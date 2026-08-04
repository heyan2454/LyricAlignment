#!/usr/bin/env python3
"""Collect immutable v7 EvidencePack JSON files into a manifest with identities.

The collector is deliberately model-free.  It rejects duplicate request IDs and
records a SHA256 for every source pack, so rendering or later aggregation cannot
silently mix attempts from different inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    root = Path(args.out_root)
    files = sorted((root / "items").glob("**/*.json"))
    seen: set[str] = set()
    records: list[dict] = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        attempt = payload.get("attempt", {})
        request = attempt.get("request", {})
        request_id = request.get("request_id")
        if not request_id:
            raise ValueError(f"{path}: missing attempt.request.request_id")
        if request_id in seen:
            raise ValueError(f"duplicate request_id: {request_id}")
        seen.add(request_id)
        records.append({
            "request_id": request_id,
            "item_id": request.get("item_id"),
            "mutation_type": request.get("mutation_type"),
            "workflow_mode": request.get("workflow_mode"),
            "status": attempt.get("status"),
            "source": str(path.relative_to(root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "audio_hash": payload.get("audio_hash"),
            "text_hash": payload.get("text_hash"),
        })
    output = {"schema": "v7/alignment_behavior_collection_v1", "out_root": str(root), "records": records}
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "records": len(records), "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
