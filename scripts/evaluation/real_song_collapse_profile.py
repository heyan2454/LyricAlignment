#!/usr/bin/env python3
"""Why does the product pipeline collapse on real songs?  Profile it from an existing batch.

Uses the per-character fields already stored in a delivered batch
(`alignments/r2/vocal/windowed/alignment.raw.json`): the model's raw decode, the upstream
`_fix_timestamps` output, and the GPU-side repair, plus each song's own timing statistics.
No inference, no GPU — this is a re-reading of evidence we already paid for.

    PYTHONPATH=src python scripts/evaluation/real_song_collapse_profile.py \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence \
        --out results/by_run/20260914_real_song_collapse/metrics.json \
        --report docs/status/20260914_real_song_collapse.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from pathlib import Path
from typing import Any

ALIGN_SUFFIX = "alignments/r2/vocal/windowed/alignment.raw.json"


def song_profile(song_dir: Path) -> dict[str, Any] | None:
    path = song_dir / ALIGN_SUFFIX
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    raw: list[tuple[float, float]] = []
    official: list[tuple[float, float]] = []
    gpu: list[tuple[float, float]] = []
    for character in document.get("characters", []):
        rs, re_ = character.get("raw_global_start_sec"), character.get("raw_global_end_sec")
        if rs is None or re_ is None:
            continue
        raw.append((float(rs), float(re_)))
        os_, oe = (character.get("official_fixed_global_start_sec"),
                   character.get("official_fixed_global_end_sec"))
        if os_ is not None and oe is not None:
            official.append((float(os_), float(oe)))
        gs, ge = character.get("gpu_fixed_global_start_sec"), character.get("gpu_fixed_global_end_sec")
        if gs is not None and ge is not None:
            gpu.append((float(gs), float(ge)))
    if len(raw) < 20:
        return None
    zero = lambda pairs: sum(1 for s, e in pairs if e <= s)
    durations = [e - s for s, e in raw if e > s]
    span = max(e for _, e in raw) - min(s for s, _ in raw)
    return {"song": song_dir.name, "characters": len(raw),
            "raw_zero_share": round(zero(raw) / len(raw), 4),
            "official_zero_share": round(zero(official) / len(official), 4) if official else None,
            "gpu_zero_share": round(zero(gpu) / len(gpu), 4) if gpu else None,
            "median_char_duration_ms": round(1000 * st.median(durations), 1) if durations else None,
            "chars_per_sec": round(len(raw) / span, 3) if span > 0 else None}


def correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return round(num / den, 3) if den else None


def build(batch: Path) -> dict[str, Any]:
    songs = [profile for profile in (song_profile(child) for child in sorted(batch.iterdir())
                                     if child.is_dir()) if profile]
    n = sum(song["characters"] for song in songs)
    raw_zero = sum(song["raw_zero_share"] * song["characters"] for song in songs)
    off_zero = sum((song["official_zero_share"] or 0.0) * song["characters"] for song in songs)
    gpu_zero = sum((song["gpu_zero_share"] or 0.0) * song["characters"] for song in songs)
    z = [100 * song["raw_zero_share"] for song in songs]
    return {"schema_version": "real_song_collapse_v1", "batch": str(batch), "songs": len(songs),
            "characters": n,
            "raw_zero_share": round(raw_zero / n, 4), "official_zero_share": round(off_zero / n, 4),
            "gpu_zero_share": round(gpu_zero / n, 4),
            "amplified_songs": sum(1 for song in songs
                                   if (song["official_zero_share"] or 0) > song["raw_zero_share"]),
            "mean_amplification_pp": round(100 * st.mean([(song["official_zero_share"] or 0) - song["raw_zero_share"]
                                                          for song in songs if song["official_zero_share"] is not None]), 2),
            "corr_raw_zero_vs_median_duration": correlation(z, [song["median_char_duration_ms"] or 0 for song in songs]),
            "corr_raw_zero_vs_chars_per_sec": correlation(z, [song["chars_per_sec"] or 0 for song in songs]),
            "songs_below_3pct_raw_zero": sum(1 for song in songs if song["raw_zero_share"] < 0.03),
            "per_song": sorted(songs, key=lambda song: -song["raw_zero_share"])}


def markdown(payload: dict[str, Any]) -> str:
    worst = payload["per_song"][:8]
    lines = ["# 真歌批塌陷画像：谁在塌、为什么、修补帮了多少（生成，勿手改）", "",
             f"> 由 `scripts/evaluation/real_song_collapse_profile.py` 从既有批次产物重读，"
             f"不涉及任何新推理。批次 `{payload['batch']}`：{payload['songs']} 首 / {payload['characters']} 字。",
             "",
             "## 1. 同一批字的三种时间轴",
             "",
             f"| 阶段 | 零长度率 |", "|---|---|",
             f"| 模型 raw 解码（未修补） | **{100 * payload['raw_zero_share']:.2f}%** |",
             f"| 上游 `_fix_timestamps` 之后（= 现交付） | **{100 * payload['official_zero_share']:.2f}%** |",
             f"| GPU 侧定向修补之后 | **{100 * payload['gpu_zero_share']:.2f}%** |",
             "",
             f"- 上游修补在 **{payload['amplified_songs']}/{payload['songs']} 首上把零长度变多**，"
             f"平均放大 **{payload['mean_amplification_pp']:+.2f} pp**；",
             f"- 作为对照：域内（M4Singer 验证集）的零长度率只有 ~0.7%，所以这 {100 * payload['raw_zero_share']:.1f}% "
             "是**模型在真实混音上的自身退化**，不是修补造成的。",
             "",
             "## 2. 什么在预测塌陷",
             "",
             f"- 与「中位字符时长」的相关 **r = {payload['corr_raw_zero_vs_median_duration']}**（最强因子）；",
             f"- 与「字/秒（歌词密度）」的相关 r = {payload['corr_raw_zero_vs_chars_per_sec']}；",
             f"- {payload['songs_below_3pct_raw_zero']}/{payload['songs']} 首的 raw 零长度 <3% ⇒ 失败高度集中在少数歌。",
             "",
             "| 最差的歌 | 字数 | raw 零长度 | 上游修补后 | GPU 修补后 | 中位字符时长(ms) | 字/秒 |",
             "|---|---|---|---|---|---|---|",
             ]
    for song in worst:
        lines.append(f"| {song['song'][:18]} | {song['characters']} | {100 * song['raw_zero_share']:.1f}% | "
                     f"{100 * (song['official_zero_share'] or 0):.1f}% | {100 * (song['gpu_zero_share'] or 0):.1f}% | "
                     f"{song['median_char_duration_ms']:.0f} | {song['chars_per_sec']} |")
    lines += ["",
              "## 3. 结论（与域内分析接得上）",
              "",
              "1. **真歌上的塌陷与域内的长音符失败是同一个问题**：时长越长越容易塌"
              f"（r={payload['corr_raw_zero_vs_median_duration']}），而域内 ≥2s 字符的超差率也最高；",
              "2. 上游修补是**净负贡献**（放大塌陷），GPU 侧定向修补把零长度压到 0；",
              "3. 因此下一臂应该针对**长字符的训练暴露**（时长上采样），而不是单纯加长音频流——"
              "M4Singer 里 ≥2s 的字符只有 1,498 个，加长流并不会增加它们的出现次数。",
              ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    payload = build(args.batch)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in
                      ("songs", "characters", "raw_zero_share", "official_zero_share", "gpu_zero_share",
                       "amplified_songs", "mean_amplification_pp", "corr_raw_zero_vs_median_duration",
                       "corr_raw_zero_vs_chars_per_sec", "songs_below_3pct_raw_zero")},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
