#!/usr/bin/env python3
"""Emit a compact machine-readable external-asset inventory."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def describe(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists() or path.is_symlink(),
        "is_symlink": path.is_symlink(),
        "symlink_target": str(path.resolve(strict=False)) if path.is_symlink() else None,
        "kind": "missing",
        "file_count": 0,
        "size_bytes": 0,
        "errors": [],
    }
    if not result["exists"]:
        return result
    try:
        if path.is_file():
            result.update(kind="file", file_count=1, size_bytes=path.stat().st_size)
            return result
        if path.is_dir():
            result["kind"] = "directory"
            for candidate in path.rglob("*"):
                try:
                    if candidate.is_file():
                        result["file_count"] += 1
                        result["size_bytes"] += candidate.stat().st_size
                except OSError as exc:
                    result["errors"].append(f"{candidate}: {type(exc).__name__}: {exc}")
            return result
        result["kind"] = "other"
    except OSError as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", action="append", nargs=2, metavar=("NAME", "PATH"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Return zero even when one or more requested assets are missing.",
    )
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = {name: describe(Path(path).expanduser()) for name, path in args.asset}
    result["filesystem"] = {
        "output_parent": str(args.out.parent),
        "free_bytes": shutil.disk_usage(args.out.parent).free,
    }
    temporary = args.out.with_name(args.out.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(args.out)

    missing = [name for name, value in result.items() if name != "filesystem" and not value["exists"]]
    if missing and not args.allow_missing:
        raise SystemExit(f"Missing required assets: {', '.join(missing)}")


if __name__ == "__main__":
    main()
