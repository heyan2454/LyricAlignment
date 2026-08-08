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


_IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    ".cache",
    ".patch_backups",
    ".repair_backups",
}
_IGNORED_ROOT_DIRECTORY_NAMES = {
    "external_data",
    "datasets",
    "models",
    "checkpoints",
    "outputs",
    "wandb",
    "夜苏打",
}
_IGNORED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".wav",
    ".mp3",
    ".mp4",
    ".m4a",
    ".flac",
    ".ckpt",
    ".safetensors",
    ".pt",
    ".pth",
    ".zip",
    ".tar",
    ".gz",
}
_IGNORED_EXACT_RELATIVE_PATHS = {
    GENERATED_MANIFEST,
    "local_paths.yaml",
    "configs/paths/local_paths.yaml",
    "configs/assets/assets.local.yaml",
    "configs/assets/smoke_samples.local.yaml",
    "docs_sessions_patch_notes_20260729_timeline_render.md",
    "PATCH_README_20260728_CONTROL_VISUAL_COLLECTION_FIX.md",
    "PATCH_README_20260803_RESEARCH_V7_ALIGN_BEHAVIOR.md",
    "PATCH_README_20260804_LONG_SLOT_REGION_ASSESSOR_ARCHIVE.md",
    "PATCH_README_20260805_DETECTOR_V2.md",
    "PATCH_README_20260807_TRANSITION_RECOVERY_DETECTOR.md",
    "PATCH_README_mir1k_import_fix.md",
    "APPLY_LONG_SLOT_REGION_ASSESSOR_ARCHIVE_PATCH.sh",
    "APPLY_RESEARCH_V7_DISCUSSION_PATCH.sh",
    "APPLY_TRANSITION_RECOVERY_DETECTOR_20260807.sh",
    "RESEARCH_V6_PACKAGE_MANIFEST.json",
    "RESEARCH_V7_DISCUSSION_PATCH_MANIFEST.json",
    "RESEARCH_V7_LONG_SLOT_REGION_ASSESSOR_ARCHIVE.patch",
    "RESEARCH_V7_LONG_SLOT_REGION_ASSESSOR_PATCH_MANIFEST.json",
    "TRANSITION_RECOVERY_DETECTOR_20260807.patch",
    "TRANSITION_RECOVERY_DETECTOR_20260807_PATCH_MANIFEST.json",
    "ARCHIVE_MANIFEST.generated.json",
}


def _filesystem_source_files(excluded_root_names: set[str] | None = None) -> list[Path]:
    """Fallback for portable source snapshots without a .git directory.

    The fallback intentionally mirrors the repository's tracked-source policy:
    source/config/docs/tests and lightweight evidence are included, while
    caches, local paths, media, model artifacts and generated archives are not.
    """

    excluded_root_names = _IGNORED_ROOT_DIRECTORY_NAMES | (excluded_root_names or set())
    paths: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        relative_posix = relative.as_posix()
        if relative_posix in _IGNORED_EXACT_RELATIVE_PATHS:
            continue
        if relative.parts and relative.parts[0] in excluded_root_names:
            continue
        if any(part in _IGNORED_DIRECTORY_NAMES or part.endswith(".egg-info") for part in relative.parts[:-1]):
            continue
        if path.name.endswith(".bak_prearchive"):
            continue
        if path.suffix.lower() in _IGNORED_SUFFIXES:
            continue
        if relative.parts[:2] in {("runs", "raw_audio"), ("runs", "large_outputs")}:
            continue
        if "raw_audio" in relative.parts or "large_outputs" in relative.parts:
            continue
        paths.append(path)
    return sorted(paths, key=lambda value: value.relative_to(ROOT).as_posix())


def tracked_files(excluded_root_names: set[str] | None = None) -> list[Path]:
    excluded_root_names = excluded_root_names or set()
    try:
        names = subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            text=False,
            stderr=subprocess.DEVNULL,
        ).split(b"\0")
    except (FileNotFoundError, subprocess.CalledProcessError):
        return _filesystem_source_files(excluded_root_names)
    paths = [ROOT / name.decode("utf-8") for name in names if name]
    # A stale generated manifest may already be tracked in an older checkout.
    # It is an archive output, never a source entry, and adding it here would
    # create two ZIP members with the same name when the fresh manifest below
    # is written.
    def _excluded(relative_posix: str) -> bool:
        if relative_posix in _IGNORED_EXACT_RELATIVE_PATHS:
            return True
        for rule in excluded_root_names:
            if rule in (".", ""):
                continue
            if relative_posix == rule or relative_posix.startswith(rule.rstrip("/") + "/"):
                return True
        return False

    return [
        path for path in paths
        if path.relative_to(ROOT).as_posix() != GENERATED_MANIFEST
        and not _excluded(path.relative_to(ROOT).as_posix())
    ]


def build(output: Path, root_name: str, excluded_root_names: set[str] | None = None) -> dict:
    entries = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in tracked_files(excluded_root_names):
            relative = path.relative_to(ROOT).as_posix()
            # Tracked symlinks may point at directories on a larger data disk
            # (e.g. session cache dirs); they are not portable archive content.
            # is_file() also covers files deleted from disk but still tracked.
            if path.is_symlink() or not path.is_file():
                continue
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
    parser.add_argument("--exclude-root", action="append", default=[],
                        help="top-level project directory to omit; may be repeated")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        build(args.output, args.root_name, set(args.exclude_root))
    print(json.dumps(verify(args.output), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
