#!/usr/bin/env python3
"""D4: closed-loop route report 聚合器（纯 CPU，不加载 GT）。

读 ``RUN_DECISIONS.jsonl``（run_closed_loop_decision.py 产物），按 route
聚合：
- repair 指标：每行推导 ``repair_success`` / ``safe_damage`` /
  ``harmful_writeback``，再调 ``closed_loop.aggregate_repair_metrics``；
- 成本：每行由 ``needs_forward`` 与 ``retry_count`` 推导 ``extra_forwards``，
  ``cache_hit`` 从 ``closed_loop/forward/RUN_MANIFEST.json`` 的 per-route
  forward 计数读取（manifest 缺失时恒 False 并记 warn），再调
  ``closed_loop.aggregate_route_cost``；
- serial recovery 分布与 C0 vs C1 vs C3 paired delta（n_episodes 对齐后
  episode 级 repair_success_rate 之差）。

产出 ``CLOSED_LOOP_REPORT.json`` 并打印文本摘要。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.closed_loop import (  # noqa: E402
    aggregate_route_cost,
    aggregate_repair_metrics,
)

_DEFAULT_RUN = "/home/hyan/Data/lyricalign/runs/realign_recovery_20260812_20260811T202813Z"
_PAIRS = (("C0", "C1"), ("C0", "C3"), ("C1", "C3"))


def _load_jsonl(path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _repair_row(row: dict) -> dict:
    action = row.get("action", "")
    writeback = bool(row.get("writeback", False))
    trigger = bool(row.get("trigger", False))
    return {
        "repair_success": "writeback" in action and writeback,
        "safe_damage": trigger and not writeback,
        "harmful_writeback": action == "unconditional_writeback" and writeback,
    }


def _cost_row(row: dict, fwd_info: dict | None) -> dict:
    needs_forward = bool(row.get("needs_forward", False))
    retry = int(row.get("retry_count", 0))
    cache_hit = False
    if fwd_info is not None:
        total = fwd_info.get("rows", 0) + fwd_info.get("failed", 0)
        cache_hit = total > 0 and fwd_info.get("cache_hit", 0) == total
    return {
        "extra_forwards": (1 if needs_forward else 0) + retry,
        "processed_audio_sec": float(row.get("processed_audio_sec", 0.0)),
        "retry_count": retry,
        "cache_hit": cache_hit,
    }


def _load_forward_manifest(run_root: Path) -> dict | None:
    mpath = run_root / "closed_loop" / "forward" / "RUN_MANIFEST.json"
    if not mpath.is_file():
        return None
    try:
        m = json.loads(mpath.read_text(encoding="utf-8"))
    except Exception:  # noqa
        return None
    out: dict[str, dict] = {}
    for rid, info in (m.get("per_route") or {}).items():
        if isinstance(info, dict):
            out[str(rid)] = {
                "rows": info.get("rows", 0),
                "cache_hit": info.get("cache_hit", 0),
                "forward": info.get("forward", 0),
                "failed": info.get("failed", 0),
            }
    return out or None


def _paired_deltas(rows: list[dict]) -> dict:
    by_route: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        by_route.setdefault(r["route"], {}).setdefault(
            r["episode_id"], []).append(r)
    out = {}
    for a, b in _PAIRS:
        a_eps, b_eps = by_route.get(a, {}), by_route.get(b, {})
        common = sorted(set(a_eps) & set(b_eps))
        if not common:
            out[f"{a}_vs_{b}"] = {"n_episodes": 0, "delta_repair_success": None}
            continue
        a_ok = sum(1 for ep in common
                   if any(_repair_row(r)["repair_success"] for r in a_eps[ep]))
        b_ok = sum(1 for ep in common
                   if any(_repair_row(r)["repair_success"] for r in b_eps[ep]))
        out[f"{a}_vs_{b}"] = {
            "n_episodes": len(common),
            "delta_repair_success": (b_ok - a_ok) / len(common),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root", default=_DEFAULT_RUN,
                    help=f"run root（默认 {_DEFAULT_RUN}）")
    ap.add_argument("--out-root", default=None,
                    help="输出目录（默认 <run-root>/closed_loop/report）")
    args = ap.parse_args(argv)

    run = Path(args.run_root)
    out_root = Path(args.out_root) if args.out_root else run / "closed_loop" / "report"
    out_root.mkdir(parents=True, exist_ok=True)

    dec_path = run / "closed_loop" / "decision" / "RUN_DECISIONS.jsonl"
    if not dec_path.exists():
        print(f"[error] RUN_DECISIONS not found: {dec_path}; run "
              f"scripts/realign_recovery/run_closed_loop_decision.py first",
              file=sys.stderr)
        return 2
    rows = _load_jsonl(dec_path)
    if not rows:
        print(f"[error] RUN_DECISIONS is empty: {dec_path}", file=sys.stderr)
        return 2

    fwd_manifest = _load_forward_manifest(run)
    if fwd_manifest is None:
        print("[warn] no closed_loop/forward/RUN_MANIFEST.json; cost uses "
              "decision-row needs_forward only (cache_hit_rate=0, audio_sec=0)",
              file=sys.stderr)

    routes = sorted({r["route"] for r in rows})
    per_route: dict[str, dict] = {}
    for route in routes:
        route_rows = [r for r in rows if r["route"] == route]
        serial_dist: dict[str, int] = {}
        for r in route_rows:
            serial_dist[r["serial_recovery"]] = (
                serial_dist.get(r["serial_recovery"], 0) + 1)
        fwd_info = (fwd_manifest or {}).get(route)
        per_route[route] = {
            "repair_metrics": aggregate_repair_metrics(
                [_repair_row(r) for r in route_rows]),
            "route_cost": aggregate_route_cost(
                [_cost_row(r, fwd_info) for r in route_rows]),
            "serial_recovery": serial_dist,
            "n_episodes": len({r["episode_id"] for r in route_rows}),
            "forward_source": "forward_manifest" if fwd_info else "decisions_only",
            "forward_counts": fwd_info,
        }

    report = {
        "schema_version": "realign_recovery_closed_loop_report_v1",
        "run_root": str(run),
        "n_routes": len(routes),
        "per_route": per_route,
        "paired_deltas": _paired_deltas(rows),
        "cost": {route: per_route[route]["route_cost"] for route in routes},
    }
    report_path = out_root / "CLOSED_LOOP_REPORT.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print("\nClosed-loop route report:")
    for route in routes:
        rm = per_route[route]["repair_metrics"]
        rc = per_route[route]["route_cost"]
        sd = per_route[route]["serial_recovery"]
        print(f"  {route:<4} n={rm['n']:>4} "
              f"repair={rm['repair_success_rate']:.3f} "
              f"safe_damage={rm['safe_damage_rate']:.3f} "
              f"harmful={rm['harmful_writeback_rate']:.3f} "
              f"extra_fwd={rc['total_extra_forwards']} "
              f"cache_hit={rc['cache_hit_rate']:.2f} "
              f"serial={json.dumps(sd, ensure_ascii=False)}")
    for key, val in report["paired_deltas"].items():
        print(f"  paired {key}: {val}")
    print(f"  report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
