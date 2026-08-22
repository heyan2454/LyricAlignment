#!/usr/bin/env python3
"""Freeze a CPU-only baseline identity for Evaluation V1.

This does not run any model forward. It records the repository commit, working
tree status, default model/checkpoint paths from inline_realign_env.sh, and
basic environment facts so later diagnostic/regression runs can be traced.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_ROOT = Path("/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_baseline_identity")


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    return result.stdout.strip()


def parse_env_defaults(path: Path) -> dict[str, str]:
    """Extract `NAME="${NAME:-value}"` defaults from a shell env script."""
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r'^([A-Z][A-Z0-9_]*)=["\']?\$\{?\1:-(.*?)\}?["\']?$', re.MULTILINE)
    for match in pattern.finditer(text):
        name, value = match.group(1), match.group(2).strip().strip('"').strip("'")
        out[name] = value
    return out


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()

    env_path = args.repo_root / "scripts/demo/inline_realign_env.sh"
    env_defaults = parse_env_defaults(env_path) if env_path.exists() else {}

    git_commit = run(["git", "rev-parse", "HEAD"], cwd=args.repo_root)
    git_short = run(["git", "rev-parse", "--short", "HEAD"], cwd=args.repo_root)
    git_status = run(["git", "status", "--short"], cwd=args.repo_root)
    git_branch = run(["git", "branch", "--show-current"], cwd=args.repo_root)
    model_source_default = env_defaults.get("MODEL_SOURCE", "")
    # If MODEL_SOURCE default is empty, try the resolved path from the env script via bash.
    if not model_source_default:
        try:
            resolved = subprocess.run(
                ["bash", "-c", f"source {env_path} >/dev/null 2>&1; resolve_model_source || true"],
                cwd=args.repo_root, text=True, capture_output=True, timeout=10,
            ).stdout.strip().splitlines()
            if resolved:
                model_source_default = resolved[-1]
        except Exception:
            pass

    identity = {
        "schema_version": "evaluation_v1_baseline_identity_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(args.repo_root),
        "git": {
            "commit": git_commit,
            "short": git_short,
            "branch": git_branch,
            "status_short": git_status,
            "dirty": bool(git_status),
        },
        "env_defaults": env_defaults,
        "resolved_model_source": model_source_default,
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
        },
        "status": "baseline_identity_frozen_cpu_only",
    }
    out_root = args.out_root
    out_root.mkdir(parents=True, exist_ok=True)
    report_path = out_root / "baseline_identity.json"
    atomic_json(report_path, identity)
    cleanup = [
        "# Cleanup Report — Evaluation V1 Baseline Identity",
        "",
        "This batch writes one small JSON file; no model forward is executed.",
        "",
        f"File: `{report_path.relative_to(out_root)}` ({report_path.stat().st_size} bytes)",
        "",
        "Recreate with:",
        "",
        f"```bash\npython scripts/evaluation/freeze_baseline_identity.py --out-root {out_root}\n```",
        "",
        f"Delete with:\n\n```bash\nrm -rf {out_root}\n```",
        "",
    ]
    (out_root / "cleanup_report.md").write_text("\n".join(cleanup), encoding="utf-8")
    print(json.dumps(identity, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
