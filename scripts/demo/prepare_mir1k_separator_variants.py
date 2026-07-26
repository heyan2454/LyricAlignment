#!/usr/bin/env python3
"""Prepare Spleeter and Demucs vocal variants for a materialized MIR-1K subset.

The subset must be created by ``prepare_mir1k_demo_subset.py``.  Separator
outputs are cached by an explicit request identity and checked against silent
or near-copy failures before they are accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.spleeter_model import resolve_spleeter_model


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def command_prefix(explicit: str | None, executable: str, env_name: str) -> list[str]:
    if explicit:
        return shlex.split(explicit)
    if shutil.which(executable):
        return [executable]
    if shutil.which("conda"):
        return ["conda", "run", "-n", env_name, executable]
    raise RuntimeError(f"cannot find {executable}; provide --{executable}-command or install the environment")


def quality_check(mix: Path, vocals: Path, accompaniment: Path, report: Path) -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "demo" / "check_audio_separation.py"),
        "--mix", str(mix),
        "--vocals", str(vocals),
        "--accompaniment", str(accompaniment),
        "--report", str(report),
    ]
    subprocess.run(command, check=True)


def prepare_spleeter(item_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    audio = item_root / "audio"
    mix = audio / "mix.wav"
    vocals = audio / "spleeter_vocals.wav"
    accompaniment = audio / "spleeter_accompaniment.wav"
    identity = audio / "spleeter.identity.json"
    quality = audio / "spleeter.quality.json"
    model = resolve_spleeter_model(args.spleeter_model_root, args.spleeter_model_name)
    request = {
        "schema_version": "mir1k_separator_variant_spleeter_v1",
        "mix_sha256": sha256(mix),
        "model_name": args.spleeter_model_name,
        "model_identity": model.as_dict(),
        "quality_policy": "reject_silent_or_near_copy_v1",
    }
    request_hash = canonical_hash(request)
    if not args.force and all(path.is_file() for path in (vocals, accompaniment, identity, quality)):
        cached = json.loads(identity.read_text(encoding="utf-8"))
        checked = json.loads(quality.read_text(encoding="utf-8"))
        if cached.get("request_hash") == request_hash and checked.get("passed") is True:
            return {"separator": "spleeter", "status": "cached", "identity": str(identity)}

    stage = audio / ".spleeter_variant_stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    command = command_prefix(args.spleeter_command, "spleeter", args.spleeter_env) + [
        "separate", "-p", f"spleeter:{args.spleeter_model_name}", "-o", str(stage), str(mix)
    ]
    environment = os.environ.copy()
    environment["MODEL_PATH"] = str(model.model_root)
    subprocess.run(command, check=True, env=environment)
    generated = stage / mix.stem
    shutil.copy2(generated / "vocals.wav", vocals)
    shutil.copy2(generated / "accompaniment.wav", accompaniment)
    quality_check(mix, vocals, accompaniment, quality)
    atomic_json(identity, {
        **request,
        "request_hash": request_hash,
        "command": command,
        "vocals_sha256": sha256(vocals),
        "accompaniment_sha256": sha256(accompaniment),
        "quality_sha256": sha256(quality),
    })
    shutil.rmtree(stage, ignore_errors=True)
    return {"separator": "spleeter", "status": "prepared", "identity": str(identity)}


def prepare_demucs(item_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    audio = item_root / "audio"
    mix = audio / "mix.wav"
    tag = f"demucs_{args.demucs_model}"
    vocals = audio / f"{tag}_vocals.wav"
    accompaniment = audio / f"{tag}_accompaniment.wav"
    identity = audio / f"{tag}.identity.json"
    quality = audio / f"{tag}.quality.json"
    request = {
        "schema_version": "mir1k_separator_variant_demucs_v1",
        "mix_sha256": sha256(mix),
        "package_version_requested": args.demucs_version,
        "model_name": args.demucs_model,
        "device": args.demucs_device,
        "shifts": args.demucs_shifts,
        "overlap": args.demucs_overlap,
        "segment_sec": args.demucs_segment,
        "jobs": args.demucs_jobs,
        "clip_mode": args.demucs_clip_mode,
        "two_stems": "vocals",
        "other_method": "add",
        "torch_home": str(args.demucs_torch_home.resolve()) if args.demucs_torch_home else None,
        "quality_policy": "reject_silent_or_near_copy_v1",
    }
    request_hash = canonical_hash(request)
    if not args.force and all(path.is_file() for path in (vocals, accompaniment, identity, quality)):
        cached = json.loads(identity.read_text(encoding="utf-8"))
        checked = json.loads(quality.read_text(encoding="utf-8"))
        if cached.get("request_hash") == request_hash and checked.get("passed") is True:
            return {"separator": "demucs", "status": "cached", "identity": str(identity)}

    stage = audio / ".demucs_variant_stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    command = command_prefix(args.demucs_command, "demucs", args.demucs_env) + [
        "-n", args.demucs_model,
        "--two-stems", "vocals",
        "--other-method", "add",
        "--out", str(stage),
        "--device", args.demucs_device,
        "--shifts", str(args.demucs_shifts),
        "--overlap", str(args.demucs_overlap),
        "--jobs", str(args.demucs_jobs),
        "--clip-mode", args.demucs_clip_mode,
    ]
    if args.demucs_segment is not None:
        command += ["--segment", str(args.demucs_segment)]
    command.append(str(mix))
    environment = os.environ.copy()
    if args.demucs_torch_home:
        args.demucs_torch_home.mkdir(parents=True, exist_ok=True)
        environment["TORCH_HOME"] = str(args.demucs_torch_home)
    subprocess.run(command, check=True, env=environment)
    generated = stage / args.demucs_model / mix.stem
    shutil.copy2(generated / "vocals.wav", vocals)
    shutil.copy2(generated / "no_vocals.wav", accompaniment)
    quality_check(mix, vocals, accompaniment, quality)
    atomic_json(identity, {
        **request,
        "request_hash": request_hash,
        "command": command,
        "vocals_sha256": sha256(vocals),
        "accompaniment_sha256": sha256(accompaniment),
        "quality_sha256": sha256(quality),
    })
    shutil.rmtree(stage, ignore_errors=True)
    return {"separator": "demucs", "status": "prepared", "identity": str(identity)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset-root", type=Path, required=True)
    parser.add_argument("--roles", nargs="+", choices=("development", "heldout"), default=["development"])
    parser.add_argument("--separators", nargs="+", choices=("spleeter", "demucs"), default=["spleeter", "demucs"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--spleeter-model-root", type=Path, default=Path.home() / ".cache" / "spleeter_models")
    parser.add_argument("--spleeter-model-name", default="2stems")
    parser.add_argument("--spleeter-env", default="spleeter")
    parser.add_argument("--spleeter-command")
    parser.add_argument("--demucs-version", default="4.1.0")
    parser.add_argument("--demucs-model", default="htdemucs_ft")
    parser.add_argument("--demucs-env", default="demucs")
    parser.add_argument("--demucs-command")
    parser.add_argument("--demucs-device", default="cuda")
    parser.add_argument("--demucs-shifts", type=int, default=0)
    parser.add_argument("--demucs-overlap", type=float, default=0.25)
    parser.add_argument("--demucs-segment", type=int)
    parser.add_argument("--demucs-jobs", type=int, default=0)
    parser.add_argument("--demucs-clip-mode", choices=("rescale", "clamp"), default="rescale")
    parser.add_argument("--demucs-torch-home", type=Path)
    args = parser.parse_args()

    selection = read_jsonl(args.subset_root / "selection.jsonl")
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in selection:
        if row["selection_role"] not in args.roles:
            continue
        item_root = args.subset_root / "items" / str(row["item_id"])
        for separator in args.separators:
            try:
                result = prepare_spleeter(item_root, args) if separator == "spleeter" else prepare_demucs(item_root, args)
                records.append({"item_id": row["item_id"], "role": row["selection_role"], **result})
                print(json.dumps(records[-1], ensure_ascii=False), flush=True)
            except Exception as exc:
                failure = {"item_id": row["item_id"], "role": row["selection_role"], "separator": separator, "error": repr(exc)}
                failures.append(failure)
                print(json.dumps(failure, ensure_ascii=False), file=sys.stderr, flush=True)
                if not args.continue_on_error:
                    raise
    summary = {
        "schema_version": "mir1k_separator_variants_summary_v1",
        "roles": args.roles,
        "separators": args.separators,
        "completed": records,
        "failures": failures,
    }
    atomic_json(args.subset_root / "separator_variants.summary.json", summary)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
