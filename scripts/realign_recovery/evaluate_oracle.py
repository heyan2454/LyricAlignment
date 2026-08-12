#!/usr/bin/env python3
"""E1 oracle REPAIR 离线评估 CLI（纯 CPU，消费已有 GPU evidence）。

用 load_real_gt_with_audit 把 overlay 真实 GT 投影到 manifest canonical 轴后，调
evaluate_oracle_runs 对照 raw 对齐结果，给出 per-mode/per-song/per-region 的
repair rate（catastrophic 阈值内视为 repaired）与 MAE。

不运行模型，只读 REQUESTS.jsonl / evidence_dir / 真实标注；输出 summary JSON 到 --out。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.oracle import evaluate_oracle_runs  # noqa: E402
from lyricalign.research_transition_recovery_detector.real_gt import load_real_gt_with_audit  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--requests", required=True, help="REQUESTS.jsonl（build_oracle_requests 产物）")
    p.add_argument("--evidence-dir", required=True, help="run_behavior_suite 的 evidence 目录（含逐 attempt JSON）")
    p.add_argument("--annotations", required=True, help="m4singer character annotations jsonl")
    p.add_argument("--timeline-manifest", required=True, help="LONG_TIMELINE_MANIFEST.jsonl")
    p.add_argument("--out", required=True, help="summary JSON 输出路径")
    p.add_argument("--catastrophic-sec", default="1,2,5,10", help="灾难阈值秒，逗号分隔")
    p.add_argument("--thresholds-ms", default="100,200,500", help="MAE 精度阈值 ms，逗号分隔")
    args = p.parse_args(argv)

    catastrophic = tuple(float(t) for t in args.catastrophic_sec.split(",") if t.strip())
    thresholds_ms = tuple(float(t) for t in args.thresholds_ms.split(",") if t.strip())

    real_gt, audit = load_real_gt_with_audit(args.annotations, args.timeline_manifest)
    summary = evaluate_oracle_runs(
        args.requests, args.evidence_dir, real_gt, args.timeline_manifest, args.out,
        thresholds_ms=thresholds_ms, catastrophic_sec=catastrophic)
    summary["gt_audit"] = audit

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    per_mode = {}
    for mode, b in sorted(summary.get("per_mode", {}).items()):
        n = b["n_units"]
        rates = {t: (b["n_repaired"][t] / n if n else 0.0) for t in b["n_repaired"]}
        per_mode[mode] = {"n_units": n, "n_repaired": b["n_repaired"], "repair_rate": rates}
    print(json.dumps({
        "ok": True,
        "total_units": summary.get("total_units"),
        "per_mode": per_mode,
        "n_songs_evaluated": len(summary.get("per_song", {})),
        "n_regions_evaluated": len(summary.get("per_region", {})),
        "out": str(out_path),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
