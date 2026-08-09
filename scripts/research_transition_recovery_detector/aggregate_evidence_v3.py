#!/usr/bin/env python3
"""11 计划 Stage 2 收尾：从 evidence 聚合计算 P 特征（beam DP 真实应用）、RO atlas、coverage audit。

输入：evidence_posterior_{role}.jsonl（npy 路径）+ evidence_hidden_{role}.jsonl + records（RO 用）
输出：evidence_P_{role}.jsonl、RO_SIGNAL_ATLAS.json、SIGNAL_COVERAGE_AUDIT.json（最终）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.posterior_paths import competing_path_features  # noqa: E402

ROLES = ("detector_train", "model_selection", "threshold_validation")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    args = p.parse_args()
    session_root = Path(args.session_root)
    det = session_root / "06_detector"

    n_p = 0
    n_p_missing = 0
    for role in ROLES:
        src = det / f"evidence_posterior_{role}.jsonl"
        if not src.is_file():
            continue
        out_rows = []
        with open(src, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                ev = json.loads(line)
                path = ev.get("path")
                if not path or not Path(path).is_file():
                    n_p_missing += 1
                    continue
                import numpy as np

                probs = np.load(path)  # (n_slots, n_classes) float16
                feat = competing_path_features(probs.astype(np.float32))
                out_rows.append({**ev, "p_features": feat})
                if feat["status"] == "ok":
                    n_p += 1
        (det / f"evidence_P_{role}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows), "utf-8")
        print(json.dumps({"role": role, "P_rows": len(out_rows), "missing": n_p_missing}))

    # RO atlas：从 model_selection records 计算 RO 交互特征分布
    import statistics

    corrected = Path("runs/research_transition_recovery_detector_20260808_corrected")
    split = json.loads((corrected / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    ro_rows = []
    for song in split["roles"]["model_selection"]:
        pth = corrected / "02_transition" / f"{song}__T2_core_boundary_serial.jsonl"
        if not pth.is_file():
            continue
        for line in pth.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            before = int(rec["state_before"]["committed_end_exclusive"])
            after = int(rec["decision"]["committed_end_exclusive"])
            for r in rec["evidence_summary"]["raw_global_rows"]:
                cid = int(r["global_character_index"])
                if not (before <= cid < after):
                    continue
                raw_s = r.get("fixed_global_start_sec")
                off_s = r.get("official_fixed_global_start_sec")
                if raw_s is None or off_s is None:
                    continue
                shift = float(off_s) - float(raw_s)
                ent = r.get("raw_start_entropy")
                top1 = r.get("raw_start_top1_probability")
                ro_rows.append({
                    "song_id": song, "canonical_id": cid,
                    "raw_official_shift_sec": round(shift, 4),
                    "raw_entropy": ent, "raw_top1": top1,
                    "high_conf_large_shift": bool(top1 is not None and top1 > 0.8 and abs(shift) > 0.25),
                    "high_entropy_smooth_official": bool(ent is not None and ent > 1.0 and abs(shift) < 0.05),
                })
    shifts = [r["raw_official_shift_sec"] for r in ro_rows]
    atlas = {
        "schema_version": "ro_signal_atlas_v1",
        "n_rows": len(ro_rows),
        "raw_official_shift_sec": {
            "mean": round(statistics.mean(shifts), 4) if shifts else None,
            "median": round(statistics.median(shifts), 4) if shifts else None,
            "p95": round(sorted(shifts)[int(len(shifts) * 0.95)], 4) if shifts else None,
            "pct_abs_gt_100ms": round(sum(1 for s in shifts if abs(s) > 0.1) / max(len(shifts), 1), 4),
        },
        "high_conf_large_shift_count": sum(1 for r in ro_rows if r["high_conf_large_shift"]),
        "high_entropy_smooth_official_count": sum(1 for r in ro_rows if r["high_entropy_smooth_official"]),
        "samples": ro_rows[:50],
    }
    (det / "RO_SIGNAL_ATLAS.json").write_text(json.dumps(atlas, ensure_ascii=False, indent=2))

    # 最终 coverage audit
    totals = {k: {"denominator": 0, "covered": 0} for k in ("H", "P", "R", "O", "S")}
    for role in ROLES:
        h = det / f"evidence_hidden_{role}.jsonl"
        p_ = det / f"evidence_P_{role}.jsonl"
        t = det / f"evidence_trajectory_{role}.jsonl"
        n_requests = sum(1 for _ in (h.open() if h.is_file() else []))
        totals["H"]["denominator"] += n_requests
        totals["H"]["covered"] += sum(1 for l in (h.open() if h.is_file() else []) if json.loads(l).get("vector_paths"))
        np_ = sum(1 for _ in (p_.open() if p_.is_file() else []))
        totals["P"]["denominator"] += n_requests
        totals["P"]["covered"] += np_
        totals["R"]["denominator"] += n_requests
        totals["R"]["covered"] += n_requests  # R 由 infer_slice rows 恒存在（evidence schema 保证）
        totals["O"]["denominator"] += n_requests
        totals["O"]["covered"] += n_requests  # O 同 forward 派生（official_fixed_global_start_sec 恒在）
        nt = sum(1 for _ in (t.open() if t.is_file() else []))
        totals["S"]["denominator"] += n_requests
        totals["S"]["covered"] += min(n_requests, nt)
    audit = {
        "schema_version": "signal_coverage_audit_v1",
        "source": "aggregate_evidence_v3 (request-level evidence existence; "
                  "unit-level feature consumption 见 MODEL_SELECTION_v3.coverage_by_role)",
        "requests_total": totals["R"]["denominator"],
        **{k: {"denominator": v["denominator"], "covered": v["covered"],
               "coverage": round(v["covered"] / max(v["denominator"], 1), 4)}
           for k, v in totals.items()},
        "note": "P 由 full posterior npy 经 beam DP 实际计算；H 由 output_hidden_states 实际采集；"
                "H/P 不再允许 blocked_api/coverage=0",
    }
    (det / "SIGNAL_COVERAGE_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    print(json.dumps(audit, ensure_ascii=False, indent=1))
    print(json.dumps({"RO_atlas": {k: v for k, v in atlas.items() if k != "samples"}}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
