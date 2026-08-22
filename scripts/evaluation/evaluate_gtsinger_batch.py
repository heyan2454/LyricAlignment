#!/usr/bin/env python3
"""Evaluate all GTSinger smoke subdirs in a batch root.

Each subdir may contain a `gt_path.txt` with the GTSinger JSON path. If not,
pass `--gt-map` as JSONL lines: `{"out_dir": "...", "gt_json": "..."}`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--gt-map", type=Path)
    parser.add_argument("--model", default="r2")
    parser.add_argument("--mode", default="windowed")
    parser.add_argument("--audio", default="vocal")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    mapping: dict[str, str] = {}
    if args.gt_map and args.gt_map.is_file():
        for line in args.gt_map.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            mapping[str(row["out_dir"])] = str(row["gt_json"])
    for sub in sorted(args.batch_root.iterdir()):
        if not sub.is_dir():
            continue
        gt_path_file = sub / "gt_path.txt"
        if gt_path_file.is_file():
            mapping[sub.name] = gt_path_file.read_text(encoding="utf-8").strip()
    if not mapping:
        raise SystemExit("no mapping found; use --gt-map or per-subdir gt_path.txt")

    results = []
    for sub in sorted(args.batch_root.iterdir()):
        if not sub.is_dir() or sub.name not in mapping:
            continue
        alignment = sub / "alignments" / args.model / args.audio / args.mode / "alignment.json"
        if not alignment.is_file():
            continue
        gt_json = Path(mapping[sub.name])
        import statistics

        def _load_json(p: Path) -> dict:
            return json.loads(p.read_text(encoding="utf-8"))

        def _clean_gt_rows(data: list[dict]) -> list[dict]:
            return [
                row for row in data
                if isinstance(row, dict) and str(row.get("word", "")).upper().replace("<AP/>", "<AP>") != "<AP>"
            ]

        gt_data = _load_json(gt_json)
        gt_rows = _clean_gt_rows(gt_data)
        alignment_data = _load_json(alignment)
        pred_rows = alignment_data.get("characters", [])
        if len(pred_rows) != len(gt_rows):
            results.append({"subdir": sub.name, "status": "count_mismatch", "pred": len(pred_rows), "gt": len(gt_rows)})
            continue
        start_errs = []
        end_errs = []
        both_errs = []
        for pred, gt in zip(pred_rows, gt_rows):
            ps = float(pred.get("selected_start_sec", pred.get("start_sec")))
            pe = float(pred.get("selected_end_sec", pred.get("end_sec")))
            gs = float(gt["start_time"])
            ge = float(gt["end_time"])
            se = abs(ps - gs)
            ee = abs(pe - ge)
            start_errs.append(se)
            end_errs.append(ee)
            both_errs.append(max(se, ee))
        def hit(errs, thr):
            return sum(1 for e in errs if e <= thr) / len(errs) if errs else 0.0
        results.append({
            "subdir": sub.name,
            "status": "ok",
            "unit_count": len(pred_rows),
            "start_median_ms": round(statistics.median(start_errs) * 1000, 1) if start_errs else None,
            "end_median_ms": round(statistics.median(end_errs) * 1000, 1) if end_errs else None,
            "both_100ms": round(hit(both_errs, 0.100), 4),
            "both_200ms": round(hit(both_errs, 0.200), 4),
            "both_500ms": round(hit(both_errs, 0.500), 4),
        })
    payload = {
        "schema_version": "gtsinger_batch_evaluation_v1",
        "batch_root": str(args.batch_root),
        "model": args.model,
        "audio": args.audio,
        "mode": args.mode,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
