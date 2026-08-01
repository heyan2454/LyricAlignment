#!/usr/bin/env python3
"""Collect full and deterministic <=3 MiB research evidence archives."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
from typing import Any, Iterable

EXCLUDED_SUFFIXES = {".wav", ".mp3", ".flac", ".mp4", ".mkv", ".pt", ".pth", ".safetensors", ".gz", ".tar", ".zip"}
EXCLUDED_PARTS = {"__pycache__", ".git", "model_cache", "hf_cache"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def eligible(root: Path) -> list[Path]:
    result = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        result.append(path)
    return sorted(result, key=lambda path: str(path.relative_to(root)))


def priority(path: Path, root: Path) -> tuple[int, int, str]:
    rel = str(path.relative_to(root))
    name = path.name
    if name in {"complete.json", "research_summary.json", "frozen_parameters.json", "run_status.jsonl"}:
        rank = 0
    elif name == "item_summary.json":
        rank = 1
    elif name.startswith("E0_") or name.startswith("E1_"):
        rank = 2
    elif name.startswith("E7_") or name.startswith("E8_"):
        rank = 3
    elif path.suffix in {".md", ".yaml", ".yml"}:
        rank = 4
    elif "experimental_alignments" in path.parts:
        rank = 8
    else:
        rank = 6
    return rank, path.stat().st_size, rel


def select_light(files: list[Path], root: Path, max_uncompressed_bytes: int) -> list[Path]:
    selected: list[Path] = []
    total = 0
    # Keep every item summary when possible, then use remaining budget for
    # detailed evidence. This preserves full-data population visibility.
    ordered = sorted(files, key=lambda path: priority(path, root))
    for path in ordered:
        size = path.stat().st_size
        if size > max_uncompressed_bytes:
            continue
        if total + size <= max_uncompressed_bytes:
            selected.append(path)
            total += size
    return selected


def build_archive(root: Path, output: Path, files: Iterable[Path], profile: str) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    selected = list(files)
    manifest = {
        "schema_version": "alignment_research_evidence_manifest_v1",
        "profile": profile,
        "source_root": str(root),
        "file_count": len(selected),
        "files": [
            {
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in selected
        ],
    }
    with tempfile.TemporaryDirectory() as temporary:
        manifest_path = Path(temporary) / "EVIDENCE_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with tarfile.open(output, "w:gz", compresslevel=9) as archive:
            archive.add(manifest_path, arcname="EVIDENCE_MANIFEST.json", recursive=False)
            for path in selected:
                archive.add(path, arcname=str(Path(root.name) / path.relative_to(root)), recursive=False)
    manifest["archive_path"] = str(output)
    manifest["archive_size"] = output.stat().st_size
    manifest["archive_sha256"] = sha256(output)
    return manifest


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--profile", choices=("full", "light3m"), required=True)
    p.add_argument("--max-bytes", type=int, default=3 * 1024 * 1024)
    return p


def main() -> int:
    args = parser().parse_args()
    root = args.run_root.expanduser().resolve()
    files = eligible(root)
    if args.profile == "light3m":
        # A conservative uncompressed budget leaves room for tar headers and
        # files that compress poorly.  Verify and retry with a smaller budget.
        budget = min(args.max_bytes - 64 * 1024, int(args.max_bytes * 0.90))
        while True:
            selected = select_light(files, root, max(0, budget))
            manifest = build_archive(root, args.output.resolve(), selected, args.profile)
            if manifest["archive_size"] <= args.max_bytes or budget <= 128 * 1024:
                break
            budget = int(budget * 0.80)
        if manifest["archive_size"] > args.max_bytes:
            raise RuntimeError(f"unable to satisfy light archive cap: {manifest['archive_size']} > {args.max_bytes}")
    else:
        manifest = build_archive(root, args.output.resolve(), files, args.profile)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
