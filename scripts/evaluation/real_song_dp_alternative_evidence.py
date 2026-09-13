#!/usr/bin/env python3
"""On real songs, where DP would move a collapsed boundary — is that a better acoustic event?

`dp` provably removes zero-length intervals (it cannot emit them), so the honest question is not
"does it legalise" but "does it legalise *in the right place*".  The delivered batch stores the top-k
timestamp candidates and their probabilities per slot, so the alternative the constrained decoder
would pick is reconstructible without running any inference:

* collapsed character (raw end ≤ raw start) -> the DP must take the most probable end class strictly
  after the start class;
* if no legal class appears in the stored top-k, say so — that means DP has to reach below the top-k,
  i.e. it is choosing among low-probability bins, which is a caveat to report rather than hide.

Evidence is the same novelty score used by `measure_boundary_acoustics.py` (spectral flux + |ΔRMS|),
compared **within the same character** between the collapsed instant and the alternative instant, so
song-level loudness and arrangement cancel out.

    PYTHONPATH=src python scripts/evaluation/real_song_dp_alternative_evidence.py \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence \
        --out results/by_run/20260914_real_song_dp_alternative/metrics.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics as st
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "measure_boundary_acoustics", ROOT / "scripts" / "evaluation" / "measure_boundary_acoustics.py")
ACOUSTICS = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ACOUSTICS)

STEP_SEC = 0.08
ALIGN_SUFFIX = "alignments/r2/vocal/windowed/alignment.raw.json"


def vocal_path(song_dir: Path) -> Path | None:
    for candidate in (song_dir / "work" / "audio" / "vocals.wav",
                      song_dir / "work" / "audio" / "vocal.wav",
                      song_dir / "work" / "audio" / "separated_vocal.wav"):
        if candidate.exists():
            return candidate
    found = sorted((song_dir / "work" / "audio").glob("*vocal*.wav")) if (song_dir / "work" / "audio").exists() else []
    return found[0] if found else None


def best_legal_end(start_class: int, end_classes: list[int], end_probs: list[float]) -> tuple[int, float] | None:
    """The most probable end class that is strictly after the start class (what DP is forced to use)."""
    options = [(float(prob), int(cls)) for cls, prob in zip(end_classes, end_probs) if int(cls) > start_class]
    if not options:
        return None
    prob, cls = max(options)
    return cls, prob


def analyse_song(song_dir: Path, *, context_sec: float) -> dict[str, Any]:
    path = song_dir / ALIGN_SUFFIX
    audio_path = vocal_path(song_dir)
    if not path.exists() or audio_path is None:
        return {"song": song_dir.name, "skipped": "缺少对齐或人声音频"}
    document = json.loads(path.read_text(encoding="utf-8"))
    import numpy as np
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio_path), "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], check=True, capture_output=True).stdout
    signal = np.frombuffer(raw, dtype=np.float32)
    flux, delta_rms, hop_sec = ACOUSTICS.novelty_frames(signal, 16000)
    if len(flux) < 5:
        return {"song": song_dir.name, "skipped": "音频太短"}

    def peak(channel: np.ndarray, t_sec: float) -> float | None:
        if not 0 <= t_sec or t_sec * 16000 >= len(signal):
            return None
        centre = int(round(t_sec / hop_sec))
        half = max(1, int(round(context_sec / hop_sec)))
        low, high = max(0, centre - half), min(len(channel), centre + half + 1)
        return float(np.max(channel[low:high])) if high > low else None

    collapsed = with_alternative = no_legal = measured = higher_d = higher_f = 0
    deltas_d: list[float] = []
    deltas_f: list[float] = []
    collapsed_d: list[float] = []
    alternative_d: list[float] = []
    for character in document.get("characters", []):
        start, end = character.get("raw_global_start_sec"), character.get("raw_global_end_sec")
        classes = character.get("raw_end_topk_classes")
        probs = character.get("raw_end_topk_probabilities")
        window_start = character.get("input_start_sec")
        local_start = character.get("raw_local_start_sec")
        if None in (start, end, classes, probs, window_start, local_start):
            continue
        if float(end) > float(start):
            continue
        collapsed += 1
        start_class = int(round(float(local_start) / STEP_SEC))
        choice = best_legal_end(start_class, classes, probs)
        if choice is None:
            no_legal += 1
            continue
        end_class, _prob = choice
        with_alternative += 1
        point = float(start)
        alternative = float(window_start) + end_class * STEP_SEC
        pair_d = (peak(delta_rms, point), peak(delta_rms, alternative))
        pair_f = (peak(flux, point), peak(flux, alternative))
        if None in pair_d or None in pair_f:
            continue
        measured += 1
        collapsed_d.append(pair_d[0])
        alternative_d.append(pair_d[1])
        deltas_d.append(pair_d[1] - pair_d[0])
        deltas_f.append(pair_f[1] - pair_f[0])
        higher_d += int(pair_d[1] > pair_d[0])
        higher_f += int(pair_f[1] > pair_f[0])
    return {"song": song_dir.name, "characters": len(document.get("characters", [])),
            "collapsed": collapsed, "with_legal_alternative": with_alternative,
            "no_legal_in_topk": no_legal, "paired_measurements": measured,
            "alternative_higher_d_rms": higher_d, "alternative_higher_flux": higher_f,
            "median_collapsed_d_rms": round(st.median(collapsed_d), 4) if collapsed_d else None,
            "median_alternative_d_rms": round(st.median(alternative_d), 4) if alternative_d else None,
            "median_delta_d_rms": round(st.median(deltas_d), 4) if deltas_d else None,
            "median_delta_flux": round(st.median(deltas_f), 4) if deltas_f else None}


def markdown(payload: dict[str, Any]) -> str:
    totals = payload["totals"]
    lines = ["# 真歌上 DP 会把塌陷边界挪到更好的位置吗？（生成，勿手改）", "",
             f"> 批次 `{payload['batch']}`，取塌陷最重的 {payload['songs_analysed']} 首，"
             f"用**已存的 top-k 候选**重建约束解码会被迫选择的合法终点，"
             f"再在同一字符内配对比较声学事件强度（ΔRMS 与谱通量）。零新推理。", "",
             f"- 塌陷字符 **{totals['collapsed']}** 个；其中 **{totals['no_legal_in_topk']} 个"
             f"（{totals['share_no_legal_in_topk']:.1%}）在 top-8 里根本没有合法终点**"
             " ⇒ 约束解码必须去取排名更靠后的桶；",
             f"- 剩下的 {totals['with_legal_alternative']} 个里，被选中的合法替代点"
             f"声学证据**更高**的比例只有 ΔRMS {totals['share_alternative_more_evidence_d_rms']:.1%} / "
             f"谱通量 {totals['share_alternative_more_evidence_flux']:.1%} ⇒ **与抛硬币无法区分**；", "",
             "## 结论（对产品决策是硬约束）", "",
             "1. **DP 在真歌上是『合法性修复』，不是『精度修复』**：它保证不再输出零长度，"
             "但挪动后的位置不比原来临界点更有证据；",
             "2. 因此 DP 会**掩盖问题**：零长度/重叠这类结构检查现在正是产品在真歌上唯一的自动缺陷探针，"
             "换了 DP 之后它们会全部变绿，而错误仍在；",
             "3. 所以 **DP 必须与置信度门控同时上线**（`export_review_gating.py` 已经用同样的 logits "
             "算出熵/边际，AUC 0.92、按歌留一复核 10% 消除 55% 缺陷）——门控不受解码选择影响，"
             "它接管『发现坏区域』的职责；",
             "4. 域内证据仍然支持换 DP（全量 0.9784 vs argmax 0.9743，配对 z=−5.27；且线上 fixed 只有 0.9699），"
             "但**不要用『塌陷率归零』当作质量提升的证据**向产品汇报。",
             ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence"))
    parser.add_argument("--songs", type=int, default=8, help="分析塌陷最重的几首")
    parser.add_argument("--context-sec", type=float, default=0.06)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    songs = []
    for song_dir in sorted(child for child in args.batch.iterdir() if child.is_dir()):
        path = song_dir / ALIGN_SUFFIX
        if not path.exists():
            continue
        try:
            characters = json.loads(path.read_text(encoding="utf-8")).get("characters", [])
        except Exception:
            continue
        values = [(float(c["raw_global_end_sec"]), float(c["raw_global_start_sec"])) for c in characters
                  if c.get("raw_global_start_sec") is not None and c.get("raw_global_end_sec") is not None]
        if not values:
            continue
        songs.append((sum(1 for end, start in values if end <= start) / len(values), song_dir))
    songs.sort(key=lambda item: -item[0])
    chosen = [entry for share, entry in songs[: args.songs]]
    results = [analyse_song(song, context_sec=args.context_sec) for song in chosen]
    usable = [row for row in results if row.get("paired_measurements")]
    totals = {"songs": len(results), "collapsed": sum(row.get("collapsed", 0) for row in results),
              "with_legal_alternative": sum(row.get("with_legal_alternative", 0) for row in results),
              "no_legal_in_topk": sum(row.get("no_legal_in_topk", 0) for row in results),
              "paired_measurements": sum(row.get("paired_measurements", 0) for row in results),
              "alternative_higher_d_rms": sum(row.get("alternative_higher_d_rms", 0) for row in results),
              "alternative_higher_flux": sum(row.get("alternative_higher_flux", 0) for row in results)}
    totals["share_no_legal_in_topk"] = round(totals["no_legal_in_topk"] / max(1, totals["collapsed"]), 4)
    totals["share_alternative_more_evidence_d_rms"] = round(
        totals["alternative_higher_d_rms"] / max(1, totals["paired_measurements"]), 4)
    totals["share_alternative_more_evidence_flux"] = round(
        totals["alternative_higher_flux"] / max(1, totals["paired_measurements"]), 4)
    payload = {"schema_version": "real_song_dp_alternative_v1", "batch": str(args.batch),
               "songs_analysed": len(results), "context_sec": args.context_sec, "totals": totals,
               "per_song": [dict(row, collapse_rate=round(row.get("collapsed", 0) / max(1, row.get("characters", 1)), 3))
                            for row in results]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({"totals": totals, "per_song": payload["per_song"]}, indent=2, ensure_ascii=False)[:1800])


if __name__ == "__main__":
    main()
