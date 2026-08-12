#!/usr/bin/env python3
"""E5 no-GT realign proposal request builder（纯 CPU，不做推理）。

从 E4 episodes（effective natural/P1..P5）与 E3 baseline（detector_shadow
unsafe_intervals）出发，构造 R-A / R-B / R-C + original + oracle 候选 REQUESTS，
写 research_v7 兼容 REQUESTS.jsonl（供 run_behavior_suite.py --real 消费）。

额外产物（均在 --out 同目录）：
- PROPOSAL_PLAN.json    逐 request 的 proposal 元数据（episode/family/method/span）；
- NO_GT_CHECK.json      逐行 validate_no_gt_request 校验结果 {n_rows, violations: []}；
- PROPOSAL_SUMMARY.json 按 family/method 统计。

GT 只在离线评分阶段消费；本脚本不读任何真实标注。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.e5_proposals import (  # noqa: E402
    build_proposals,
    load_episodes,
    write_requests,
)
from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request  # noqa: E402


def _load_jsonl(path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--episodes", required=True, help="E4 episodes.jsonl")
    p.add_argument("--baseline", required=True, help="E3 baseline.jsonl（raw）")
    p.add_argument("--timeline-manifests", required=True, nargs="+",
                   help="LONG_TIMELINE_MANIFEST.jsonl（可多个）")
    p.add_argument("--out", required=True, help="REQUESTS.jsonl 输出路径")
    p.add_argument("--families", default=None,
                   help="逗号分隔 episode family 白名单（默认全部）")
    p.add_argument("--kinds", default=None,
                   help="逗号分隔 episode kind 白名单（natural/propagated）")
    p.add_argument("--limit", type=int, default=0, help="处理前 N 个 episode")
    p.add_argument("--r-a-context-sec", type=float, default=2.0)
    p.add_argument("--r-a-text-k", type=int, default=2)
    p.add_argument("--r-b-text-k", type=int, default=2)
    p.add_argument("--skip-original", action="store_true")
    p.add_argument("--skip-oracle", action="store_true")
    p.add_argument("--skip-ra", action="store_true")
    p.add_argument("--skip-rb", action="store_true")
    p.add_argument("--skip-rc", action="store_true")
    args = p.parse_args(argv)

    episodes = load_episodes(args.episodes)
    if args.families:
        fams = {f.strip() for f in args.families.split(",") if f.strip()}
        episodes = [e for e in episodes if e.get("family") in fams]
    if args.kinds:
        kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
        episodes = [e for e in episodes if e.get("kind") in kinds]
    if args.limit:
        episodes = episodes[: args.limit]

    baseline_rows = _load_jsonl(args.baseline)

    requests, plan = build_proposals(
        episodes,
        args.timeline_manifests,
        baseline_rows,
        r_a_context_sec=args.r_a_context_sec,
        r_a_text_k=args.r_a_text_k,
        r_b_text_k=args.r_b_text_k,
        include_original=not args.skip_original,
        include_oracle=not args.skip_oracle,
        include_ra=not args.skip_ra,
        include_rb=not args.skip_rb,
        include_rc=not args.skip_rc,
    )

    out_path = write_requests(requests, args.out)
    out_dir = Path(out_path).parent

    plan_path = out_dir / "PROPOSAL_PLAN.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    violations = []
    for row in requests:
        found = validate_no_gt_request(row)
        if found:
            violations.append({"request_id": row.get("request_id"), "fields": sorted(found)})
    no_gt = {"n_rows": len(requests), "violations": violations}
    (out_dir / "NO_GT_CHECK.json").write_text(
        json.dumps(no_gt, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    summary = {
        "n_episodes_input": len(episodes),
        "n_requests": len(requests),
        "per_method": dict(Counter(pr["proposal_method"] for pr in plan)),
        "per_family": dict(Counter(pr["family"] for pr in plan)),
        "per_kind": dict(Counter(pr["kind"] for pr in plan)),
        "no_gt_check": no_gt,
    }
    (out_dir / "PROPOSAL_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "n_episodes_input": len(episodes),
        "n_requests": len(requests),
        "per_method": summary["per_method"],
        "per_family": summary["per_family"],
        "per_kind": summary["per_kind"],
        "out": out_path,
        "proposal_plan": str(plan_path),
        "no_gt_check": no_gt,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
