#!/usr/bin/env python3
"""Split a no-GT review bundle into blinded packets and an experimenter-only key."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


LABELS = ["VALID_STABLE", "VALID_BUT_UNCERTAIN", "TAIL_COLLAPSE", "HEAD_COLLAPSE", "WRONG_REPEATED_SECTION",
          "MULTI_SECTION_SPLIT", "GLOBAL_SHIFT", "LOCAL_SHIFT", "ZERO_DURATION_CLUSTER", "UNRESOLVED"]


def blind_id(seed: str, request_id: str) -> str:
    return "R-" + hashlib.sha256(f"{seed}|{request_id}".encode()).hexdigest()[:16]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True); parser.add_argument("--packets-out", required=True); parser.add_argument("--key-out", required=True)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args(argv); bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8")); packets=[]; key=[]
    for case in bundle["cases"]:
        token = blind_id(args.seed, case["request_id"])
        packets.append({"blind_id": token, "comparison_group": case["review"]["blind_comparison_group"],
                        "audio_path": case["audio_path"], "audio_range_sec": case["audio_range_sec"], "lyrics_path": case["lyrics_path"],
                        "text_units": case["text_units"], "row_count": case["row_count"],
                        "review": {"reviewer": None, "labels": [], "allowed_labels": LABELS, "severe_error_minutes": None,
                                   "longest_error_sec": None, "unresolved": None, "notes": None}})
        key.append({"blind_id": token, "request_id": case["request_id"], "item_id": case["item_id"], "mutation_type": case["mutation_type"],
                    "evidence_source": case["evidence_source"], "evidence_sha256": case["evidence_sha256"]})
    packets.sort(key=lambda row: row["blind_id"]); key.sort(key=lambda row: row["blind_id"])
    Path(args.packets_out).parent.mkdir(parents=True, exist_ok=True); Path(args.key_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.packets_out).write_text(json.dumps({"schema":"research_v7/blinded_review_packets_v1","case_count":len(packets),"packets":packets},ensure_ascii=False,indent=1)+"\n",encoding="utf-8")
    Path(args.key_out).write_text(json.dumps({"schema":"research_v7/blinded_review_key_v1","case_count":len(key),"key":key},ensure_ascii=False,indent=1)+"\n",encoding="utf-8")
    print(json.dumps({"ok":True,"packets":len(packets),"packets_out":args.packets_out,"key_out":args.key_out},ensure_ascii=False));return 0


if __name__ == "__main__": raise SystemExit(main())
