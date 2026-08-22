#!/usr/bin/env python3
"""Evaluate a GTSinger alignment against the JSON word-level ground truth.

GTSinger JSON is word-level; for Chinese mini each word is usually one Chinese
character. `<AP>` aspiration markers are removed from ground truth before
comparison because the lyric text generator drops them.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_gt_rows(data: list[dict]) -> list[dict]:
    return [
        row for row in data
        if isinstance(row, dict) and str(row.get("word", "")).upper().replace("<AP/>", "<AP>") != "<AP>"
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--gt-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    alignment = load_json(args.alignment)
    gt_data = load_json(args.gt_json)
    if not isinstance(gt_data, list):
        raise SystemExit("gt-json must contain a JSON array")
    gt_rows = clean_gt_rows(gt_data)
    pred_rows = alignment.get("characters", [])
    if len(pred_rows) != len(gt_rows):
        raise SystemExit(
            f"count mismatch: pred={len(pred_rows)} gt={len(gt_rows)}; "
            "check lyric text/AP filtering or use a matching alignment"
        )

    rows = []
    for i, (pred, gt) in enumerate(zip(pred_rows, gt_rows)):
        p_start = float(pred.get("selected_start_sec", pred.get("start_sec")))
        p_end = float(pred.get("selected_end_sec", pred.get("end_sec")))
        g_start = float(gt["start_time"])
        g_end = float(gt["end_time"])
        start_err = abs(p_start - g_start)
        end_err = abs(p_end - g_end)
        rows.append({
            "index": i,
            "text": str(gt.get("word", "")),
            "pred_start_sec": p_start,
            "pred_end_sec": p_end,
            "gt_start_sec": g_start,
            "gt_end_sec": g_end,
            "start_abs_error_sec": start_err,
            "end_abs_error_sec": end_err,
            "both_abs_error_sec": max(start_err, end_err),
        })

    start_errs = [r["start_abs_error_sec"] for r in rows]
    end_errs = [r["end_abs_error_sec"] for r in rows]
    both_errs = [r["both_abs_error_sec"] for r in rows]

    def hit_rate(errs, threshold):
        return sum(1 for e in errs if e <= threshold) / len(errs) if errs else 0.0

    summary = {
        "schema_version": "gtsinger_alignment_evaluation_v1",
        "alignment": str(args.alignment),
        "gt_json": str(args.gt_json),
        "unit_count": len(rows),
        "start_error_sec": {
            "median": statistics.median(start_errs) if start_errs else None,
            "p90": sorted(start_errs)[min(len(start_errs)-1, int(round(0.90*len(start_errs))))] if start_errs else None,
            "mean": statistics.mean(start_errs) if start_errs else None,
            "max": max(start_errs) if start_errs else None,
        },
        "end_error_sec": {
            "median": statistics.median(end_errs) if end_errs else None,
            "p90": sorted(end_errs)[min(len(end_errs)-1, int(round(0.90*len(end_errs))))] if end_errs else None,
            "mean": statistics.mean(end_errs) if end_errs else None,
            "max": max(end_errs) if end_errs else None,
        },
        "both_error_sec": {
            "median": statistics.median(both_errs) if both_errs else None,
            "p90": sorted(both_errs)[min(len(both_errs)-1, int(round(0.90*len(both_errs))))] if both_errs else None,
        },
        "hit_rates": {
            "start_100ms": hit_rate(start_errs, 0.100),
            "start_200ms": hit_rate(start_errs, 0.200),
            "start_500ms": hit_rate(start_errs, 0.500),
            "end_100ms": hit_rate(end_errs, 0.100),
            "end_200ms": hit_rate(end_errs, 0.200),
            "end_500ms": hit_rate(end_errs, 0.500),
            "both_100ms": hit_rate(both_errs, 0.100),
            "both_200ms": hit_rate(both_errs, 0.200),
            "both_500ms": hit_rate(both_errs, 0.500),
        },
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
