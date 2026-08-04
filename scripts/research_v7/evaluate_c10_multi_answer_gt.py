#!/usr/bin/env python3
"""Score C10 repeated-section evidence against all declared legal GT locations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def mae(rows: list[dict], gt: list[dict], mapping: list[int]) -> float | None:
    errors: list[float] = []
    for row in rows:
        index = int(row["global_character_index"])
        if index >= len(mapping) or mapping[index] >= len(gt):
            continue
        truth = gt[mapping[index]]
        errors.extend((abs(float(row["fixed_global_start_sec"]) - float(truth["start_sec"])),
                       abs(float(row["fixed_global_end_sec"]) - float(truth["end_sec"]))))
    return sum(errors) / len(errors) if errors else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    collection = json.loads(Path(args.collection).read_text(encoding="utf-8")); root = Path(collection["out_root"])
    results: list[dict] = []
    for record in collection["records"]:
        payload = json.loads((root / record["source"]).read_text(encoding="utf-8"))
        attempt, request = payload["attempt"], payload["attempt"]["request"]
        params = request.get("mutation_parameters", {})
        if attempt.get("status") != "ok" or not params.get("c10_case"):
            continue
        starts, count = params.get("repeat_gt_starts"), int(params.get("repeat_unit_count") or 0)
        if not isinstance(starts, list) or len(starts) != 2 or count < 1:
            raise ValueError(f"invalid C10 provenance for {request['request_id']}")
        gt = [json.loads(line) for line in Path(request["text_source"]).read_text(encoding="utf-8").splitlines() if line]
        rows = attempt["decoder_outputs"]["official"]["rows"]
        if params["c10_case"] == "single_ambiguous_repeat":
            alternatives = [[start + i for i in range(count)] for start in starts]
            values = [mae(rows, gt, mapping) for mapping in alternatives]
            valid = [(i, value) for i, value in enumerate(values) if value is not None]
            chosen, score = min(valid, key=lambda pair: pair[1]) if valid else (None, None)
            results.append({"request_id": request["request_id"], "item_id": request["item_id"], "c10_case": params["c10_case"],
                            "legal_location_mae_sec": values, "best_legal_location": chosen, "best_legal_mae_sec": score,
                            "matched_unit_count": len(rows)})
        elif params["c10_case"] == "double_repeat_sequence":
            mapping = [starts[0] + i for i in range(count)] + [starts[1] + i for i in range(count)]
            results.append({"request_id": request["request_id"], "item_id": request["item_id"], "c10_case": params["c10_case"],
                            "ordered_two_section_mae_sec": mae(rows, gt, mapping), "matched_unit_count": len(rows)})
    by_case = {}
    for case in sorted({row["c10_case"] for row in results}):
        key = "best_legal_mae_sec" if case == "single_ambiguous_repeat" else "ordered_two_section_mae_sec"
        values = [float(row[key]) for row in results if row["c10_case"] == case and row.get(key) is not None]
        by_case[case] = {"count": len(values), "mean_mae_sec": sum(values) / len(values) if values else None,
                         "min_mae_sec": min(values) if values else None, "max_mae_sec": max(values) if values else None}
    output = {"schema": "research_v7/c10_multi_answer_gt_v1", "results": results, "by_case": by_case,
              "note": "Single-repeat score is minimum MAE over declared legal GT occurrences; double-repeat score preserves chronological occurrence order."}
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "results": len(results), "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
