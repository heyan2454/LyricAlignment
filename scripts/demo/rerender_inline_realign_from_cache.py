#!/usr/bin/env python3
"""Rebuild inline-realign visuals/videos from a frozen experiment cache.

This entry deliberately does not initialize the pipeline RunState, so a change
limited to visualization or rendering code can be applied to an old completed
experiment directory.  Scientific JSON/JSONL artifacts are hashed before and
after the refresh and the command fails if any of them changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.run_state import atomic_json, file_identity


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def scientific_files(root: Path) -> list[Path]:
    fixed = [
        root / "experiment_manifest.jsonl",
        root / "experiment_summary.json",
        root / "resolved_config.json",
        root / "pipeline_request.json",
    ]
    result = [path for path in fixed if path.is_file()]
    items = root / "items"
    if items.is_dir():
        for path in sorted(items.rglob("*")):
            if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
                continue
            relative = path.relative_to(items)
            if any(part in {"visuals", "renders", "render", "work"} for part in relative.parts):
                continue
            result.append(path)
    return sorted(set(path.resolve() for path in result))


def tree_identity(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    files = scientific_files(root)
    for path in files:
        relative = str(path.relative_to(root)).replace("\\", "/")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return {"file_count": len(files), "sha256": digest.hexdigest()}


def backup_render_state(root: Path, backup_root: Path) -> list[str]:
    copied: list[str] = []
    candidates = [
        root / "visualization_summary.json",
        root / "demo_render_summary.json",
        root / "render_complete.json",
        root / "state" / "visual_items",
        root / "state" / "video_page_items",
        root / "state" / "render_items",
        root / "state" / "stages" / "visualization.json",
        root / "state" / "stages" / "video_pages.json",
        root / "state" / "stages" / "render.json",
    ]
    for source in candidates:
        if not source.exists():
            continue
        relative = source.relative_to(root)
        destination = backup_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)
        copied.append(str(relative))
    return copied


def run(command: list[str], *, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"command": command, "log": str(log_path)}, ensure_ascii=False), flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        returncode = process.wait()
    if returncode != 0:
        raise RuntimeError(f"command failed rc={returncode}; see {log_path}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment-root", type=Path, required=True)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--profile", choices=("review", "final"), default="review")
    p.add_argument("--timeline-page-seconds", type=float, default=30.0)
    p.add_argument(
        "--comparison-branches",
        default="B0_60_fixed_official,B4_60_silence_official,C1_60_silence_compressed_diagnostic,B6_60_strict_silence_official",
    )
    p.add_argument("--skip-static", action="store_true")
    p.add_argument("--skip-video-pages", action="store_true")
    p.add_argument("--skip-encode", action="store_true")
    p.add_argument("--render-incomplete", action="store_true")
    p.add_argument("--no-backup-state", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    root = args.experiment_root.expanduser().resolve()
    manifest = (args.manifest or (root / "experiment_manifest.jsonl")).expanduser().resolve()
    required = [manifest, root / "experiment_summary.json", root / "resolved_config.json", root / "items"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"frozen experiment cache is incomplete: {missing}")

    stamp = utc_stamp()
    refresh_root = root / "render_refresh" / stamp
    refresh_root.mkdir(parents=True, exist_ok=False)
    before = tree_identity(root)
    backups = [] if args.no_backup_state else backup_render_state(root, refresh_root / "state_backup")
    commands: list[list[str]] = []

    if not args.skip_static:
        command = [
            args.python_bin, "scripts/demo/analyze_inline_realign_visuals.py",
            "--manifest", str(manifest), "--experiment-root", str(root),
            "--timeline-page-seconds", str(args.timeline_page_seconds),
            "--behavior-page-seconds", str(args.timeline_page_seconds),
            "--comparison-branches", args.comparison_branches,
            "--font", args.font, "--video-pages-mode", "off", "--force",
        ]
        commands.append(command)
        run(command, log_path=refresh_root / "01_static_visuals.log")

    if not args.skip_video_pages:
        command = [
            args.python_bin, "scripts/demo/analyze_inline_realign_visuals.py",
            "--manifest", str(manifest), "--experiment-root", str(root),
            "--timeline-page-seconds", str(args.timeline_page_seconds),
            "--behavior-page-seconds", str(args.timeline_page_seconds),
            "--comparison-branches", args.comparison_branches,
            "--font", args.font, "--video-pages-mode", "on",
            "--video-pages-only", "--force",
        ]
        commands.append(command)
        run(command, log_path=refresh_root / "02_video_pages.log")

    if not args.skip_encode:
        command = [
            args.python_bin, "scripts/demo/render_inline_realign_demo_batch.py",
            "--manifest", str(manifest), "--experiment-root", str(root),
            "--font", args.font, "--profile", args.profile,
            "--comparison-branches", args.comparison_branches, "--force",
        ]
        if args.render_incomplete:
            command.append("--render-incomplete")
        commands.append(command)
        run(command, log_path=refresh_root / "03_encode.log")

    after = tree_identity(root)
    if before != after:
        payload = {
            "status": "failed_scientific_cache_changed", "before": before, "after": after,
            "refresh_root": str(refresh_root), "commands": commands,
        }
        atomic_json(refresh_root / "rerender_complete.json", payload)
        raise RuntimeError(
            "scientific experiment artifacts changed during rerender; stop and inspect rerender_complete.json"
        )

    payload = {
        "schema_version": "inline_realign_cache_rerender_v1_scientific_guard",
        "status": "complete", "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment_root": str(root), "manifest": file_identity(manifest),
        "scientific_identity_before": before, "scientific_identity_after": after,
        "backed_up_state": backups, "commands": commands,
        "visualization_summary": file_identity(root / "visualization_summary.json"),
        "demo_render_summary": file_identity(root / "demo_render_summary.json"),
    }
    atomic_json(refresh_root / "rerender_complete.json", payload)
    atomic_json(root / "rerender_complete.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
