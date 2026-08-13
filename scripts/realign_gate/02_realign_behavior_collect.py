#!/usr/bin/env python3
"""Realign Gate stage 02: case selection + no-GT realign behavior collection.

Drives ``case_selection.run_stage``: stratifies CASE_POOL into S1..S4 cases,
builds R-A/R-B proposal requests, runs the forward suite (smoke fake executor
by default, or the real frozen Qwen executor with --gpu), and rebuilds the
candidate index. GT labels are never generated here (stage 03 only).

Usage:
  PYTHONPATH=src python scripts/realign_gate/02_realign_behavior_collect.py \\
      --run-root <run> [--cfg <CONFIG.json>] [--smoke] [--limit N]
      [--gpu] [--checkpoint-path PATH] [--resume]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.realign_gate import case_selection
from lyricalign.realign_gate import identity


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True, help="run root (stage dirs under it)")
    p.add_argument("--cfg", help="CONFIG.json for stage inputs/params (default <run-root>/00_meta/CONFIG.json)")
    p.add_argument("--smoke", action="store_true", help="fake executor, pure CPU")
    p.add_argument("--limit", type=int, default=0, help="max requests forwarded (smoke default 2)")
    p.add_argument("--gpu", action="store_true", help="real frozen Qwen executor")
    p.add_argument("--checkpoint-path", help="local LoRA checkpoint dir (required with --gpu)")
    p.add_argument("--resume", action="store_true", help="reuse identity-identical evidence")
    p.add_argument("--include-sparse", action="store_true",
                   help="construct true R-S full-text/active-slot/fixed-row requests")
    p.add_argument("--allow-unpaired-rb", action="store_true",
                   help="retain valid R-U/R-A/R-S requests when R-B anchors are unavailable")
    p.add_argument("--r-a-text-k", type=int,
                   help="R-A/R-S context units per side for no-GT padding experiments")
    args = p.parse_args(argv)

    run_root = Path(args.run_root)
    cfg_path = args.cfg or str(run_root / "00_meta" / "CONFIG.json")
    cfg_path = Path(cfg_path)
    if not cfg_path.exists():
        p.error(f"config not found: {cfg_path}")

    smoke = args.smoke or (not args.gpu)
    limit = args.limit if args.limit else (2 if smoke else 0)
    resume = args.resume or args.gpu
    checkpoint_path = args.checkpoint_path or identity.CHECKPOINT_PATH

    summary = case_selection.run_stage(
        run_root,
        cfg_path,
        smoke=smoke,
        limit=limit,
        gpu=args.gpu,
        checkpoint_path=checkpoint_path,
        resume=resume,
        include_sparse=args.include_sparse,
        require_paired_rb=not args.allow_unpaired_rb,
        r_a_text_k=args.r_a_text_k,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("result_status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
