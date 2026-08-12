#!/usr/bin/env python3
"""closed-loop C2/C3 REQUESTS GPU forward CLI.

复用 research_v7 冻结的 real-executor 路径（run_behavior_suite --real）对
closed_loop 的 C2/C3 REQUESTS 逐行 forward，再汇总顶层 RUN_MANIFEST.json。
per-item 失败、content-identity 缓存复用（--resume）与 evidence 落盘全部委托给
run_behavior_suite，本 CLI 不重复造 forward 引擎。

用法：
  PYTHONPATH=src python scripts/realign_recovery/run_closed_loop_forward.py \
      --run-root /home/hyan/Data/lyricalign/runs/realign_recovery_20260812_20260811T202813Z \
      --model-dir <HF snapshot> --checkpoint-path <R2 LoRA ckpt> --revision main
  # 冒烟：--routes C2,C3 --max-rows 0（不触碰 GPU，仅产空 manifest）
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from lyricalign.realign_recovery.run_objects import atomic_write_text  # noqa: E402

DEFAULT_RUN_ROOT = "/home/hyan/Data/lyricalign/runs/realign_recovery_20260812_20260811T202813Z"
SCHEMA = "realign_recovery_closed_loop_forward_v1"


def _load_behavior_suite():
    name = "research_v7_run_behavior_suite"
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    path = _REPO / "scripts" / "research_v7" / "run_behavior_suite.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        return ""


def _git_dirty() -> str:
    def _h(*parts):
        return hashlib.sha256(b":".join(p.encode() if isinstance(p, str) else p for p in parts)).hexdigest()
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        staged = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True).stdout or ""
        unstaged = subprocess.run(["git", "diff"], capture_output=True, text=True).stdout or ""
    except Exception:  # noqa
        return hashlib.sha256(b"unknown").hexdigest()
    return _h(head, staged, unstaged)


def _plan_needs_forward(run_root: Path, rid: str, warnings: list[str]) -> bool:
    plan_path = run_root / "closed_loop" / "routes" / "ROUTE_PLAN.json"
    if not plan_path.is_file():
        warnings.append(f"ROUTE_PLAN.json missing at {plan_path}; assume {rid} needs_forward=True per contract")
        return True
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa
        warnings.append(f"ROUTE_PLAN.json unreadable ({e}); assume {rid} needs_forward=True")
        return True
    per_ep = plan.get("per_episode") or {}
    any_episode = any(
        ((spec or {}).get(rid) or {}).get("needs_forward")
        for spec in per_ep.values() if isinstance(spec, dict))
    if any_episode:
        return True
    warnings.append(f"route {rid}: no episode has needs_forward=True in ROUTE_PLAN per_episode; skipped")
    return False


def _forward_route(bs, args, rid: str, req_file: Path, route_out: Path, warnings: list[str]) -> dict:
    if not req_file.is_file():
        return {"route": rid, "status": "missing_requests", "requests_file": str(req_file)}
    argv = ["--manifest", str(req_file), "--out-root", str(route_out),
            "--real", "--resume",
            "--model-dir", args.model_dir, "--checkpoint-path", args.checkpoint_path,
            "--revision", args.revision, "--model", args.model, "--checkpoint", args.checkpoint]
    if args.max_rows > 0:
        argv += ["--limit", str(args.max_rows)]
    if args.model_dir is None or args.checkpoint_path is None:
        return {"route": rid, "status": "missing_model", "error": "--model-dir and --checkpoint-path required to forward"}
    rc = bs.main(argv)
    manifest_path = route_out / "RUN_MANIFEST.json"
    if rc != 0 or not manifest_path.is_file():
        return {"route": rid, "status": "runner_failed", "exit_code": rc, "out_root": str(route_out)}
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    ic = m.get("item_count") or {}
    return {
        "route": rid, "status": "ok", "out_root": str(route_out),
        "requests_file": str(req_file),
        "rows": ic.get("requests", 0), "ok": ic.get("requests", 0) - ic.get("failed", 0),
        "cache_hit": ic.get("cache_hit", 0), "forward": ic.get("forward", 0),
        "failed": ic.get("failed", 0),
        "runtime_sec": (m.get("runtime_budget") or {}).get("elapsed_sec"),
        "evidence_inventory": m.get("evidence_inventory", []),
        "failures": m.get("failures", []),
        "role": ic.get("role", {}),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", default=DEFAULT_RUN_ROOT)
    p.add_argument("--model-dir", help="HF snapshot dir (Qwen Forced Aligner base); required unless --max-rows 0")
    p.add_argument("--checkpoint-path", help="frozen R2 LoRA checkpoint dir; required unless --max-rows 0")
    p.add_argument("--revision", default="main")
    p.add_argument("--model", default="Qwen3-ForcedAligner-0.6B-hf")
    p.add_argument("--checkpoint", default="r2-step-000750")
    p.add_argument("--out-root", default=None)
    p.add_argument("--routes", default="C2,C3")
    p.add_argument("--max-rows", type=int, default=0, help="limit rows per route (0 = all rows / smoke-skip)")
    args = p.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_dir():
        print(json.dumps({"ok": False, "error": f"run-root not found: {run_root}"}, ensure_ascii=False))
        return 2
    out_root = Path(args.out_root) if args.out_root else run_root / "closed_loop" / "forward"
    route_ids = [r.strip() for r in args.routes.split(",") if r.strip()]
    warnings: list[str] = []
    t_start = time.time()

    if args.max_rows == 0:
        bs = None
    else:
        if not args.model_dir or not args.checkpoint_path:
            p.error("--model-dir and --checkpoint-path are required for forward (or use --max-rows 0 for smoke)")
        bs = _load_behavior_suite()

    per_route: dict[str, dict] = {}
    for rid in route_ids:
        needs = _plan_needs_forward(run_root, rid, warnings)
        if not needs:
            per_route[rid] = {"route": rid, "status": "skipped_no_forward"}
            warnings.append(f"route {rid}: needs_forward=False in plan, skipped")
            continue
        req_file = run_root / "closed_loop" / "routes" / "requests" / f"{rid}.jsonl"
        route_out = out_root / "route" / rid
        if args.max_rows == 0:
            per_route[rid] = {"route": rid, "status": "smoke_skip", "rows": 0, "ok": 0,
                              "cache_hit": 0, "forward": 0, "failed": 0,
                              "requests_file": str(req_file)}
            continue
        per_route[rid] = _forward_route(bs, args, rid, req_file, route_out, warnings)

    totals = {
        "rows": sum(r.get("rows", 0) for r in per_route.values()),
        "ok": sum(r.get("ok", 0) for r in per_route.values()),
        "cache_hit": sum(r.get("cache_hit", 0) for r in per_route.values()),
        "forward": sum(r.get("forward", 0) for r in per_route.values()),
        "failed": sum(r.get("failed", 0) for r in per_route.values()),
        "elapsed_sec": round(time.time() - t_start, 3),
    }
    evidence_inventory = []
    for r in per_route.values():
        for ev in r.get("evidence_inventory", []):
            if ev.get("path") not in {e.get("path") for e in evidence_inventory}:
                evidence_inventory.append(ev)
    evidence_inventory.sort(key=lambda e: str(e.get("path", "")))

    plan_path = run_root / "closed_loop" / "routes" / "ROUTE_PLAN.json"
    manifest = {
        "schema": SCHEMA,
        "run_id": f"cl-forward-{time.strftime('%Y%m%d_%H%M%S')}",
        "code_identity": {"git_commit": _git_head(), "source_tree": _git_dirty()},
        "run_root": str(run_root),
        "out_root": str(out_root),
        "model": {"model": args.model, "revision": args.revision, "checkpoint": args.checkpoint,
                  "model_dir": args.model_dir, "checkpoint_path": args.checkpoint_path},
        "route_plan": str(plan_path) if plan_path.is_file() else None,
        "per_route": per_route,
        "total": totals,
        "evidence_inventory": evidence_inventory,
        "warnings": warnings,
        "max_rows": args.max_rows,
    }
    atomic_write_text(str(out_root / "RUN_MANIFEST.json"), json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": True, "schema": SCHEMA, "routes": sorted(per_route),
                      "rows": totals["rows"], "ok": totals["ok"],
                      "cache_hit": totals["cache_hit"], "forward": totals["forward"],
                      "failed": totals["failed"], "out_root": str(out_root),
                      "warnings": warnings}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
