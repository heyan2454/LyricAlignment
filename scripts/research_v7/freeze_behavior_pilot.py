#!/usr/bin/env python3
"""Freeze pilot inputs before formal v7 collection.

Writes hashes of the exact behavior manifest, mutation catalogue and optional
donor manifest.  Existing output is never overwritten unless its content is
identical, preventing an accidental mid-pilot donor/ratio change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behavior-manifest", required=True)
    parser.add_argument("--mutation-catalog", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--donor-manifest")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--commit-policy", required=True)
    parser.add_argument("--slot-policy", required=True)
    args = parser.parse_args(argv)
    inputs = {"behavior_manifest": Path(args.behavior_manifest), "mutation_catalog": Path(args.mutation_catalog)}
    if args.donor_manifest:
        inputs["donor_manifest"] = Path(args.donor_manifest)
    missing = [str(p) for p in inputs.values() if not p.is_file()]
    if missing:
        parser.error("missing freeze input: " + ", ".join(missing))
    payload = {
        "schema": "v7/behavior_pilot_freeze_v1",
        "seed": args.seed,
        "commit_policy": args.commit_policy,
        "slot_policy": args.slot_policy,
        "inputs": {name: {"path": str(path), "sha256": digest(path)} for name, path in inputs.items()},
    }
    target = Path(args.out)
    if target.exists():
        old = json.loads(target.read_text(encoding="utf-8"))
        if old != payload:
            parser.error(f"refusing to overwrite a different pilot freeze: {target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(target), "manifest_sha256": payload["inputs"]["behavior_manifest"]["sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
