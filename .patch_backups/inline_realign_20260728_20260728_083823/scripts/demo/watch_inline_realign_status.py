#!/usr/bin/env python3
"""Continuously display compact live status for an inline-realign run."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    except (OSError, json.JSONDecodeError):
        return []


def human_bytes(value: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            pass
    return total


def render(root: Path) -> str:
    manifest = read_jsonl(root / "experiment_manifest.jsonl")
    manifest_ids = {str(row.get("item_id")) for row in manifest}
    live = read_json(root / "live_status.json")
    experiment_live = read_json(root / "experiment_live_status.json")
    experiment = read_json(root / "experiment_summary.json")
    visuals = read_json(root / "visualization_summary.json")
    renders = read_json(root / "demo_render_summary.json")
    status_rows = read_jsonl(root / "run_status.jsonl")
    complete_ids = {
        str(row.get("item_id")) for row in status_rows
        if row.get("status") == "complete" and str(row.get("item_id")) in manifest_ids
    }
    failed_ids = {
        str(row.get("item_id")) for row in status_rows
        if row.get("status") == "failed" and str(row.get("item_id")) in manifest_ids
    }
    stage = live.get("stage") or "not started"
    stage_state = live.get("status") or "unknown"
    item = experiment_live.get("item_id") or "—"
    branch = experiment_live.get("branch") or "—"
    current = experiment_live.get("item_ordinal")
    total = experiment_live.get("manifest_item_count") or len(manifest)
    lines = [
        f"Inline realign status | {datetime.now().isoformat(timespec='seconds')}",
        f"root: {root}",
        f"pipeline: {stage_state} | stage: {stage}",
        f"experiment item: {current or '—'}/{total or '—'} | {item} | branch: {branch}",
        f"items complete/failed/manifest: {len(complete_ids)}/{len(failed_ids)}/{len(manifest_ids)}",
        f"experiment summary complete/failed: {experiment.get('completed_item_count', '—')}/{experiment.get('failed_item_count', '—')}",
        f"visuals complete/failed: {visuals.get('completed_item_count', '—')}/{visuals.get('failed_item_count', '—')}",
        f"demo comparison videos complete/failed: {renders.get('completed_item_count', '—')}/{renders.get('failed_item_count', '—')}",
        f"output size: {human_bytes(directory_size(root))}",
    ]
    failure = live.get("message") or experiment_live.get("message")
    if failure:
        lines.append(f"message: {failure}")
    log = root / "logs" / f"{stage}.log"
    if log.is_file():
        try:
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-6:]
            if tail:
                lines.extend(["", f"tail: {log.name}", *tail])
        except OSError:
            pass
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_root", type=Path)
    parser.add_argument("--refresh-seconds", type=float, default=3.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-clear", action="store_true")
    args = parser.parse_args()
    root = args.experiment_root.expanduser().resolve()
    while True:
        if not args.no_clear and not args.once:
            os.system("cls" if os.name == "nt" else "clear")
        print(render(root), flush=True)
        if args.once:
            return 0
        time.sleep(max(0.5, args.refresh_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
