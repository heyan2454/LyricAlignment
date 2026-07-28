#!/usr/bin/env python3
"""Publish lightweight Demo result views beside songs or under one directory.

Canonical experiment artifacts remain under ``<experiment-root>/items``.  This
script creates only symlinks plus a tiny manifest, so choosing an adjacent view
does not duplicate alignment JSON or rendered video files.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_component(value: Any) -> str:
    text = str(value).strip().replace("/", "_").replace("\\", "_")
    text = "".join(character if character.isalnum() or character in "-_. " else "_" for character in text)
    return text.strip(" ._") or "item"


def link_file(source: Path, target: Path, *, force: bool) -> str:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        if target.is_symlink() and target.resolve() == source:
            return "reused_symlink"
        if not force:
            raise FileExistsError(f"publish target already exists: {target}")
        target.unlink()
    relative = os.path.relpath(source, target.parent.resolve())
    target.symlink_to(relative)
    return "created_symlink"


def target_root(item: dict[str, Any], *, layout: str, publish_root: Path | None) -> Path:
    language = safe_component(item.get("language", "Unknown"))
    stem = safe_component(item.get("demo_source_stem") or item.get("item_id"))
    if layout == "adjacent":
        source_dir = Path(item.get("demo_source_directory") or Path(item["source_media_path"]).parent).resolve()
        return source_dir / f"{stem}_inline_realign"
    if layout == "directory":
        if publish_root is None:
            raise ValueError("--publish-root is required for --layout directory")
        return publish_root.resolve() / language / stem
    raise ValueError(f"unsupported publish layout: {layout}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--experiment-root", type=Path, required=True)
    p.add_argument("--layout", choices=("adjacent", "directory"), required=True)
    p.add_argument("--publish-root", type=Path)
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    manifest = args.manifest.expanduser().resolve()
    root = args.experiment_root.expanduser().resolve()
    if not (root / "experiment_summary.json").is_file():
        raise FileNotFoundError(f"alignment stage incomplete: {root / 'experiment_summary.json'}")
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in read_jsonl(manifest):
        if str(item.get("dataset")) != "demo":
            continue
        item_id = str(item["item_id"])
        canonical = root / "items" / item_id
        destination = target_root(item, layout=args.layout, publish_root=args.publish_root)
        try:
            links: dict[str, str] = {}
            sources = {
                "alignment.json": canonical / "branches" / "B2_30_silence_official" / "alignment.json",
                "official.mp4": canonical / "render" / "official.mp4",
                "item_summary.json": canonical / "item_summary.json",
                "inline_realign_shadow.json": canonical / "inline_realign_shadow.json",
            }
            for name, source in sources.items():
                if source.is_file():
                    links[name] = link_file(source, destination / name, force=args.force)
            incomplete = canonical / "automatic_incomplete_shadow" / "alignment.json"
            if incomplete.is_file():
                links["automatic_incomplete_shadow.json"] = link_file(
                    incomplete, destination / "automatic_incomplete_shadow.json", force=args.force
                )
            publish_manifest = {
                "schema_version": "inline_realign_demo_publish_view_v1",
                "item_id": item_id,
                "language": item.get("language"),
                "layout": args.layout,
                "canonical_item_root": str(canonical.resolve()),
                "source_media_path": item.get("source_media_path"),
                "links": links,
                "contains_duplicate_large_files": False,
            }
            atomic_json(destination / "publish_manifest.json", publish_manifest)
            rows.append({"item_id": item_id, "destination": str(destination), "links": links})
        except Exception as exc:
            failures.append({
                "item_id": item_id,
                "destination": str(destination),
                "error": f"{type(exc).__name__}: {exc}",
            })
    summary = {
        "schema_version": "inline_realign_demo_publish_summary_v1",
        "layout": args.layout,
        "publish_root": None if args.publish_root is None else str(args.publish_root.expanduser().resolve()),
        "published_count": len(rows),
        "failed_count": len(failures),
        "large_files_are_links": True,
        "results": rows,
        "failures": failures,
    }
    atomic_json(root / "demo_publish_summary.json", summary)
    print(json.dumps({
        "status": "complete" if not failures else "partial_failure",
        "published_count": len(rows), "failed_count": len(failures),
        "summary": str(root / "demo_publish_summary.json"),
    }, ensure_ascii=False), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
