"""OpenCPOP 字符级派生的回归测试（不依赖 15 G 真实数据，用 tmp_path 造迷你目录）。

锁的是**最容易静默污染结论**的四处：
1. `_` 连音续格必须并入前字（否则唱词序列里出现 prompt 不存在的 `_`，长音样本也被拆碎）；
2. SP/AP 必须剔除（否则把 5~8 s 的器乐段当"长音"，长音供给虚高数倍）；
3. utt ↔ 句子轨必须按**唱词串 + 时长**配对，不能按序号推算（真实数据里 utt 后 6 位是全库累计序号，
   按"每曲从 1"推算会在多首歌上整体错位）；
4. 任何不符（时长、取字数与唱词不符、无剩余区间）都要**显式计数丢弃**，不许静默接受。
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.datasets.opencpop import (  # noqa: E402
    evidence_rows,
    load_songs,
    parse_textgrid,
    sentence_items,
)

SONG_INTERVALS = [
    (0.0, 4.0, "silence"),
    (4.0, 7.0, "月亮代表我的心"),
    (7.0, 12.0, "月亮代表我的心"),
    (12.0, 20.0, "在你心里面唱一首歌"),
]

# 句1：月(0.2s)+_(0.4s 续格 ⇒ 合成 0.6s)、亮代表我的各 0.3、心 0.9s
CHAR_INTERVALS = [
    (0.0, 4.0, "SP"),
    (4.0, 4.2, "月"), (4.2, 4.6, "_"), (4.6, 4.9, "亮"), (4.9, 5.2, "代"),
    (5.2, 5.5, "表"), (5.5, 5.8, "我"), (5.8, 6.1, "的"), (6.1, 7.0, "心"),
    (7.0, 7.1, "AP"),
    (7.1, 7.6, "月"), (7.6, 8.1, "亮"), (8.1, 8.6, "代"), (8.6, 9.1, "表"),
    (9.1, 9.6, "我"), (9.6, 10.1, "的"), (10.1, 10.9, "心"), (10.9, 12.0, "SP"),
    (12.0, 12.4, "在"), (12.4, 12.8, "你"), (12.8, 13.2, "心"), (13.2, 13.6, "里"),
    (13.6, 14.0, "面"), (14.0, 14.4, "唱"), (14.4, 14.8, "一"), (14.8, 15.2, "首"),
    (15.2, 15.6, "歌"), (15.6, 20.0, "SP"),
]


def _textgrid(tier_name: str, intervals: list[tuple[float, float, str]]) -> str:
    body = "".join(f"\t\t\tintervals [{i}]:\n\t\t\t\txmin = {a}\n\t\t\t\txmax = {b}\n"
                   f'\t\t\t\ttext = "{t}"\n' for i, (a, b, t) in enumerate(intervals, start=1))
    return ('item [%d]:\n\t\tclass = "IntervalTier"\n\t\tname = "%s"\n\t\txmin = 0.0\n\t\txmax = 30.0\n'
            '\t\tintervals: size = %d\n%s' % (0, tier_name, len(intervals), body))


def _write_textgrid(path: Path, char_intervals: list[tuple[float, float, str]] | None = None) -> None:
    tiers = [_textgrid("句子", SONG_INTERVALS), _textgrid("汉字", char_intervals or CHAR_INTERVALS)]
    for index, tier in enumerate(tiers, start=1):
        tiers[index - 1] = tier.replace("item [0]:", f"item [{index}]:", 1)
    path.write_text('File type = "ooTextFile"\nObject class = "TextGrid"\n\nxmin = 0.0\nxmax = 30.0\n'
                    "tiers? <exists>\nsize = 2\nitem []:\n" + "\n".join(tiers), encoding="utf-8")


def _write_wav(path: Path, seconds: float) -> None:
    rate = 44100
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(round(seconds * rate)))


def _make_root(tmp_path: Path, *, utt_ids: list[str], durations: dict[str, float],
               lyric_overrides: dict[str, str] | None = None,
               char_intervals: list[tuple[float, float, str]] | None = None) -> Path:
    """默认唱词按 SONG_INTERVALS 顺序取；utt 编号故意用全库累计序号（37/38/39）。"""
    default_lyric = [t for _, _, t in SONG_INTERVALS if t != "silence"]
    root = tmp_path / "Opencpop"
    (root / "raw" / "textgrids").mkdir(parents=True)
    (root / "segments" / "wavs").mkdir(parents=True)
    _write_textgrid(root / "raw" / "textgrids" / "1001.TextGrid", char_intervals)
    lines = []
    for index, utt in enumerate(utt_ids):
        lyric = (lyric_overrides or {}).get(utt, default_lyric[index % len(default_lyric)])
        lines.append(f"{utt}|{lyric}|rest")
    (root / "segments" / "transcriptions.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for utt, seconds in durations.items():
        _write_wav(root / "segments" / "wavs" / f"{utt}.wav", seconds)
    return root


def test_tier_parse_and_melisma_merge(tmp_path: Path) -> None:
    root = _make_root(tmp_path, utt_ids=[], durations={})
    song = next(load_songs(root))
    assert {"句子", "汉字"} <= set(parse_textgrid(song.textgrid))
    assert len(song.sentences) == 3, "silence 句区间必须剔除"
    assert song.chars[0].text == "月" and abs(song.chars[0].duration - 0.6) < 1e-6, "续格必须并入前字"
    assert song.melisma_chars == 1 and song.orphan_continuations == 0
    texts = [c.text for c in song.chars]
    assert "_" not in texts and "SP" not in texts and "AP" not in texts
    assert len(texts) == 7 + 7 + 9, f"SP/AP/续格剔除后的字数不符: {len(texts)}"


def test_utt_matched_by_lyric_not_by_numbering(tmp_path: Path) -> None:
    ids = ["1001000037", "1001000038", "1001000039"]
    root = _make_root(tmp_path, utt_ids=ids, durations={"1001000037": 3.0, "1001000038": 5.0,
                                                        "1001000039": 2.0})
    items, stats = sentence_items(root)
    assert stats["aligned"] == 2, "第三段时长与句区间不符，必须被 dur_mismatch 丢弃"
    assert stats["dropped"]["dur_mismatch"] == 1
    assert stats["dropped"]["unit_lyric_length_mismatch"] == 0
    assert [i["utt"] for i in items] == ids[:2]
    assert [u.text for u in items[0]["units"]] == list("月亮代表我的心")
    assert items[0]["units"][0].start == pytest.approx(0.0)
    assert items[0]["units"][0].duration == pytest.approx(0.6)
    # 重复唱词串按时间顺序逐个消费 ⇒ 第二段拿到的是 7.0→12.0 那个区间
    assert items[1]["units"][0].start == pytest.approx(0.1)


def test_unmatched_lyric_is_dropped(tmp_path: Path) -> None:
    """唱词串在句子轨里根本不存在 ⇒ unmatched_sentence，不许拿相邻区间凑数。"""
    ids = ["1001000037"]
    root = _make_root(tmp_path, utt_ids=ids, durations={"1001000037": 3.0},
                      lyric_overrides={"1001000037": "月亮代表我的心啊"})
    items, stats = sentence_items(root)
    assert items == []
    assert stats["dropped"]["unmatched_sentence"] == 1


def test_char_count_mismatch_is_dropped(tmp_path: Path) -> None:
    """句轨串完整、汉字轨少一个字 ⇒ 取字与唱词不等，必须走 unit_lyric_mismatch 而不是将就用。"""
    ids = ["1001000037", "1001000038", "1001000039"]
    trimmed = [iv for iv in CHAR_INTERVALS if iv[2] != "歌"]
    root = _make_root(tmp_path, utt_ids=ids,
                      durations={"1001000037": 3.0, "1001000038": 5.0, "1001000039": 8.0},
                      char_intervals=trimmed)
    items, stats = sentence_items(root)
    assert stats["aligned"] == 2
    assert stats["dropped"]["unit_lyric_length_mismatch"] == 1
    assert stats["dropped"]["dur_mismatch"] == 0


def test_char_variant_but_same_length_is_kept(tmp_path: Path) -> None:
    """OpenCPOP 的 transcriptions 与汉字轨存在异体/别字（礡↔礴、唐↔堂）。
    时间轴与 prompt 同源取汉字轨 ⇒ 字数相同就保留，只计数不丢弃。"""
    ids = ["1001000037"]
    root = _make_root(tmp_path, utt_ids=ids, durations={"1001000037": 3.0})
    # 汉字轨把"心"写成异体"芯"（唱词仍写"心"）：等长、文本不等
    _write_textgrid(root / "raw" / "textgrids" / "1001.TextGrid",
                    [(a, b, ("芯" if t == "心" else t)) for a, b, t in CHAR_INTERVALS])
    items, stats = sentence_items(root)
    assert stats["aligned"] == 1, "等长的异体字差异不该丢样本"
    assert stats["char_variant_segments"] == 1
    assert items[0]["units"][0].text == "月"


def test_evidence_rows_are_flat_per_char(tmp_path: Path) -> None:
    ids = ["1001000037", "1001000038"]
    root = _make_root(tmp_path, utt_ids=ids, durations={"1001000037": 3.0, "1001000038": 5.0})
    items, _ = sentence_items(root)
    rows = list(evidence_rows(items))
    assert rows and all(row["model"] == "r2" and row["dataset"] == "opencpop" for row in rows)
    assert set(rows[0]) >= {"audio_path", "text", "gt_start_sec", "gt_end_sec", "gt_dur_sec", "utt", "song"}
    assert rows[0]["text"] == "月" and rows[0]["gt_start_sec"] == 0.0
    assert all(row["gt_end_sec"] > row["gt_start_sec"] for row in rows), "不允许零长度真值"
    assert len(rows) == 14
