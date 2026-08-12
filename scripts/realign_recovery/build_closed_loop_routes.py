#!/usr/bin/env python3
"""D2 closed-loop route plan builder（纯 CPU，不加载 GT）。

读取 E5 REQUESTS 与 candidate bank，把 bank 行按 ``proposal_id`` 前缀回推
episode_id（前缀取自 REQUESTS 的 ``provenance.episode_id``，回推失败标记为
``"episode_id": null`` 并计数），随后调用 ``closed_loop.build_route_plan``
生成 C0/C0S/C1/C2/C3 五 route 计划，并按 plan 为 C2/C3 复制请求行。

输出：
- ``<run>/closed_loop/routes/ROUTE_PLAN.json``
- ``<run>/closed_loop/routes/requests/C2.jsonl`` / ``C3.jsonl``
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.candidate_scores import (  # noqa: E402
    load_bank,
    load_requests,
)
from lyricalign.realign_recovery.closed_loop import build_route_plan  # noqa: E402
from lyricalign.realign_recovery.run_objects import (  # noqa: E402
    atomic_write_text,
    write_jsonl,
)

DEFAULT_RUN_ROOT = "/home/hyan/Data/lyricalign/runs/realign_recovery_20260812_20260811T202813Z"

ROUTE_SELECTION = ("C2", "C3")


def enrich_bank_episodes(bank_rows, episode_ids) -> tuple[list[dict], int]:
    """按 ``proposal_id`` 前缀回推每行 episode_id；失败置 None 并计数。"""
    enriched = []
    unmatched = 0
    for row in bank_rows:
        copy = dict(row)
        ep = None
        pid = copy.get("proposal_id")
        if pid:
            for cand in episode_ids:
                if str(pid).startswith(cand + ":"):
                    ep = cand
                    break
        if ep is None:
            unmatched += 1
        copy["episode_id"] = ep
        enriched.append(copy)
    return enriched, unmatched


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", default=DEFAULT_RUN_ROOT,
                   help=f"run root（默认 {DEFAULT_RUN_ROOT}）")
    args = p.parse_args(argv)

    run_root = Path(args.run_root)
    requests_path = run_root / "e5_proposals" / "raw" / "REQUESTS.jsonl"
    bank_path = run_root / "e5_proposals" / "candidate_bank" / "candidate_bank.jsonl"
    out_dir = run_root / "closed_loop" / "routes"
    requests_dir = out_dir / "requests"

    requests_by_id = load_requests(requests_path)
    requests = list(requests_by_id.values())
    bank_rows = load_bank(bank_path)

    episode_ids = sorted({
        str(req["provenance"]["episode_id"])
        for req in requests
        if (req.get("provenance") or {}).get("episode_id")
    })
    enriched_bank, unmatched_bank = enrich_bank_episodes(bank_rows, episode_ids)

    plan = build_route_plan(enriched_bank, requests)

    route_plan_path = out_dir / "ROUTE_PLAN.json"
    atomic_write_text(
        route_plan_path,
        json.dumps(plan, ensure_ascii=False, indent=1) + "\n",
    )

    c2_rows = []
    c3_rows = []
    per_episode = plan["per_episode"]
    for req in requests:
        ep = (req.get("provenance") or {}).get("episode_id")
        if ep not in per_episode:
            continue
        if "C2" in per_episode[ep]:
            c2_rows.append({**req, "route": "C2"})
        if "C3" in per_episode[ep]:
            c3_rows.append({**req, "route": "C3"})

    c2_path = requests_dir / "C2.jsonl"
    c3_path = requests_dir / "C3.jsonl"
    write_jsonl(c2_path, c2_rows)
    write_jsonl(c3_path, c3_rows)

    needs_forward = {rid: 0 for rid in plan["routes"]}
    for ep_entry in per_episode.values():
        for rid, spec in ep_entry.items():
            if spec.get("needs_forward"):
                needs_forward[rid] = needs_forward.get(rid, 0) + 1

    print(json.dumps({
        "ok": True,
        "n_episodes": plan["n_episodes"],
        "n_routes": plan["n_routes"],
        "needs_forward": needs_forward,
        "unmatched_bank": unmatched_bank,
        "n_bank": len(bank_rows),
        "n_requests": len(requests),
        "c2_rows": len(c2_rows),
        "c3_rows": len(c3_rows),
        "outputs": {
            "route_plan": str(route_plan_path),
            "c2_requests": str(c2_path),
            "c3_requests": str(c3_path),
        },
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
