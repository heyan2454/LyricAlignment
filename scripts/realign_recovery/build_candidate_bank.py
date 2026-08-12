#!/usr/bin/env python3
"""D1 candidate bank builder（纯 CPU，不加载 GT）。

把 E1 oracle + E5 proposal 的 GPU forward evidence 汇入同一 candidate bank：
每个有效 episode 10-20 个 candidates（不做窗口笛卡尔积）。行即 run_objects
``Candidate``（schema realign_recovery_run_objects_v1）；bank 不加载 GT。

输出：bank JSONL + 同目录 CANDIDATE_BANK_SUMMARY.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.candidate_bank import build_candidate_bank  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--e5-requests", required=True, help="E5 REQUESTS.jsonl")
    p.add_argument("--e5-evidence-dir", required=True, help="E5 formal evidence 目录")
    p.add_argument("--e1-requests", required=True, help="E1 oracle REQUESTS.jsonl")
    p.add_argument("--e1-evidence-dir", required=True, help="E1 oracle evidence 目录")
    p.add_argument("--episodes", required=True, help="E4 episodes.jsonl")
    p.add_argument("--plan", required=True, help="E5 PROPOSAL_PLAN.json")
    p.add_argument("--timeline-manifests", required=True, nargs="+",
                   help="LONG_TIMELINE_MANIFEST.jsonl（可多个）")
    p.add_argument("--out", required=True, help="bank JSONL 输出路径")
    p.add_argument("--resume", action="store_true", help="跳过已存在的候选行（按 id）")
    p.add_argument("--limit", type=int, default=0, help="只处理前 N 个 episode")
    args = p.parse_args(argv)

    limit = args.limit or None
    summary = build_candidate_bank(
        args.e5_requests,
        args.e5_evidence_dir,
        args.e1_requests,
        args.e1_evidence_dir,
        args.episodes,
        args.plan,
        args.timeline_manifests,
        args.out,
        limit=limit,
        resume=args.resume,
    )

    summary_path = Path(args.out).with_name("CANDIDATE_BANK_SUMMARY.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "out": args.out,
        "summary": summary_path.name,
        "n_candidates": summary["n_candidates"],
        "gate_violations": summary["gate_violations"],
        "n_unmapped_regions": len(summary["unmapped_regions"]),
        "ownership": summary["ownership"],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
