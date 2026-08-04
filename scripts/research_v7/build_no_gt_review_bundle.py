#!/usr/bin/env python3
"""Create an immutable, abstention-only review queue from no-GT evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    collection = json.loads(Path(args.collection).read_text(encoding="utf-8")); root = Path(collection["out_root"]); cases = []
    for record in collection["records"]:
        evidence = json.loads((root / record["source"]).read_text(encoding="utf-8")); attempt = evidence["attempt"]; request = attempt["request"]
        if Path(request["text_source"]).suffix == ".jsonl":
            continue
        rows = attempt.get("decoder_outputs", {}).get("official", {}).get("rows", [])
        cases.append({"request_id": request["request_id"], "item_id": request["item_id"], "mutation_type": request["mutation_type"],
                      "audio_path": request["audio_source"], "audio_range_sec": [request["audio_start_sec"], request["audio_end_sec"]],
                      "lyrics_path": request["text_source"], "text_units": request["text_units"], "evidence_source": record["source"],
                      "evidence_sha256": record["sha256"], "status": attempt["status"], "row_count": len(rows),
                      "review": {"reviewer": None, "labels": [], "severe_error_minutes": None, "longest_error_sec": None,
                                 "blind_comparison_group": request["item_id"], "notes": None, "accuracy_claim": "prohibited_without_gt"}})
    output = {"schema": "v7/no_gt_review_bundle_v1", "collection": str(args.collection), "case_count": len(cases),
              "rules": ["Do not enter accuracy/MAE without external GT.", "Blind-review mutations within each comparison group.", "Keep multi-solution and unresolved labels distinct from strict no-match."], "cases": cases}
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "cases": len(cases), "out": str(target)}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
