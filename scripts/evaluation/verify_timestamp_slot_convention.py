#!/usr/bin/env python3
"""Verify the timestamp slot convention and that `slot="offset"` weights the end slot only.

Cheap integrity check that must run before interpreting any result from the loss-weighting arm: if the
label pairs were (end, start) rather than (start, end), weighting "offset" would silently weight
onsets instead, and every C-vs-A comparison would be reading an artefact.

Reads the derived label file, and for every item:
  * counts pairs with end > start (expected: all of them),
  * builds the label tensor and checks that each weighted position is the *second* slot of a pair
    whose implied duration is at least `long_sec`.

    PYTHONPATH=src python scripts/evaluation/verify_timestamp_slot_convention.py \
        --labels /home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl \
        --limit 400 --out results/by_run/20260914_slot_convention/metrics.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.training.timestamp_loss import slot_weights  # noqa: E402


def check(labels_path: Path, *, limit: int, long_sec: float, weight: float) -> dict[str, Any]:
    forward = reverse = equal = 0
    items_ok = items_checked = 0
    weighted_slots = 0
    for index, line in enumerate(labels_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip() or (limit and index >= limit):
            break
        row = json.loads(line)
        ids = row.get("timestamp_class_ids") or []
        step = float(row.get("timestamp_segment_sec", 0.08))
        pairs = [(ids[2 * position], ids[2 * position + 1]) for position in range(len(ids) // 2)]
        for start, end in pairs:
            if end > start:
                forward += 1
            elif end < start:
                reverse += 1
            else:
                equal += 1
        tensor = None
        try:
            import torch
            tensor = torch.tensor([ids], dtype=torch.long)
        except ImportError:  # pragma: no cover
            break
        mask = slot_weights(tensor, step_sec=step, long_sec=long_sec, weight=weight, slot="offset")
        hits = [position for position in range(len(ids)) if float(mask[0, position]) == weight]
        weighted_slots += len(hits)
        ok = all(position % 2 == 1 and ids[position] > ids[position - 1]
                 and (ids[position] - ids[position - 1]) * step >= long_sec for position in hits)
        items_checked += 1
        items_ok += int(ok)
    total = forward + reverse + equal
    return {"schema_version": "slot_convention_v1", "labels": str(labels_path),
            "characters": total, "pairs_forward": forward, "pairs_reversed": reverse, "pairs_equal": equal,
            "forward_share": round(forward / max(1, total), 6),
            "items_checked": items_checked, "items_offset_slots_valid": items_ok,
            "weighted_slot_count": weighted_slots,
            "weighted_slot_share": round(weighted_slots / max(1, total * 2), 4),
            "verdict": "pass" if (reverse == 0 and equal == 0 and items_ok == items_checked and weighted_slots > 0)
            else "fail"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"))
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--long-sec", type=float, default=1.0)
    parser.add_argument("--weight", type=float, default=3.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    payload = check(args.labels, limit=args.limit, long_sec=args.long_sec, weight=args.weight)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    raise SystemExit(0 if payload["verdict"] == "pass" else 1)


if __name__ == "__main__":
    main()
