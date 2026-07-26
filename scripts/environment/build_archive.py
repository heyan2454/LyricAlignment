#!/usr/bin/env python3
"""Build and independently verify a portable tracked-files project archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATED_MANIFEST = "ARCHIVE_MANIFEST.generated.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def tracked_files() -> list[Path]:
    names = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"], text=False).split(b"\0")
    paths = [ROOT / name.decode("utf-8") for name in names if name]
    # A stale generated manifest may already be tracked in an older checkout.
    # It is an archive output, never a source entry, and adding it here would
    # create two ZIP members with the same name when the fresh manifest below
    # is written.
    return [path for path in paths if path.relative_to(ROOT).as_posix() != GENERATED_MANIFEST]


def build(output: Path, root_name: str) -> dict:
    entries = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in tracked_files():
            relative = path.relative_to(ROOT).as_posix()
            payload = path.read_bytes()
            archive.writestr(f"{root_name}/{relative}", payload)
            entries.append({"path": relative, "size": len(payload), "sha256": sha256_bytes(payload)})
        manifest = {"schema_version": 1, "archive_root": root_name, "entries": entries}
        archive.writestr(f"{root_name}/{GENERATED_MANIFEST}", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return manifest


def verify(archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"archive contains duplicate member names: {duplicates[:10]}")
        manifests = [name for name in names if name.endswith(f"/{GENERATED_MANIFEST}")]
        if len(manifests) != 1:
            raise ValueError("archive must contain exactly one generated manifest")
        manifest = json.loads(archive.read(manifests[0]))
        root = str(manifest["archive_root"])
        expected_manifest_name = f"{root}/{GENERATED_MANIFEST}"
        if manifests[0] != expected_manifest_name:
            raise ValueError(
                f"generated manifest path disagrees with archive_root: {manifests[0]}"
            )
        if any(row.get("path") == GENERATED_MANIFEST for row in manifest["entries"]):
            raise ValueError("generated manifest must not list itself as a source entry")
        expected = {f"{root}/{row['path']}": row for row in manifest["entries"]}
        if len(expected) != len(manifest["entries"]):
            raise ValueError("generated manifest contains duplicate source paths")
        unexpected = sorted(set(names) - set(expected) - {expected_manifest_name})
        if unexpected:
            raise ValueError(f"archive contains unmanifested members: {unexpected[:10]}")
        for name, row in expected.items():
            info = archive.getinfo(name)
            payload = archive.read(name)
            if info.file_size != row["size"] or sha256_bytes(payload) != row["sha256"]:
                raise ValueError(f"archive entry mismatch: {name}")
        required = ("src/lyricalign/datasets/m4singer.py", "src/lyricalign/datasets/mir1k.py", "scripts/datasets/audit_m4singer.py")
        missing = [path for path in required if f"{root}/{path}" not in expected]
        if missing:
            raise ValueError(f"archive missing required project modules: {missing}")
        return {"status": "passed", "archive_root": root, "file_count": len(expected), "archive_sha256": sha256_bytes(archive_path.read_bytes())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root-name", default="LyricAlignment")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        build(args.output, args.root_name)
    print(json.dumps(verify(args.output), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
