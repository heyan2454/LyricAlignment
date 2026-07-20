#!/usr/bin/env python3
"""Idempotently download the one approved Qwen forced-aligner revision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default="Qwen/Qwen3-ForcedAligner-0.6B-hf")
    parser.add_argument("--revision", default=None)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--local-dir", type=Path, default=None, help="Optional external materialized model directory.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps({"model_id": args.model_id, "revision": args.revision, "cache_dir": str(args.cache_dir), "status": "dry_run"}))
        return
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError as exc:
        raise SystemExit("Install huggingface_hub before downloading: python -m pip install -U huggingface_hub") from exc
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    location = snapshot_download(repo_id=args.model_id, revision=args.revision, cache_dir=str(args.cache_dir), local_dir=str(args.local_dir) if args.local_dir else None)
    info = HfApi().model_info(args.model_id, revision=args.revision)
    files = [str(p.relative_to(location)) for p in Path(location).rglob("*") if p.is_file()]
    manifest = {"model_id": args.model_id, "requested_revision": args.revision, "resolved_revision": info.sha, "local_path": str(location), "file_count": len(files), "files": files}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
