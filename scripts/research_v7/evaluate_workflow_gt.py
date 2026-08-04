#!/usr/bin/env python3
"""Score P0/P1/P2/D/S attempts against GT after production-like execution."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--collection", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args(argv); collection = json.loads(Path(args.collection).read_text(encoding="utf-8")); root = Path(collection["out_root"]); attempts = []
    for record in collection["records"]:
        evidence = json.loads((root / record["source"]).read_text(encoding="utf-8")); attempt = evidence["attempt"]; request = attempt["request"]
        if attempt["status"] != "ok":
            attempts.append({"request_id": request["request_id"], "item_id": request["item_id"], "workflow_mode": request["workflow_mode"], "scored": False, "reason": attempt["status"]}); continue
        gt = [json.loads(line) for line in Path(request["text_source"]).read_text(encoding="utf-8").splitlines() if line]
        source_start = int(request.get("mutation_parameters", {}).get("source_text_start_index") or 0); errors = []; matched = 0
        for row in attempt["decoder_outputs"]["official"]["rows"]:
            local = int(row["global_character_index"])
            # Sparse rows retain global text positions, all other workflow chunks are local.
            index = local if request["workflow_mode"] == "strict_serial_sparse_slots" or request.get("input_variant") == "strict_serial_committed_prefix_all_slots" else source_start + local
            if index < len(gt) and index < len(request["text_units"]) + source_start:
                errors.extend((abs(float(row["fixed_global_start_sec"]) - float(gt[index]["start_sec"])), abs(float(row["fixed_global_end_sec"]) - float(gt[index]["end_sec"])))); matched += 1
        attempts.append({"request_id": request["request_id"], "item_id": request["item_id"], "workflow_mode": request["workflow_mode"], "parent_request_id": request["parent_request_id"], "cursor_offset_units": request.get("mutation_parameters", {}).get("cursor_offset_units"), "provisional_policy": request.get("mutation_parameters", {}).get("provisional_policy"), "scored": bool(errors), "matched_unit_count": matched, "boundary_mae_sec": sum(errors) / len(errors) if errors else None, "cursor_prev_end": attempt.get("cursor_prev_end"), "cursor_after": attempt.get("cursor_after")})
    p0 = {row["item_id"]: row for row in attempts if row["workflow_mode"] == "production_full_once" and row["scored"]}; grouped = defaultdict(list)
    for row in attempts:
        if row["scored"] and row["item_id"] in p0:
            row["delta_from_p0_mae_sec"] = row["boundary_mae_sec"] - p0[row["item_id"]]["boundary_mae_sec"]
        grouped[row["workflow_mode"]].append(row)
    summary = {}
    for mode, rows in grouped.items():
        scores = [row["boundary_mae_sec"] for row in rows if row["scored"]]; deltas = [row["delta_from_p0_mae_sec"] for row in rows if "delta_from_p0_mae_sec" in row]
        summary[mode] = {"total_count": len(rows), "scored_count": len(scores), "mean_boundary_mae_sec": sum(scores)/len(scores) if scores else None, "mean_delta_from_p0_mae_sec": sum(deltas)/len(deltas) if deltas else None}
    cursor_rows = defaultdict(list)
    for row in attempts:
        if row["workflow_mode"] == "strict_serial_same_audio_cursor_injection":
            cursor_rows[str(row["cursor_offset_units"])].append(row)
    cursor_summary = {}
    for offset, rows in cursor_rows.items():
        scores = [row["boundary_mae_sec"] for row in rows if row["scored"]]
        deltas = [row["delta_from_p0_mae_sec"] for row in rows if "delta_from_p0_mae_sec" in row]
        cursor_summary[offset] = {"total_count": len(rows), "scored_count": len(scores), "mean_boundary_mae_sec": sum(scores)/len(scores) if scores else None, "mean_delta_from_p0_mae_sec": sum(deltas)/len(deltas) if deltas else None}
    provisional_rows = defaultdict(list)
    for row in attempts:
        if row["workflow_mode"] == "strict_serial_provisional_slots":
            provisional_rows[str(row["provisional_policy"])].append(row)
    provisional_summary = {}
    for policy, rows in provisional_rows.items():
        scores = [row["boundary_mae_sec"] for row in rows if row["scored"]]
        deltas = [row["delta_from_p0_mae_sec"] for row in rows if "delta_from_p0_mae_sec" in row]
        provisional_summary[policy] = {"total_count": len(rows), "scored_count": len(scores), "mean_boundary_mae_sec": sum(scores)/len(scores) if scores else None, "mean_delta_from_p0_mae_sec": sum(deltas)/len(deltas) if deltas else None}
    Path(args.out).write_text(json.dumps({"schema": "v7/workflow_gt_v1", "attempts": attempts, "summary": summary, "cursor_injection_summary": cursor_summary, "provisional_summary": provisional_summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "attempts": len(attempts), "out": args.out}, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
