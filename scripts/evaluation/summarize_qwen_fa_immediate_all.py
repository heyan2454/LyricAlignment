#!/usr/bin/env python3
"""Create a compact index for the complete immediate Qwen FA diagnostic run."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    expected = {
        "selection": args.input_root / "selection.json",
        "timestamp_coverage": args.input_root / "timestamp_coverage.json",
        "core_summary": args.input_root / "core" / "final_summary.json",
        "extended_summary": args.input_root / "extended" / "final_summary.json",
        "cliff240_summary": args.input_root / "cliff240" / "final_summary.json",
        "error_blocks": args.input_root / "error_blocks.json",
    }
    files: dict[str, Any] = {}
    for name, path in expected.items():
        files[name] = {
            "path": str(path),
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": sha256(path) if path.is_file() else None,
        }
    task_dirs: list[dict[str, Any]] = []
    for path in sorted(args.input_root.rglob("identity.json")):
        if "derived_audio" in path.parts:
            continue
        identity = read_json(path)
        task_dirs.append(
            {
                "directory": str(path.parent),
                "model_name": identity.get("model_name"),
                "experiment": identity.get("experiment"),
                "checkpoint_kind": identity.get("checkpoint_kind"),
                "variant_count": identity.get("variant_count"),
                "character_row_count": identity.get("character_row_count"),
                "identity_sha256": sha256(path),
            }
        )
    payload = {
        "schema_version": "qwen_fa_immediate_all_summary_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(args.input_root),
        "files": files,
        "completed_task_count": len(task_dirs),
        "tasks": task_dirs,
        "scope": {
            "immediate": [
                "timestamp coverage",
                "b180 raw/fixed, seam and mask audit",
                "MIR-1K natural-long audit",
                "multi-sample absolute-time shift sweep",
                "expanded full-vs-crop consistency",
                "240-second dense cliff and equal-total A/B controls",
                "A+silence+A versus A+silence+B repetition controls",
                "raw backward-jump and repair-block summaries",
            ],
            "excluded": [
                "new model training",
                "LoRA scale or layer ablations",
                "hard/crossfade join augmentation sweep",
                "near-homophone data augmentation",
            ],
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({"out": str(args.out), "task_count": len(task_dirs)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
