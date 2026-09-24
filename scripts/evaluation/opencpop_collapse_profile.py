#!/usr/bin/env python3
"""零人工的 OpenCPOP 塌陷画像：把"哪些字糊在同一个时刻"自动归类。

输入是 `ood_dp_replay.py --dump-units` 的逐单元产物（gt/official/dp 起止 + top-1 + 熵 + 容差内质量），
外加窗音频本身（算能量代理，判断那段到底有没有声音）。**全程不需要人听**，每条判据都可复算。

    PYTHONPATH=src python scripts/evaluation/opencpop_collapse_profile.py \
        --dump /home/hyan/Data/lyricalign/runs/20260924_opencpop_eval/units_window_old750.jsonl.gz \
        --out  docs/status/20260924_opencpop_collapse.md
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics as st
import subprocess
from collections import defaultdict
from pathlib import Path

TOL = 0.2
MIN_BLOCK = 5


def load_units(path: Path) -> dict[str, list[dict]]:
    by_item: dict[str, list[dict]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                by_item[row["utt"]].append(row)
    for rows in by_item.values():
        rows.sort(key=lambda r: r["unit_index"])
    return dict(by_item)


def err_stats(pairs: list[tuple[float, float]]) -> dict:
    errs = sorted(abs(p - g) for g, p in pairs if p is not None)
    if not errs:
        return {"n": 0}
    return {"n": len(errs), "miss_share": round(sum(1 for e in errs if e > TOL) / len(errs), 4),
            "median_ms": round(1000 * st.median(errs), 1), "p90_ms": round(1000 * errs[int(0.9 * (len(errs) - 1))], 1),
            "mean_ms": round(1000 * st.mean(errs), 1)}


def collapse_blocks(rows: list[dict], decoder: str) -> list[list[dict]]:
    """同一 item 内连续 ≥MIN_BLOCK 个单元的结束点完全相同 = 塌陷块。"""
    key = f"{decoder}_end_sec"
    blocks: list[list[dict]] = []
    run: list[dict] = []
    for row in rows:
        if run and row.get(key) != run[-1].get(key):
            if len(run) >= MIN_BLOCK:
                blocks.append(run)
            run = []
        run.append(row)
    if len(run) >= MIN_BLOCK:
        blocks.append(run)
    return blocks


def audio_probe(path: str, start: float, end: float) -> dict:
    """该时间段的声学代理：帧 RMS 与"有声帧占比"。不依赖任何标注或人工。"""
    try:
        import numpy as np
        result = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}",
                                 "-t", f"{max(0.05, end - start):.3f}", "-i", path,
                                 "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                                check=True, capture_output=True)
        samples = np.frombuffer(result.stdout, dtype=np.float32)
    except Exception as error:  # noqa: BLE001
        return {"available": False, "reason": str(error)[:60]}
    if samples.size < 160:
        return {"available": False, "reason": "too_short"}
    frame = 400
    count = samples.size // frame
    rms = np.sqrt((samples[:count * frame].reshape(count, frame) ** 2).mean(axis=1))
    floor = float(np.percentile(rms, 10))
    voiced = float((rms > max(floor + 0.01, 0.02 * float(rms.max()))).mean())
    onset_density = float((np.diff(rms) > 0.25 * float(rms.max())).mean())
    return {"available": True, "voiced_share": round(voiced, 3), "rms_max": round(float(rms.max()), 4),
            "onset_density": round(onset_density, 3)}


def classify(block: list[dict], probe: dict, mass_median: float) -> list[str]:
    tags: list[str] = []
    durations = [row["gt_end_sec"] - row["gt_start_sec"] for row in block]
    median_dur = st.median(durations)
    span = block[-1]["gt_end_sec"] - block[0]["gt_start_sec"]
    if median_dur >= 0.5:
        tags.append("长音收尾糊（块内 GT 时长中位 ≥0.5 s）")
    elif median_dur <= 0.25:
        tags.append("密集念白糊（块内 GT 时长中位 ≤0.25 s）")
    else:
        tags.append("中等时长糊")
    if span / max(median_dur, 1e-6) >= 8:
        tags.append(f"整块被压进一个时刻，GT 本应跨 {span:.2f} s")
    if mass_median < 0.2:
        tags.append("候选里根本没有正确答案（mass-in-tolerance <0.2 ⇒ 后处理救不了）")
    if probe.get("available") and probe["voiced_share"] < 0.2:
        tags.append("该段本身近乎无声（voiced 占比 <20 %）⇒ 更像静音归属问题而非对齐问题")
    return tags


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True, help="units_*.jsonl.gz")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--decoder", default="official")
    parser.add_argument("--max-cases", type=int, default=12)
    args = parser.parse_args()

    by_item = load_units(args.dump)
    rows_all = [row for rows in by_item.values() for row in rows]
    decoders = [d for d in ("official", "dp") if f"{d}_end_sec" in (rows_all[0] if rows_all else {})]

    lines = [f"# OpenCPOP 塌陷自动画像（{args.dump.name}）", "",
             "> 由 `scripts/evaluation/opencpop_collapse_profile.py` 从逐单元 dump 生成，零人工判读；"
             "每条判据的算法写在脚本里，可复算。", "",
             f"- 条目 {len(by_item):,} 个，逐单元记录 {len(rows_all):,} 行", ""]

    lines += ["## 起始点 vs 结束点（这就是「只比结束点」补上的另一半）", "",
              "| 解码器 | 轴 | 单元 | 超差率@0.2s | 中位(ms) | p90(ms) | 均值(ms) |", "|---|---|---:|---:|---:|---:|---:|"]
    for decoder in decoders:
        for axis in ("start", "end"):
            stats = err_stats([(row[f"gt_{axis}_sec"], row.get(f"{decoder}_{axis}_sec")) for row in rows_all])
            if stats.get("n"):
                lines.append(f"| {decoder} | {axis} | {stats['n']:,} | {100 * stats['miss_share']:.2f} % | "
                             f"{stats['median_ms']} | {stats['p90_ms']} | {stats['mean_ms']} |")
    lines.append("")

    # 时长误差：起止都错但时长对 / 时长错 的分离
    for decoder in decoders:
        dur_err = [abs((row[f"{decoder}_end_sec"] - row[f"{decoder}_start_sec"])
                       - (row["gt_end_sec"] - row["gt_start_sec"])) for row in rows_all
                   if row.get(f"{decoder}_end_sec") is not None and row.get(f"{decoder}_start_sec") is not None]
        if dur_err:
            dur_err.sort()
            lines.append(f"- `{decoder}` 时长误差：中位 {1000 * st.median(dur_err):.1f} ms，"
                         f"p90 {1000 * dur_err[int(0.9 * (len(dur_err) - 1))]:.0f} ms，"
                         f">200 ms 占比 {100 * sum(1 for e in dur_err if e > TOL) / len(dur_err):.2f} %")
    lines.append("")

    for decoder in decoders:
        blocks = [(utt, rows, block) for utt, rows in by_item.items() for block in collapse_blocks(rows, decoder)]
        illegal_units = sum(len(b) for _, _, b in blocks)
        lines += [f"## `{decoder}` 的塌陷块（连续 ≥{MIN_BLOCK} 字共用同一结束点）", "",
                  f"- 命中 {len(blocks)} 块，涉及 {illegal_units:,} 字"
                  f"（占全部字的 {100 * illegal_units / max(1, len(rows_all)):.2f} %）", ""]
        if not blocks:
            lines += ["无。", ""]
            continue
        lines += [f"| # | 条目 | 共用时刻(s) | 块内字数 | 模型顶格 | GT 应跨(s) | GT 时长中位(s) | "
                  f"end top-1 | end 熵 | mass-in-tol | voiced 占比 | 起音密度 | 自动判读 |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for index, (utt, rows, block) in enumerate(blocks[:args.max_cases], start=1):
            mass = [row.get("end_mass_in_tol") for row in block if row.get("end_mass_in_tol") is not None]
            mass_median = st.median(mass) if mass else 0.0
            top1 = st.median([row.get("end_top1", 0) for row in block])
            ent = st.median([row.get("end_entropy", 0) for row in block])
            span = block[-1]["gt_end_sec"] - block[0]["gt_start_sec"]
            median_dur = st.median([row["gt_end_sec"] - row["gt_start_sec"] for row in block])
            probe = audio_probe(utt, block[0]["gt_start_sec"], block[-1]["gt_end_sec"])
            tags = classify(block, probe, mass_median)
            shared = rows[block[0]["unit_index"]][f"{decoder}_end_sec"]
            lines.append(f"| {index} | {Path(utt).name} | {shared:.3f} | {len(block)} | "
                         f"{block[0]['text']}…{block[-1]['text']} | {span:.2f} | {median_dur:.2f} | "
                         f"{top1:.2f} | {ent:.2f} | {mass_median:.2f} | "
                         f"{probe.get('voiced_share', '—')} | {probe.get('onset_density', '—')} | "
                         + "；".join(tags) + " |")
        lines.append("")
        lines.append("**块内唱词抽样（前 3 块，用于核对判读，不代表人工结论）**：")
        for index, (utt, rows, block) in enumerate(blocks[:3], start=1):
            lines.append(f"- 块 {index}：`{Path(utt).name}` "
                         + " ".join(f"{row['text']}[{row['gt_start_sec']:.2f}-{row['gt_end_sec']:.2f}"
                                    f"→{row[f'{decoder}_end_sec']:.2f}]" for row in block[:12]))
        lines.append("")
        units = [row for _, _, block in blocks for row in block]
        if units:
            lines += ["**这些塌陷字到底错多重、DP 与门控能不能救（全自动，无需人听）**：", ""]
            for other in decoders:
                ends = sorted(abs(row[f"{other}_end_sec"] - row["gt_end_sec"]) for row in units)
                starts = sorted(abs(row[f"{other}_start_sec"] - row["gt_start_sec"]) for row in units)
                lines.append(
                    f"- `{other}`：结束点中位误差 {1000 * st.median(ends):.0f} ms"
                    f"（p90 {1000 * ends[int(0.9 * (len(ends) - 1))]:.0f} ms，超差率 "
                    f"{100 * sum(1 for e in ends if e > TOL) / len(ends):.1f} %）；"
                    f"起始点中位 {1000 * st.median(starts):.0f} ms（超差率 "
                    f"{100 * sum(1 for e in starts if e > TOL) / len(starts):.1f} %）")
            collapsed = {id(row) for row in units}
            rest = [row for rows in by_item.values() for row in rows if id(row) not in collapsed]
            hit = sum(1 for row in units if row.get("end_top1", 1.0) < 0.2)
            base = sum(1 for row in rest if row.get("end_top1", 1.0) < 0.2)
            lift = (hit / len(units)) / max(base / max(len(rest), 1), 1e-9)
            lines.append(f"- 门控召回：`end_top1 < 0.2` 自动抓到 **{hit}/{len(units)}** 个塌陷字"
                         f"（{100 * hit / len(units):.0f} %），而其余 {len(rest):,} 个字里只有 "
                         f"{100 * base / max(len(rest), 1):.2f} % 触发 ⇒ 提升约 {lift:.0f} 倍；"
                         "置信度漏掉的那部分（多为近乎无声的段）应由能量/静音探针兜住。")
            lines += ["", "> **结构合法化（DP）不等于铺对**——上面 `dp` 行的误差就是证据。"
                         "这条以前在真歌批上无法量化（那里没有人工真值），OpenCPOP 第一次给出了可判读的对照。", ""]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()
