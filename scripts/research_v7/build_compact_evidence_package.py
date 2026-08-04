#!/usr/bin/env python3
"""Build a <=5 MB research-v7 handoff package without media, models, or raw items."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def copy(source: Path, staging: Path, target: Path, inventory: list[dict]) -> None:
    destination = staging / target
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    inventory.append({"archive_path": str(target), "source_path": str(source), "sha256": digest(source), "bytes": source.stat().st_size})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--human-review", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024)
    args = parser.parse_args()
    repo, run_root, human_review = args.repo.resolve(), args.run_root.resolve(), args.human_review.resolve()
    exclude_roots = {"evidence_packages", "m4singer_test_all839_baseline_20260804"}
    with tempfile.TemporaryDirectory(prefix="research_v7_compact_") as temporary:
        staging = Path(temporary) / "research_v7_compact_evidence_20260804"
        inventory: list[dict] = []
        for source in sorted((repo / "docs/research_v7_align_behavior").glob("*.md")):
            copy(source, staging, Path("reports") / source.name, inventory)
        for name in ("AGENTS.md", "pyproject.toml", "RESEARCH_V7_DISCUSSION_PATCH_MANIFEST.json"):
            source = repo / name
            if source.is_file(): copy(source, staging, Path("repository_identity") / name, inventory)
        copy(args.environment.resolve(), staging, Path("repository_identity") / "environment.json", inventory)
        for command, name in ((["git", "rev-parse", "HEAD"], "git_head.txt"),
                              (["git", "status", "--short", "--branch"], "git_status.txt"),
                              (["git", "diff", "--binary"], "working_tree.patch"),
                              (["git", "ls-files", "--others", "--exclude-standard"], "untracked_files.txt")):
            output = subprocess.check_output(command, cwd=repo, text=True)
            source = staging / "repository_identity" / name
            source.parent.mkdir(parents=True, exist_ok=True); source.write_text(output, encoding="utf-8")
            inventory.append({"archive_path": str(source.relative_to(staging)), "source_path": "generated:" + " ".join(command), "sha256": digest(source), "bytes": source.stat().st_size})
        for source in sorted(run_root.glob("research_v7_provenance_index_20260804_v9.json")):
            copy(source, staging, Path("provenance") / source.name, inventory)
        for run in sorted(path for path in run_root.iterdir() if path.is_dir() and path.name not in exclude_roots):
            for source in sorted(path for path in run.iterdir() if path.is_file() and source_suffix(path)):
                copy(source, staging, Path("automatic_runs") / run.name / source.name, inventory)
        for source in sorted(path for path in human_review.rglob("*") if path.is_file()):
            copy(source, staging, Path("human_review") / source.relative_to(human_review), inventory)
        excluded = {
            "per_request_evidence": "all run `items/` trees; their identities and SHA256 are in collection.json/provenance index",
            "media": "audio, review MP4, ASS, rendered alignment intermediates",
            "models": "base-model cache and LoRA weights; exact identities are retained in manifests/environment",
            "incomplete_all839_baseline": "excluded because its queued run is not completed evidence",
        }
        manifest = {"schema": "research_v7/compact_handoff_v1", "included_file_count": len(inventory),
                    "excluded": excluded, "files": inventory}
        manifest_path = staging / "EVIDENCE_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        readme = staging / "README.md"
        readme.write_text("""# Compact research-v7 evidence handoff\n\nThis package contains reports, formal run manifests/freeze/collection/analysis metadata, provenance index, reproducibility identity, and normalized human review evidence. It intentionally excludes media, model weights, and per-request evidence trees to remain small; their paths and SHA256 identities remain in the included collection/provenance files.\n\n`human_review/experimenter_decoded_annotations.json` reveals mutation identities and must not be shared with blinded reviewers.\n""", encoding="utf-8")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary_archive = args.out.with_suffix(args.out.suffix + ".tmp")
        with tarfile.open(temporary_archive, "w:gz") as archive:
            archive.add(staging, arcname=staging.name)
        size = temporary_archive.stat().st_size
        if size > args.max_bytes:
            temporary_archive.unlink()
            raise RuntimeError(f"package is {size} bytes, over cap {args.max_bytes}")
        temporary_archive.replace(args.out)
    print(json.dumps({"status": "complete", "archive": str(args.out), "bytes": args.out.stat().st_size,
                      "included_files": len(inventory), "sha256": digest(args.out)}, ensure_ascii=False))
    return 0


def source_suffix(path: Path) -> bool:
    return path.suffix in {".json", ".jsonl", ".md", ".txt"}


if __name__ == "__main__":
    raise SystemExit(main())
