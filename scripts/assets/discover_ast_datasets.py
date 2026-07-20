#!/usr/bin/env python3
"""Read-only AST M4Singer/MIR-1K discovery and lightweight audit JSON."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


MEDIA = {".wav", ".flac", ".mp3", ".m4a"}


def count_files(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file()) if root.exists() else 0


def size_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0


def first_media(root: Path) -> Path | None:
    return next((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA), None)


def probe_audio(path: Path | None) -> dict:
    if not path:
        return {"status": "no_media_found"}
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(path)]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    return {"path": str(path), "status": "ok" if result.returncode == 0 else "failed", "ffprobe": json.loads(result.stdout) if result.returncode == 0 else result.stderr.strip()}


def inspect(name: str, root: Path) -> dict:
    media = first_media(root)
    return {
        "dataset": name,
        "candidate_root": str(root),
        "exists": root.exists(),
        "resolved_root": str(root.resolve()) if root.exists() else None,
        "file_count": count_files(root),
        "size_bytes": size_bytes(root),
        "sample_audio": probe_audio(media),
        "direct_read_only_reuse": root.exists() and media is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m4singer-root", type=Path, required=True)
    parser.add_argument("--mir1k-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = {"mode": "read_only", "datasets": [inspect("m4singer", args.m4singer_root), inspect("mir1k", args.mir1k_root)]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(args.out)


if __name__ == "__main__":
    main()
