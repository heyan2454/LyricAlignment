#!/usr/bin/env python3
"""Global entropy threshold vs one calibrated per predicted-duration bin — which flags defects better?

Tonight's confidence×duration cross-tab says long characters sit in the low-confidence quartile almost
by definition (80% of ≥2 s characters are in Q4 versus 14% of <0.5 s).  A *global* entropy threshold
therefore spends its whole review budget on long characters, whether or not they are wrong, and may
under-flag a confidently-wrong short character.  The fix must be observable at inference, so the
conditioning variable is the model's **own predicted duration**, not ground truth.

Evaluation is leave-one-song-out: thresholds are fitted on the other songs only, then applied to the
held-out song.  Reported at fixed review budgets: defect capture share and residual defect rate, with
both estimators on the identical population so the comparison is paired.

    PYTHONPATH=src python scripts/evaluation/gating_calibration_test.py \
        --dump results/by_run/20260914_mech_validation_uniform/per_character.jsonl \
        --out results/by_run/20260914_gating_calibration/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
BUDGETS = (0.05, 0.10, 0.20)
PRED_EDGES = (0.0, 0.25, 0.5, 1.0, 2.0, 99.0)
MIN_BIN_ROWS = 30


def characters(path: Path) -> list[dict[str, Any]]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
    out: list[dict[str, Any]] = []
    for (item, index), kinds in per.items():
        if len(kinds) != 2:
            continue
        onset, offset = kinds["onset"], kinds["offset"]
        parts = str(item).split("#")
        predicted_duration = float(offset["pred_sec"]) - float(onset["pred_sec"])
        out.append({"key": f"{item}|{index}", "song": "#".join(parts[:2]) if len(parts) >= 2 else str(item),
                    "entropy": (float(onset["entropy_nats"]) + float(offset["entropy_nats"])) / 2.0,
                    "pred_dur": predicted_duration,
                    "gt_dur": float(onset["duration"]),
                    "defect": max(float(onset["abs_err_argmax"]), float(offset["abs_err_argmax"])) > TOL})
    return out


def pred_bin(value: float) -> str:
    for low, high in zip(PRED_EDGES[:-1], PRED_EDGES[1:]):
        if low <= value < high:
            return "2s+" if high >= 99 else f"{low:g}-{high:g}s"
    return "other"


def quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("inf")
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def global_flags(rows: list[dict[str, Any]], *, training: list[dict[str, Any]], budget: float) -> dict[str, bool]:
    cut = quantile([row["entropy"] for row in training], 1.0 - budget)
    return {row["key"]: row["entropy"] >= cut for row in rows}


def conditional_flags(rows: list[dict[str, Any]], *, training: list[dict[str, Any]], budget: float) -> dict[str, bool]:
    """Per-predicted-duration-bin thresholds; sparse bins fall back to the global cut.

    The conditioning variable is the model's own predicted duration, which exists at inference.
    Ground-truth duration must never be used here or the gate becomes an oracle.
    """
    cut_global = quantile([row["entropy"] for row in training], 1.0 - budget)
    by_bin: dict[str, list[float]] = defaultdict(list)
    for row in training:
        by_bin[pred_bin(row["pred_dur"])].append(row["entropy"])
    cuts = {name: quantile(values, 1.0 - budget) for name, values in by_bin.items()
            if len(values) >= MIN_BIN_ROWS}
    return {row["key"]: row["entropy"] >= cuts.get(pred_bin(row["pred_dur"]), cut_global) for row in rows}


def _summarise(rows: list[dict[str, Any]], flags: dict[str, bool], *, total_defects: int) -> dict[str, Any]:
    flagged = [row for row in rows if flags.get(row["key"], False)]
    captured = sum(1 for row in flagged if row["defect"])
    residual_population = len(rows) - len(flagged)
    return {"flagged": len(flagged),
            "flagged_share": round(len(flagged) / max(1, len(rows)), 4),
            "captured_defects": captured,
            "capture_share": round(captured / max(1, total_defects), 4),
            "residual_defects": total_defects - captured,
            "residual_defect_rate": round((total_defects - captured) / max(1, residual_population), 4)}


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    songs = sorted({row["song"] for row in rows})
    if len(songs) < 3:
        return {"status": "insufficient_songs", "songs": len(songs)}
    by_song = {song: [row for row in rows if row["song"] == song] for song in songs}
    total_defects = sum(1 for row in rows if row["defect"])
    out: dict[str, Any] = {"status": "measured", "songs": len(songs), "characters": len(rows),
                           "defects": total_defects, "defect_rate": round(total_defects / max(1, len(rows)), 4),
                           "min_bin_rows": MIN_BIN_ROWS, "budgets": {}}
    for budget in BUDGETS:
        gflags: dict[str, bool] = {}
        cflags: dict[str, bool] = {}
        bins_used: set[str] = set()
        for held in songs:
            training = [row for row in rows if row["song"] != held]
            test = by_song[held]
            gflags.update(global_flags(test, training=training, budget=budget))
            cflags.update(conditional_flags(test, training=training, budget=budget))
            cut_global = quantile([row["entropy"] for row in training], 1.0 - budget)
            per_bin: dict[str, list[float]] = defaultdict(list)
            for row in training:
                per_bin[pred_bin(row["pred_dur"])].append(row["entropy"])
            for name, values in per_bin.items():
                if len(values) >= MIN_BIN_ROWS and quantile(values, 1.0 - budget) != cut_global:
                    bins_used.add(name)
        summary = {"global": _summarise(rows, gflags, total_defects=total_defects),
                   "duration_conditional": _summarise(rows, cflags, total_defects=total_defects),
                   "conditional_bins_in_use": sorted(bins_used)}
        summary["paired"] = {
            "capture_share_delta_pp": round(100 * (summary["duration_conditional"]["capture_share"]
                                                   - summary["global"]["capture_share"]), 3),
            "conditional_only_defects": sum(1 for row in rows if cflags.get(row["key"])
                                            and not gflags.get(row["key"]) and row["defect"]),
            "global_only_defects": sum(1 for row in rows if gflags.get(row["key"])
                                       and not cflags.get(row["key"]) and row["defect"])}
        out["budgets"][f"{int(budget * 100)}%"] = summary
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = characters(args.dump)
    payload = {"schema_version": "gating_calibration_v1", "dump": str(args.dump),
               "tolerance_sec": TOL, "pred_duration_bins": [f"{a:g}-{b:g}s" for a, b in zip(PRED_EDGES[:-1], PRED_EDGES[1:])],
               **evaluate(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "pred_duration_bins"},
                     indent=2, ensure_ascii=False))
    if args.report:
        lines = ["# 门控阈值：全局 vs 按预测时长分档（生成，勿手改）", ""]
        if payload.get("status") == "measured":
            lines += [f"> 缺陷定义：起或止边界误差 > {TOL} s；留出单位 = 歌（`Singer#Song`）；"
                      f"分箱依据 = **模型自己预测的时长**（推理期可得，真值时长绝不参与）。", ""]
            for budget, block in payload["budgets"].items():
                lines += [f"## 复核预算 {budget}", "",
                          "| 策略 | 标记占比 | 抓到缺陷占比 | 剩余缺陷率 |", "|---|---|---|---|"]
                for label, name in (("global", "全局熵阈值（现行）"), ("duration_conditional", "按预测时长分档")):
                    entry = block[label]
                    lines.append(f"| {name} | {_pct(entry['flagged_share'])} | "
                                 f"{_pct(entry['capture_share'], 1)} | {_pct(entry['residual_defect_rate'])} |")
                paired = block["paired"]
                lines += ["", f"- 抓到缺陷占比差 **{paired['capture_share_delta_pp']:+.2f} pp**；"
                          f"只有分档版抓到的缺陷 {paired['conditional_only_defects']} 个、"
                          f"只有全局版抓到的 {paired['global_only_defects']} 个；"
                          f"实际生效的分箱：{', '.join(block['conditional_bins_in_use']) or '无'}。", ""]
        args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value: Any, digits: int = 2) -> str:
    return "—" if value is None else f"{100 * value:.{digits}f}%"


if __name__ == "__main__":
    main()
