#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the identity/comparability gate over the real-song batches (which past claims survive?).

    PYTHONPATH=src python scripts/evaluation/audit_evidence_identity.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import evidence_identity_audit as A

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_evidence_identity_audit"
BATCHES = {
    "ktv_B4": RUNS / "20260814_ktv_B4",
    "ktv_current_silence": RUNS / "20260814_ktv_current_silence",
    "slot_vs_b4_align": RUNS / "20260815_slot_vs_b4/align",
    "slot_v2_textmode3": RUNS / "20260815_slot_v2/align_textmode3",
}
PAIRS = [("ktv_B4__vs__current_silence", "ktv_B4", "ktv_current_silence"),
         ("current_silence__vs__slot_align", "ktv_current_silence", "slot_vs_b4_align"),
         ("ktv_B4__vs__slot_align", "ktv_B4", "slot_vs_b4_align"),
         ("current_silence__vs__textmode3", "ktv_current_silence", "slot_v2_textmode3")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    coll = {name: A.collect(path) for name, path in BATCHES.items()}
    audit: dict[str, object] = {"schema": "evidence_identity_audit_v1",
                                "batches": {k: {"root": str(BATCHES[k]), "songs_with_artifacts": len(v)}
                                            for k, v in coll.items()}}
    audit["identity_hygiene"] = A.audit_identity_hygiene(coll)
    audit["pairs"] = []
    for name, a, b in PAIRS:
        if not coll[a] or not coll[b]:
            audit["pairs"].append({"pair": name, "verdict": "missing_batch"})
            continue
        audit["pairs"].append(A.audit_pair(name, coll[a], coll[b]))
    (args.out_dir / "IDENTITY_AUDIT.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("batches:", json.dumps(audit["batches"], ensure_ascii=False))
    print("\nidentity hygiene:")
    for k, v in audit["identity_hygiene"].items():
        print(f"  {k:22s} {json.dumps(v, ensure_ascii=False)}")
    print("\npair verdicts:")
    for p in audit["pairs"]:
        print(f"  {p['pair']:34s} -> {p['verdict'].upper():15s} songs={p.get('songs')} "
              f"same_plan={p.get('same_window_plan_share')} same_sha={p.get('same_audio_sha_share')} "
              f"identical_out={p.get('outputs_identical_share')} len_mismatch={p.get('unit_count_mismatch_songs')} "
              f"text_mismatch={p.get('text_mismatch_songs')}")
        print(f"      reason: {p.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
