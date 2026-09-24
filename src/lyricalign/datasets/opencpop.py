"""OpenCPOP (Chinese popular song, single female singer) 字符级时间轴派生。

OpenCPOP 的整曲 TextGrid 含七个 IntervalTier：句子 / 汉字 / 音节 / 音高 / 音长 / 音素 / 连音。
其中 **汉字轨给出逐字的人工起止时间**，这正是 MIR-1K 缺的东西，因此 OpenCPOP 可以直接作为
字符级对齐的**纯测试域**使用。

防火墙：本模块只做"读标注 + 派生"，不写任何训练侧产物。OpenCPOP 于 2026-09-22 才进入本机，
所有既有 checkpoint 都不曾见过它 ⇒ 只许报告，不许据此选 checkpoint（AGENTS.md 强约束）。

两种评测尺度（census 明确要求"句级与整曲两套各挂一臂，勿混尺"）：
  * ``sentence``：官方句级切段 wav（3,756 段），每段一句、逐字 GT 变成段内相对时间。与既有
    GTSinger panel 同为"短单元"尺度，可直接并列。
  * ``window``：从整曲 wav 按句子边界贪心装箱成 ≤ ``max_sec`` 的窗口（项目正式口径 fixed 60s），
    窗口音频物化到磁盘，用于跨句长时序评测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

DEFAULT_ROOT = Path("/root/autodl-tmp/AST_storage/Data_external/opencpop/Opencpop")
ALIGN_TOL_SEC = 0.02  # 句段 wav 时长与句子轨区间长度的容差
# 汉字轨里混有非歌词标记段：SP=静音/停顿，AP=换气（长度恒为 2 字符）。它们占据时间轴，
# 但不属于唱词，必须从字符级真值里剔除——否则既虚增字数，又把 5~8 s 的器乐段当成"长音"。
NON_LYRIC_TOKENS = frozenset({"SP", "AP"})
# 汉字轨里的 `_` 不是唱词，而是**前一个汉字的延音/连音续格**（melisma：一个字跨多个音符）。
# 它自己占时间，必须并入前一个汉字的区间，否则字符序列会多出 prompt 里不存在的 `_`，
# 而 melisma 合并后正是长音靶子最干净的样本来源。
CONTINUATION_TOKEN = "_"

_INTERVAL_RE = re.compile(r'xmin = ([\d.eE+-]+)\s*\n\s*xmax = ([\d.eE+-]+)\s*\n\s*text = "(.*?)"')
_TIER_BLOCK_RE = re.compile(r'class = "IntervalTier"\s*\n\s*name = "(.*?)"\s*\n(.*?)(?=\n\s*item \[\d+\]:|\s*$)', re.S)


@dataclass(frozen=True)
class Interval:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Song:
    song_id: str
    textgrid: Path
    tiers: dict[str, list[Interval]] = field(default_factory=dict)

    @property
    def sentences(self) -> list[Interval]:
        """句子轨里的真实唱句（剔除 silence）。"""
        return [iv for iv in self.tiers.get("句子", []) if iv.text.strip() and iv.text != "silence"]

    @property
    def chars(self) -> list[Interval]:
        """汉字轨里的唱词字：逐字人工边界，SP/AP 剔除，`_` 续格并入前字（melisma 合成长区间）。"""
        return self._char_index()[0]

    @property
    def melisma_chars(self) -> int:
        return self._char_index()[1]

    @property
    def orphan_continuations(self) -> int:
        return self._char_index()[2]

    def _char_index(self) -> tuple[list[Interval], int, int]:
        cached = getattr(self, "_chars_cache", None)
        if cached is not None:
            return cached
        out: list[Interval] = []
        melisma = orphan = 0
        for iv in self.tiers.get("汉字", []):
            text = iv.text.strip()
            if not text or text in NON_LYRIC_TOKENS:
                continue
            if text == CONTINUATION_TOKEN:
                if out and abs(iv.start - out[-1].end) < 1e-3:
                    out[-1] = Interval(out[-1].start, iv.end, out[-1].text)
                    melisma += 1
                else:
                    orphan += 1
                continue
            out.append(Interval(iv.start, iv.end, text))
        self._chars_cache = (out, melisma, orphan)
        return self._chars_cache

    @property
    def non_lyric(self) -> list[Interval]:
        return [iv for iv in self.tiers.get("汉字", []) if iv.text.strip() in NON_LYRIC_TOKENS]

    @property
    def slur_slots(self) -> list[Interval]:
        return [iv for iv in self.tiers.get("连音", []) if iv.text.strip() not in ("", "0")]


def parse_textgrid(path: Path) -> dict[str, list[Interval]]:
    tiers: dict[str, list[Interval]] = {}
    for name, body in _TIER_BLOCK_RE.findall(path.read_text(encoding="utf-8")):
        tiers[name] = [Interval(float(a), float(b), t) for a, b, t in _INTERVAL_RE.findall(body)]
    return tiers


def load_songs(root: Path = DEFAULT_ROOT) -> Iterator[Song]:
    tg_dir = root / "raw" / "textgrids"
    for path in sorted(tg_dir.glob("*.TextGrid")):
        yield Song(song_id=path.stem, textgrid=path, tiers=parse_textgrid(path))


def _units_of_sentence(sent: Interval, chars: list[Interval]) -> list[Interval] | None:
    """取中心落在句区间内的字，并转成句内相对时间；任何字跨界则整句作废（返回 None）。"""
    units = [c for c in chars if sent.start <= (c.start + c.end) / 2.0 < sent.end]
    if not units:
        return None
    relative = [Interval(round(u.start - sent.start, 4), round(u.end - sent.start, 4), u.text) for u in units]
    if relative[0].start < -ALIGN_TOL_SEC or relative[-1].end > sent.duration + ALIGN_TOL_SEC:
        return None
    return relative


def song_utt_ids(root: Path, song_id: str) -> list[str]:
    """曲号定长 4 位 ⇒ 前缀匹配唯一。句 utt 后 6 位是**全库累计序号**（2002 从 39 续），不能本地推算。"""
    return sorted(p.stem for p in (root / "segments" / "wavs").glob(f"{song_id}*.wav"))


def transcriptions(root: Path = DEFAULT_ROOT) -> dict[str, str]:
    """utt → 该句唱词串（transcriptions.txt 第 2 字段，`|` 分隔，权威对应关系）。"""
    out: dict[str, str] = {}
    path = root / "segments" / "transcriptions.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("|")
        if len(parts) >= 2 and parts[0].strip():
            out[parts[0].strip()] = "".join(parts[1].split())
    return out


def _sentence_index(sentences: list[Interval]) -> dict[str, "object"]:
    """唱词串 → 该串在句子轨里按时间顺序待消费的区间列表（同句重复出现时逐个配对）。"""
    from collections import defaultdict, deque
    buckets: dict[str, deque] = defaultdict(deque)
    for sent in sorted(sentences, key=lambda s: s.start):
        buckets["".join(sent.text.split())].append(sent)
    return buckets


def sentence_items(root: Path = DEFAULT_ROOT, *, max_dropped_log: int = 8) -> tuple[list[dict], dict]:
    """句级视图：一行 = 一个字。utt 与句子轨按**唱词串 + 时长**双键配对，并强制字数与唱词一致。"""
    wav_dir = root / "segments" / "wavs"
    lyrics = transcriptions(root)
    items: list[dict] = []
    dropped = {"no_wav": 0, "dur_mismatch": 0, "no_units": 0, "no_lyric_line": 0, "unmatched_sentence": 0,
               "unit_lyric_length_mismatch": 0}
    counts = {"sentences_seen": 0, "aligned": 0, "songs": 0, "songs_fully_matched": 0,
              "melisma_continuations": 0, "orphan_continuations": 0, "char_variant_segments": 0}
    logs: list[str] = []
    for song in load_songs(root):
        counts["sentences_seen"] += len(song.sentences)
        counts["songs"] += 1
        counts["melisma_continuations"] += song.melisma_chars
        counts["orphan_continuations"] += song.orphan_continuations
        buckets = _sentence_index(song.sentences)
        matched = 0
        for utt in song_utt_ids(root, song.song_id):
            lyric = lyrics.get(utt)
            if lyric is None:
                dropped["no_lyric_line"] += 1
                continue
            queue = buckets.get(lyric)
            if not queue:
                dropped["unmatched_sentence"] += 1
                if len(logs) < max_dropped_log:
                    logs.append(f"{utt}: 唱词串在句子轨里无剩余匹配 -> {lyric[:24]}")
                continue
            sent = queue.popleft()
            wav = wav_dir / f"{utt}.wav"
            if not wav.is_file():
                dropped["no_wav"] += 1
                continue
            units = _units_of_sentence(sent, song.chars)
            if units is None:
                dropped["no_units"] += 1
                if len(logs) < max_dropped_log:
                    logs.append(f"{utt}: units=None span={sent.duration:.2f}")
                continue
            duration = _wav_duration_sec(wav)
            if duration is None or abs(duration - sent.duration) > ALIGN_TOL_SEC:
                dropped["dur_mismatch"] += 1
                if len(logs) < max_dropped_log:
                    logs.append(f"{utt}: wav={round(duration,3)} vs tier={round(sent.duration, 3)}")
                continue
            # 最后一道：取到的字数必须与唱词串**等长**。注意只比长度不比文本——
            # OpenCPOP 的 transcriptions.txt 与 TextGrid 汉字轨存在系统性用字不一致
            # （实测 138 段：礡↔礴、唐↔堂、再↔在…，字数相同）。时间轴与喂给 aligner 的歌词
            # **同源取自汉字轨**，所以异体/别字不构成脏样本；而"字数不等"才说明句边界取字丢字或多字。
            joined = "".join(unit.text for unit in units)
            if len(joined) != len(lyric):
                dropped["unit_lyric_length_mismatch"] += 1
                if len(logs) < max_dropped_log:
                    logs.append(f"{utt}: 取字 {len(joined)} ≠ 唱词 {len(lyric)} | {joined[:20]} vs {lyric[:20]}")
                continue
            if joined != lyric:
                counts["char_variant_segments"] += 1
            counts["aligned"] += 1
            matched += 1
            items.append({"utt": utt, "song": song.song_id, "audio_path": str(wav),
                          "audio_dur_sec": round(duration, 3), "units": units})
        if matched == len(song.sentences):
            counts["songs_fully_matched"] += 1
    stats = {"songs_represented": len({i["song"] for i in items}), **counts, "dropped": dropped,
             "drop_log": logs}
    return items, stats


def window_items(root: Path = DEFAULT_ROOT, *, max_sec: float = 60.0, min_units: int = 8) -> tuple[list[dict], dict]:
    """整曲视图：按句子边界贪心装箱成 ≤max_sec 的窗口，音频裁剪物化由调用方负责。

    窗口只保留"完整落在窗内的句子"，因此窗口时间轴 = 整曲时间轴平移，字级 GT 保持绝对时间减窗起点。
    每个候选窗的去留原因都计入 `window_outcomes`，不静默丢弃。
    """
    wav_dir = root / "raw" / "wavs"
    items: list[dict] = []
    outcomes = {"ok": 0, "below_min_units": 0, "length_mismatch": 0}
    skipped_songs = 0

    def flush(song_id: str, sentences: list[Interval], start: float, source: Path,
              chars: list[Interval]) -> None:
        made, reason = _make_window(song_id, source, sentences, start, chars, min_units)
        outcomes[reason] += 1
        if made is not None:
            items.append(made)

    for song in load_songs(root):
        source = wav_dir / f"{song.song_id}.wav"
        if not source.is_file():
            skipped_songs += 1
            continue
        chars = song.chars
        window: list[Interval] = []
        window_start: float | None = None
        for sent in song.sentences:
            if window and window_start is not None and sent.end - window_start > max_sec:
                flush(song.song_id, window, window_start, source, chars)
                window, window_start = [], None
            if window_start is None:
                window_start = sent.start
            window.append(sent)
        if window and window_start is not None:
            flush(song.song_id, window, window_start, source, chars)
    stats = {"windows": len(items), "songs_skipped_no_wav": skipped_songs, "window_outcomes": outcomes,
             "max_sec": max_sec,
             "units": sum(len(i["units"]) for i in items),
             "short_units": sum(1 for i in items for u in i["units"] if u.duration < 0.25),
             "long_units": sum(1 for i in items for u in i["units"] if u.duration >= 1.5)}
    return items, stats


def _make_window(song_id: str, source: Path, sentences: list[Interval], start: float,
                 chars: list[Interval], min_units: int) -> tuple[dict | None, str]:
    end = sentences[-1].end
    units = [Interval(round(c.start - start, 4), round(c.end - start, 4), c.text)
             for c in chars if start <= (c.start + c.end) / 2.0 < end]
    if len(units) < min_units:
        return None, "below_min_units"
    # 与句级同一把尺：取字数必须等于窗内唱词（句轨串拼接）的字数，否则窗边界处丢了字或多字。
    lyric = "".join("".join(s.text.split()) for s in sentences)
    if len(units) != len(lyric):
        return None, "length_mismatch"
    return {"utt": f"{song_id}_w{int(round(start * 100)):06d}", "song": song_id,
            "audio_path": str(source), "window_start_sec": round(start, 4),
            "audio_dur_sec": round(end - start, 3), "units": units}, "ok"


_WAV_CACHE: dict[str, float] = {}


def _wav_duration_sec(path: Path) -> float | None:
    """不依赖 soundfile：直接读 WAV 头 + 帧数算时长。"""
    key = str(path)
    if key in _WAV_CACHE:
        return _WAV_CACHE[key]
    try:
        import wave
        with wave.open(key, "rb") as handle:
            duration = handle.getnframes() / float(handle.getframerate())
    except Exception:
        return None
    _WAV_CACHE[key] = duration
    return duration


def evidence_rows(items: list[dict], *, model: str = "r2") -> Iterator[dict]:
    """展平成 unit_evidence 同构的行（``collect_items`` 只认 model/audio_path/text/gt_*_sec）。"""
    for item in items:
        for unit in item["units"]:
            yield {"model": model, "dataset": "opencpop", "utt": item["utt"], "song": item["song"],
                   "audio_path": item["audio_path"], "text": unit.text,
                   "gt_start_sec": round(unit.start, 4), "gt_end_sec": round(unit.end, 4),
                   "gt_dur_sec": round(unit.duration, 4), "audio_dur_sec": item.get("audio_dur_sec")}
