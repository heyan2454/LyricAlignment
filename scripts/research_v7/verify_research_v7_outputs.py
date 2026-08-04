#!/usr/bin/env python3
"""Verify v7 collected evidence identities and hashes before analysis/reporting."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    args = parser.parse_args(argv)
    collection = json.loads(Path(args.collection).read_text(encoding="utf-8"))
    root = Path(collection["out_root"])
    errors = []
    seen = set()
    for record in collection.get("records", []):
        request_id = record.get("request_id")
        path = root / record.get("source", "")
        if request_id in seen:
            errors.append(f"duplicate request_id {request_id}")
        seen.add(request_id)
        if not path.is_file():
            errors.append(f"missing source {path}")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
            errors.append(f"hash mismatch {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("attempt", {}).get("request", {}).get("request_id") != request_id:
            errors.append(f"request identity mismatch {path}")
        if not payload.get("audio_hash") or not payload.get("text_hash"):
            errors.append(f"missing input hash {path}")
    result = {"ok": not errors, "records": len(collection.get("records", [])), "errors": errors}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
