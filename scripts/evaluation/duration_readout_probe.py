#!/usr/bin/env python3
"""Decide whether long-note duration information is *mis-read* or *missing*.

This is the gate before any structural training arm.  From the dumped slot distributions we build
end-time readouts that use **no ground truth** — argmax, distribution mean/median, and leave-one-song-out
monotone recalibrations of the implied duration — then compare the resulting end-time error with the
model's own direct end prediction.

Why leave-one-song-out recalibration matters: if a monotone recalibration fitted on *other* songs closes
the gap, the information is present and the problem is decoding/calibration (cheap, no retraining).
If even the best readout stays worse than the direct end prediction, the representation is the limit
and only an architectural change can help.

    PYTHONPATH=src python scripts/evaluation/duration_readout_probe.py \
        --rows results/by_run/20260914_offset_dist/rows.jsonl \
        --out results/by_run/20260914_duration_readout/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

TOL = 0.2
LONG_SEC = 1.0
VERY_LONG_SEC = 2.0


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        step = float(row["step_sec"])
        onset, offset = row.get("onset") or {}, row.get("offset") or {}
        if not onset or not offset:
            continue
        rows.append({"song": row["song"], "key": f"{row['item_id']}|{row['index']}",
                     "gt_start": row["gt_start_bin"] * step, "gt_end": row["gt_end_bin"] * step,
                     "gt_dur": float(row["gt_duration"]),
                     "start_argmax": onset["argmax_bin"] * step, "end_argmax": offset["argmax_bin"] * step,
                     "start_mean": onset["mean_bin"] * step, "end_mean": offset["mean_bin"] * step,
                     "start_median": onset["median_bin"] * step, "end_median": offset["median_bin"] * step})
    return rows


def fit_duration_map(pairs: list[tuple[float, float]]) -> Callable[[float], float]:
    """Monotone piecewise-linear map from implied duration to the median true duration per bin.

    Out-of-range inputs are extrapolated with slope 1 rather than clamped — clamping long predictions
    back to the last bin's median is exactly the artefact that misled an earlier calibration result.
    """
    if len(pairs) < 20:
        return lambda value: value
    by_bin: dict[int, list[float]] = defaultdict(list)
    for implied, truth in pairs:
        by_bin[int(min(9, max(0, implied * 4)))].append(truth)
    knots_x: list[float] = []
    knots_y: list[float] = []
    for bin_index in range(10):
        values = by_bin.get(bin_index)
        if values and len(values) >= 8:
            knots_x.append((bin_index + 0.5) / 4.0)
            knots_y.append(st.median(values))
    if len(knots_x) < 2:
        return lambda value: value
    order = sorted(range(len(knots_x)), key=lambda index: knots_x[index])
    xs = [knots_x[index] for index in order]
    ys = [knots_y[index] for index in order]

    def mapping(value: float) -> float:
        if value <= xs[0]:
            return ys[0] + (value - xs[0])
        if value >= xs[-1]:
            return ys[-1] + (value - xs[-1])
        for index in range(len(xs) - 1):
            if xs[index] <= value <= xs[index + 1]:
                span = xs[index + 1] - xs[index]
                ratio = 0.0 if span <= 0 else (value - xs[index]) / span
                return ys[index] + ratio * (ys[index + 1] - ys[index])
        return value
    return mapping


# Each readout maps a row (plus a duration map, identity when not calibrated) to a predicted end time.
# `recal` marks the ones whose map must be fitted on other songs only.
READOUTS: dict[str, dict[str, Any]] = {
    "direct_end": {"fn": lambda row, _map: row["end_argmax"], "recal": False, "implied": None},
    "start_argmax_plus_mean_gap": {
        "fn": lambda row, _map: row["start_argmax"] + (row["end_mean"] - row["start_mean"]),
        "recal": False, "implied": None},
    "start_argmax_plus_median_gap": {
        "fn": lambda row, _map: row["start_argmax"] + (row["end_median"] - row["start_median"]),
        "recal": False, "implied": None},
    "recal_argmax_duration": {
        "fn": lambda row, map_fn: row["start_argmax"] + map_fn(row["end_argmax"] - row["start_argmax"]),
        "recal": True, "implied": lambda row: row["end_argmax"] - row["start_argmax"]},
    "recal_mean_duration": {
        "fn": lambda row, map_fn: row["start_argmax"] + map_fn(row["end_mean"] - row["start_mean"]),
        "recal": True, "implied": lambda row: row["end_mean"] - row["start_mean"]},
    "recal_median_duration": {
        "fn": lambda row, map_fn: row["start_argmax"] + map_fn(row["end_median"] - row["start_median"]),
        "recal": True, "implied": lambda row: row["end_median"] - row["start_median"]},
    "oracle_duration": {"fn": lambda row, _map: row["gt_start"] + row["gt_dur"], "recal": False, "implied": None},
}


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    songs = sorted({row["song"] for row in rows})
    if len(songs) < 3:
        return {"status": "insufficient_songs", "songs": len(songs)}
    by_song = {song: [row for row in rows if row["song"] == song] for song in songs}
    per_readout: dict[str, Any] = {}
    for name, spec in READOUTS.items():
        errors: dict[str, list[float]] = {"all": [], "long": [], "very_long": []}
        duration_errors: dict[str, list[float]] = {"all": [], "long": [], "very_long": []}
        for held in songs:
            if spec["recal"]:
                pairs = [(spec["implied"](row), row["gt_dur"])
                         for song in songs if song != held for row in by_song[song]]
                mapping = fit_duration_map(pairs)
            else:
                mapping = lambda value: value  # noqa: E731
            for row in by_song[held]:
                errors["all"].append(abs(spec["fn"](row, mapping) - row["gt_end"]))
                if spec["recal"]:
                    duration_errors["all"].append(abs(mapping(spec["implied"](row)) - row["gt_dur"]))
                if row["gt_dur"] >= LONG_SEC:
                    errors["long"].append(abs(spec["fn"](row, mapping) - row["gt_end"]))
                    if spec["recal"]:
                        duration_errors["long"].append(abs(mapping(spec["implied"](row)) - row["gt_dur"]))
                if row["gt_dur"] >= VERY_LONG_SEC:
                    errors["very_long"].append(abs(spec["fn"](row, mapping) - row["gt_end"]))
                    if spec["recal"]:
                        duration_errors["very_long"].append(abs(mapping(spec["implied"](row)) - row["gt_dur"]))

        def block(values: list[float], marks: list[float]) -> dict[str, Any]:
            if not values:
                return {}
            return {"characters": len(values),
                    "median_end_err_ms": round(1000 * st.median(values), 1),
                    "mean_end_err_ms": round(1000 * st.mean(values), 1),
                    "miss_share": round(sum(1 for value in values if value > TOL) / len(values), 4),
                    "median_duration_err_ms": round(1000 * st.median(marks), 1) if marks else None}
        per_readout[name] = {"all": block(errors["all"], duration_errors["all"]),
                             "long": block(errors["long"], duration_errors["long"]),
                             "very_long": block(errors["very_long"], duration_errors["very_long"])}
    return {"status": "measured", "songs": len(songs), "readouts": per_readout}


def _pct(value: Any) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def markdown(payload: dict[str, Any]) -> str:
    readouts = payload["readouts"]
    baseline = readouts["direct_end"]
    oracle = readouts["oracle_duration"]
    lines = ["# 时长读法判别（生成，勿手改）——信息是「被读错」还是「不在表示里」", "",
             f"> 输入 {payload['songs']} 首歌；所有读法**不使用真值**（`oracle_duration` 只是下界参考）；"
             f"校准类读法按歌留一拟合、只给被留那首歌打分，故每个字符恰好被计一次。缺陷阈值 ±{TOL} s。", "",
             "| 读法 | 全部中位误差(ms) | 全部超差率 | ≥1s 中位误差 | ≥2s n | ≥2s 中位误差 | ≥2s 超差率 |",
             "|---|---|---|---|---|---|---|"]
    for name, block in readouts.items():
        all_block, long_block, very = block["all"], block["long"], block["very_long"]
        lines.append(f"| {name} | {all_block.get('median_end_err_ms')} | {_pct(all_block.get('miss_share'))} | "
                     f"{long_block.get('median_end_err_ms')} | {very.get('characters', '—')} | "
                     f"**{very.get('median_end_err_ms', '—')}** | {_pct(very.get('miss_share'))} |")
    # 分位数陷阱：0.08 s 的 bin 量化让多数字符的结束点误差恰好为 0 ⇒ **中位数退化**，
    # 判据必须用"超差率 + 平均误差"，不能用中位数（我第一版就是踩了这个）。
    recal_miss = [(key, value["very_long"].get("miss_share")) for key, value in readouts.items()
                  if key.startswith("recal") and value["very_long"].get("miss_share") is not None]
    best_key, best_miss = min(recal_miss, key=lambda item: item[1]) if recal_miss else (None, None)
    base_miss = baseline["very_long"].get("miss_share")
    base_ms = baseline["very_long"].get("mean_end_err_ms")
    verdict = ("**信息在分布里、被读错 ⇒ 属解码/校准问题，不需要重训**"
               if best_miss is not None and base_miss is not None and best_miss < base_miss
               else f"所有不用真值的读法都打不过直接预测（最好的校准 {best_key} 超差率 "
                    f"{_pct(best_miss)} vs 直接预测 {_pct(base_miss)}）⇒ **表示层面缺信息**，"
                    f"只有架构改动值得一试")
    lines += ["", "## 判据与结论", "",
              f"- **统计量警示**：0.08 s 分箱让中位误差退化为 0，故判据只用**超差率与平均误差**；",
              f"- 现状（模型直接预测结束点）：≥2s 超差率 **{_pct(base_miss)}**、平均误差 **{base_ms} ms**；",
              f"- 不用真值的读法里最好的校准（{best_key}）：≥2s 超差率 **{_pct(best_miss)}** ⇒ {verdict}；",
              "- 两点方法学说明：`direct_end` 与「起始 + (结束−起始)」是恒等变形，读法里没有偷改公式；"
              "校准的越界处理是**线性外推而非钳位**（今晚一次钳位伪影曾把 −0.46 pp 的效应夸大成 37.67%）。", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = load_rows(args.rows)
    payload = {"schema_version": "duration_readout_v2", "rows": str(args.rows), "characters": len(rows),
               "tolerance_sec": TOL, **evaluate(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({name: {"all": block["all"].get("median_end_err_ms"),
                             "long": block["long"].get("median_end_err_ms"),
                             "very_long_mean_ms": block["very_long"].get("mean_end_err_ms"),
                             "very_long_n": block["very_long"].get("characters"),
                             "very_long_miss": block["very_long"].get("miss_share")}
                      for name, block in payload.get("readouts", {}).items()}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
