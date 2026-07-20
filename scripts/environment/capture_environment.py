#!/usr/bin/env python3
"""Capture a compact reproducibility snapshot for the active environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGES = ("torch", "transformers", "huggingface_hub", "numpy", "PyYAML", "soundfile")


def command_output(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def distribution_info(name: str) -> dict[str, Any]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return {"installed": False}
    info: dict[str, Any] = {"installed": True, "version": distribution.version}
    direct_url = distribution.read_text("direct_url.json")
    if direct_url:
        try:
            info["direct_url"] = json.loads(direct_url)
        except json.JSONDecodeError:
            info["direct_url_raw"] = direct_url
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "python": {"version": sys.version, "executable": sys.executable},
        "platform": platform.platform(),
        "packages": {name: distribution_info(name) for name in PACKAGES},
        "commands": {
            "ffmpeg": (command_output(["ffmpeg", "-version"]) or "").splitlines()[:1],
            "nvidia_smi": command_output(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
        },
    }
    try:
        import torch

        result["torch_runtime"] = {
            "version": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        }
    except Exception as exc:
        result["torch_runtime_error"] = f"{type(exc).__name__}: {exc}"

    temporary = args.out.with_name(args.out.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(args.out)


if __name__ == "__main__":
    main()
