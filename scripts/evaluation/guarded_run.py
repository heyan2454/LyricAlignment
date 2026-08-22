#!/usr/bin/env python3
"""Run a command only if the Evaluation V1 manifest access policy allows it.

This is the productization gate wrapper: by default it refuses sealed_final.
Pass --allow-sealed only for a registered milestone run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_policy(rows: list[dict], allowed_tiers: set[str], allow_sealed: bool) -> list[str]:
    problems = []
    tiers = Counter(str(r.get("tier", "")) for r in rows)
    if "sealed_final" in tiers and not allow_sealed:
        problems.append(f"manifest contains {tiers['sealed_final']} sealed_final rows; pass --allow-sealed only for milestones")
    unexpected = sorted(set(tiers) - allowed_tiers)
    if unexpected:
        problems.append(f"manifest contains tiers outside allowed set: {unexpected}")
    group_tiers: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        group_tiers[str(r.get("group_id", ""))].add(str(r.get("tier", "")))
    cross = sorted(g for g, s in group_tiers.items() if len(s) > 1)
    if cross:
        problems.append(f"same group appears in multiple tiers: {cross}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tiers", default="diagnostic_visible,regression_selection")
    parser.add_argument("--allow-sealed", action="store_true")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    rows = load_rows(args.manifest)
    allowed = {t.strip() for t in args.tiers.split(",") if t.strip()}
    problems = check_policy(rows, allowed, args.allow_sealed)
    if problems:
        report = {"allowed": False, "problems": problems, "manifest": str(args.manifest)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    if not args.cmd or args.cmd == ["--"]:
        print(json.dumps({"allowed": True, "command": None}, ensure_ascii=False, indent=2))
        return 0
    # argparse REMAINDER may include a leading '--'
    cmd = args.cmd[1:] if args.cmd[0] == "--" else args.cmd
    print(json.dumps({"allowed": True, "command": cmd}, ensure_ascii=False))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
