#!/usr/bin/env python3
"""Build deterministic strict cross-song donors from a formal manifest's GT text."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path


def units(path: str) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def lcs_ratio(a: list[str], b: list[str]) -> float:
    row = [0] * (len(b) + 1)
    for x in a:
        old = row[:]
        for j, y in enumerate(b, 1):
            row[j] = old[j - 1] + 1 if x == y else max(old[j], row[j - 1])
    return row[-1] / max(1, len(a))


def ngram_jaccard(a: list[str], b: list[str], n: int = 2) -> float:
    """Character/unit n-gram overlap, including a deterministic unigram fallback."""
    if len(a) < n or len(b) < n:
        n = 1
    left = {tuple(a[i:i + n]) for i in range(max(0, len(a) - n + 1))}
    right = {tuple(b[i:i + n]) for i in range(max(0, len(b) - n + 1))}
    return len(left & right) / max(1, len(left | right))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--donor-pool-manifest", action="append", default=[],
                   help="additional JSONL inventories used only as donor candidates")
    p.add_argument("--out", required=True)
    p.add_argument("--item-id", action="append", required=True)
    p.add_argument("--seed", type=int, default=3407)
    p.add_argument("--lcs-max", type=float, default=0.20)
    p.add_argument("--ngram-jaccard-max", type=float, default=0.25)
    p.add_argument("--unit-count", type=int, default=0,
                   help="use a fixed target prefix length; needed when the experiment is windowed")
    args = p.parse_args(argv)
    records = [json.loads(line) for line in Path(args.manifest).read_text(encoding="utf-8").splitlines() if line]
    targets = {r["item_id"]: r for r in records if r.get("item_id") in set(args.item_id)}
    if set(args.item_id) != set(targets):
        p.error("requested item_id missing from manifest")
    donor_records = list(records)
    for manifest_path in args.donor_pool_manifest:
        donor_records.extend(json.loads(line) for line in Path(manifest_path).read_text(encoding="utf-8").splitlines() if line)
    pool = [r for r in donor_records if r.get("gt_path") and Path(r["gt_path"]).is_file()]
    rng = random.Random(args.seed)
    rows = []
    for item_id in args.item_id:
        target = targets[item_id]; base = units(target["gt_path"])
        n = min(args.unit_count, len(base)) if args.unit_count else len(base)
        base = base[:n]
        if n < 1:
            raise RuntimeError(f"empty target units for {item_id}")
        candidates = list(pool); rng.shuffle(candidates)
        selected = None
        for donor in candidates:
            if donor.get("source_song_id") == target.get("source_song_id") or donor.get("item_id") == item_id:
                continue
            donor_units = units(donor["gt_path"])
            for start in range(0, len(donor_units) - n + 1):
                segment = donor_units[start:start + n]
                ratio = lcs_ratio(base, segment)
                ngram = ngram_jaccard(base, segment)
                if ratio <= args.lcs_max and ngram <= args.ngram_jaccard_max:
                    selected = (donor, start, segment, ratio, ngram)
                    break
            if selected:
                break
        if not selected:
            raise RuntimeError(f"no strict donor for {item_id}")
        donor, start, segment, ratio, ngram = selected
        rows.append({"target_item_id": item_id, "target_source_song_id": target.get("source_song_id"),
                     "target_units_sha256": hashlib.sha256("\x1f".join(base).encode()).hexdigest(),
                     "target_unit_count": n,
                     "donor_item_id": donor["item_id"], "donor_source_song_id": donor.get("source_song_id"),
                     "donor_gt_path": donor["gt_path"], "donor_start_index": start,
                     "donor_end_index": start + n, "donor_units": segment,
                     "similarity": {"normalized_lcs": ratio, "bigram_jaccard": ngram,
                                    "phonetic_check": "not_available_for_normalized_character_gt"},
                     "thresholds": {"normalized_lcs_max": args.lcs_max,
                                    "bigram_jaccard_max": args.ngram_jaccard_max}, "seed": args.seed})
    payload = {"schema": "v7/strict_cross_song_donor_manifest_v1", "rows": rows}
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "rows": len(rows), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
