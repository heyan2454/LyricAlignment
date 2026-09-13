#!/usr/bin/env python3
"""Paired per-character comparison of two checkpoints on the same items.

Aggregate hit rates cannot resolve small checkpoint differences (the whole-set 0.2 s number is
saturated and the song-macro noise floor is ~0.5 pp), but comparing the *same characters* across two
checkpoints removes song/character difficulty entirely and is far more sensitive.  Consumes the
per-character dumps written by `measure_predicted_boundary_acoustics.py`.

    PYTHONPATH=src python scripts/evaluation/paired_checkpoint_comparison.py \
        --old results/by_run/20260913_boundary_pred_vs_gt_old750_v3/per_character.jsonl \
        --new results/by_run/20260914_boundary_pred_vs_gt_new12000/per_character.jsonl \
        --out results/by_run/20260914_paired_old750_vs_new12000/metrics.json
"""
from __future__ import annotations
import argparse, json, statistics as st
from collections import defaultdict
from pathlib import Path

CHANNEL = "d_rms"


def load(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["channel"] == CHANNEL:
            out[(row["item_id"], row["index"], row["kind"])] = row
    return out


def paired(keys, old, new, *, long=None):
    keys = [k for k in keys if long is None or old[k]["long"] == long]
    if len(keys) < 3:
        return None
    diff = [1000.0 * (new[k]["abs_err_argmax"] - old[k]["abs_err_argmax"]) for k in keys]
    mean = st.mean(diff)
    se = st.stdev(diff) / len(diff) ** 0.5 if len(diff) > 1 else 0.0
    return {"n": len(keys), "mean_delta_ms": round(mean, 2), "se_ms": round(se, 2),
            "z": round(mean / se, 2) if se else None,
            "better": sum(1 for x in diff if x < -1), "worse": sum(1 for x in diff if x > 1),
            "miss_rate_old": round(sum(1 for k in keys if old[k]["abs_err_argmax"] > 0.2) / len(keys), 4),
            "miss_rate_new": round(sum(1 for k in keys if new[k]["abs_err_argmax"] > 0.2) / len(keys), 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--tolerance", type=float, default=0.2)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    old, new = load(args.old), load(args.new)
    shared = sorted(set(old) & set(new))
    result = {"schema_version": "paired_checkpoint_comparison_v1",
              "old": str(args.old), "new": str(args.new), "shared_measurements": len(shared),
              "items": len({k[0] for k in shared}), "tolerance_sec": args.tolerance, "sides": {}}
    for kind in ("onset", "offset"):
        for label, long in (("all", None), ("long", True), ("short", False)):
            block = paired([k for k in shared if k[2] == kind], old, new, long=long)
            if block:
                result["sides"][f"{kind}_{label}"] = block
    both = defaultdict(dict)
    for (item, index, kind) in shared:
        both[(item, index)][kind] = True
    complete = [(i, j) for (i, j), kinds in both.items() if len(kinds) == 2]
    def maxerr(store, item, index):
        return max(store[(item, index, "onset")]["abs_err_argmax"], store[(item, index, "offset")]["abs_err_argmax"])
    for label, keys in (("combined_all", complete),
                        ("combined_long", [(i, j) for (i, j) in complete if old[(i, j, "onset")]["long"]])):
        if len(keys) < 3:
            continue
        diff = [1000.0 * (maxerr(new, i, j) - maxerr(old, i, j)) for i, j in keys]
        mean = st.mean(diff)
        se = st.stdev(diff) / len(diff) ** 0.5
        result["sides"][label] = {"n": len(keys), "mean_delta_ms": round(mean, 2), "se_ms": round(se, 2),
                                  "z": round(mean / se, 2) if se else None,
                                  "miss_rate_old": round(sum(1 for i, j in keys if maxerr(old, i, j) > args.tolerance) / len(keys), 4),
                                  "miss_rate_new": round(sum(1 for i, j in keys if maxerr(new, i, j) > args.tolerance) / len(keys), 4)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
