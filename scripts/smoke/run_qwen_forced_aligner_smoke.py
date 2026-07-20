#!/usr/bin/env python3
"""Run resumable, metric-free Qwen forced-alignment smoke samples."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.inference.qwen_forced_aligner import QwenForcedAligner

SCHEMA_VERSION = 2


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_alignment(
    items: list[dict[str, Any]],
    audio_duration: float,
    *,
    expected_item_count: int | None = None,
) -> dict[str, Any]:
    """Separate ordering errors from valid-but-noteworthy overlaps and gaps."""

    warning_counts: dict[str, int] = {}
    overlap_values: list[float] = []
    gap_values: list[float] = []
    previous_start: float | None = None
    previous_end: float | None = None

    def warn(name: str) -> None:
        warning_counts[name] = warning_counts.get(name, 0) + 1

    for item in items:
        start = item.get("start_time")
        end = item.get("end_time")
        if not _finite_number(start) or not _finite_number(end):
            warn("non_finite_timestamp")
            continue
        start = float(start)
        end = float(end)
        if start > end:
            warn("negative_duration")
        if start < -0.25:
            warn("start_before_audio")
        if end > audio_duration + 0.5:
            warn("end_after_audio")
        if previous_start is not None and start < previous_start:
            warn("start_time_decreased")
        if previous_end is not None:
            if end < previous_end:
                warn("end_time_decreased")
            if start < previous_end:
                overlap_values.append(previous_end - start)
            elif start > previous_end:
                gap_values.append(start - previous_end)
        previous_start = start
        previous_end = end

    if not items:
        warn("empty_alignment")
    if expected_item_count is not None and len(items) != expected_item_count:
        warn("item_count_mismatch")

    return {
        "warnings": sorted(warning_counts),
        "warning_counts": warning_counts,
        "alignment_item_count": len(items),
        "expected_item_count": expected_item_count,
        "interval_overlap": {
            "count": len(overlap_values),
            "total_sec": sum(overlap_values),
            "max_sec": max(overlap_values, default=0.0),
        },
        "gap_between_items": {
            "count": len(gap_values),
            "total_sec": sum(gap_values),
            "max_sec": max(gap_values, default=0.0),
        },
    }


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), *args], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def environment_summary() -> dict[str, Any]:
    result: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": {
            name: package_version(name)
            for name in ("torch", "transformers", "huggingface_hub", "numpy", "PyYAML", "soundfile")
        },
        "git": {
            "commit": git_value("rev-parse", "HEAD"),
            "branch": git_value("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(git_value("status", "--porcelain")),
        },
    }
    try:
        import torch

        result["torch_runtime"] = {
            "cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        }
    except Exception as exc:  # pragma: no cover - environment dependent
        result["torch_runtime_error"] = f"{type(exc).__name__}: {exc}"
    try:
        ffmpeg_line = subprocess.check_output(
            ["ffmpeg", "-version"], text=True, stderr=subprocess.STDOUT
        ).splitlines()[0]
    except Exception as exc:  # pragma: no cover - environment dependent
        ffmpeg_line = f"unavailable: {type(exc).__name__}: {exc}"
    result["ffmpeg"] = ffmpeg_line
    return result


def should_skip_existing(
    existing: dict[str, Any],
    *,
    model_identity: dict[str, Any],
    config_hash: str,
    audio_sha256: str,
    text_sha256: str,
) -> bool:
    return (
        existing.get("status") == "success"
        and existing.get("model", {}).get("model_id_or_path") == model_identity.get("model_id_or_path")
        and existing.get("model", {}).get("resolved_revision") == model_identity.get("resolved_revision")
        and existing.get("config", {}).get("config_hash") == config_hash
        and existing.get("input", {}).get("audio_sha256") == audio_sha256
        and existing.get("input", {}).get("text_sha256") == text_sha256
    )


def sample_summary(record: dict[str, Any], output_path: Path) -> dict[str, Any]:
    timestamps = record.get("timestamps") or []
    preview = timestamps[:3]
    if len(timestamps) > 5:
        preview += [{"omitted_items": len(timestamps) - 5}] + timestamps[-2:]
    elif len(timestamps) > 3:
        preview += timestamps[3:]
    return {
        "sample_id": record.get("sample_id"),
        "dataset": record.get("dataset"),
        "status": record.get("status"),
        "audio_duration_sec": record.get("input", {}).get("audio_duration_sec"),
        "text_character_count": record.get("input", {}).get("text_character_count"),
        "alignment_item_count": record.get("diagnostics", {}).get("alignment_item_count"),
        "warnings": record.get("diagnostics", {}).get("warnings", []),
        "timing": record.get("timing"),
        "error_type": record.get("error_type"),
        "external_output_path": str(output_path),
        "external_output_sha256": sha256_file(output_path) if output_path.exists() else None,
        "timestamp_preview": preview,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", help="Model ID or external local model path; overrides config")
    parser.add_argument("--revision", help="Requested model revision; overrides config")
    parser.add_argument("--language", help="Language label; overrides config")
    parser.add_argument("--device", help="Torch device; overrides config")
    parser.add_argument("--dtype", help="Torch dtype; overrides config")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    model_cfg = cfg.get("model", {})
    model_id = args.model or model_cfg.get("model_id_or_path") or cfg.get("model_id_or_path")
    if not model_id:
        raise SystemExit("model_id_or_path is required in config or --model")
    revision = args.revision or model_cfg.get("revision")
    language = args.language or cfg.get("language", "Chinese")
    device = args.device or model_cfg.get("device", "cuda")
    dtype = args.dtype or model_cfg.get("dtype", "bfloat16")
    ffmpeg_executable = cfg.get("executables", {}).get("ffmpeg", "ffmpeg")

    output_dir = expand_path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = cfg.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_index_root = expand_path(cfg.get("run_index_dir", ROOT / "runs" / "smoke"))
    run_dir = run_index_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    aligner = QwenForcedAligner(
        model_id,
        revision=revision,
        device=device,
        dtype=dtype,
        ffmpeg_executable=ffmpeg_executable,
    )
    model_identity = aligner.model_identity()
    model_load_sec = aligner.model_load_sec

    behavior_cfg = {
        "language": language,
        "device": device,
        "dtype": dtype,
        "validation": cfg.get("validation", {}),
        "audio_contract": cfg.get("audio_contract", {}),
    }
    config_hash = sha256_json(behavior_cfg)
    skip_existing_success = bool(cfg.get("skip_existing_success", True))
    overwrite = bool(args.overwrite or cfg.get("overwrite", False))

    command = shlex.join(sys.argv)
    atomic_write_text(run_dir / "command.txt", command + "\n")
    env = environment_summary()
    env["model"] = model_identity
    atomic_write_json(run_dir / "environment_summary.json", env)

    run_started = time.perf_counter()
    exit_code = 0
    summaries: list[dict[str, Any]] = []
    first_executed_sample = True

    for sample in cfg.get("samples", []):
        sample_id = sample["sample_id"]
        out_path = output_dir / f"{sample_id}.json"
        audio_path = expand_path(sample["audio_path"])
        text = str(sample["text"])
        audio_sha256 = sha256_file(audio_path)
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        if out_path.exists() and skip_existing_success and not overwrite:
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            if should_skip_existing(
                existing,
                model_identity=model_identity,
                config_hash=config_hash,
                audio_sha256=audio_sha256,
                text_sha256=text_sha256,
            ):
                print(f"skip matching success {out_path}")
                summaries.append(sample_summary(existing, out_path) | {"resume_action": "skipped_matching_success"})
                continue

        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "sample_id": sample_id,
            "dataset": sample.get("dataset"),
            "model": model_identity,
            "config": {
                "config_hash": config_hash,
                "language": language,
                "device": device,
                "dtype": dtype,
            },
            "input": {
                "audio_path": str(audio_path),
                "audio_source": sample.get("audio_source"),
                "audio_sha256": audio_sha256,
                "text": text,
                "text_source": sample.get("text_source"),
                "text_sha256": text_sha256,
                "text_character_count": len([char for char in text if not char.isspace()]),
            },
        }
        sample_started = time.perf_counter()
        try:
            detailed = aligner.align_detailed(audio_path, text, language)
            timestamps = detailed["timestamps"]
            expected_count = sample.get("expected_item_count")
            if expected_count is None and cfg.get("validation", {}).get("compare_non_whitespace_character_count", True):
                expected_count = record["input"]["text_character_count"]
            diagnostics = validate_alignment(
                timestamps,
                detailed["audio_duration_sec"],
                expected_item_count=expected_count,
            )
            record["input"].update(
                {
                    "audio_duration_sec": detailed["audio_duration_sec"],
                    "decoded_sample_rate_hz": detailed["decoded_sample_rate_hz"],
                    "decoded_num_samples": detailed["decoded_num_samples"],
                }
            )
            record.update(
                {
                    "status": "success",
                    "timestamps": timestamps,
                    "diagnostics": diagnostics,
                    "timing": detailed["timing"],
                }
            )
        except Exception as exc:  # keep each sample independent
            record.update(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "diagnostics": {"warnings": ["inference_failed"]},
                }
            )
            exit_code = 1
        record.setdefault("timing", {})["sample_wall_sec"] = time.perf_counter() - sample_started
        if first_executed_sample:
            record["timing"]["model_load_sec"] = model_load_sec
            record["timing"]["cold_start_total_sec"] = (model_load_sec or 0.0) + record["timing"]["sample_wall_sec"]
            first_executed_sample = False
        atomic_write_json(out_path, record)
        summaries.append(sample_summary(record, out_path) | {"resume_action": "executed"})
        print(f"{sample_id}: {record['status']} -> {out_path}")

    run_summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "config_path": str(args.config.resolve()),
        "config_file_sha256": sha256_file(args.config),
        "behavior_config_hash": config_hash,
        "model": model_identity,
        "model_load_sec": model_load_sec,
        "runtime_definition": {
            "model_load_sec": "processor/model loading and device transfer",
            "audio_decode_sec": "ffmpeg decode to mono 16 kHz float32",
            "input_prepare_sec": "processor input construction and device/dtype transfer",
            "forward_sec": "model forward with CUDA synchronization when applicable",
            "alignment_decode_sec": "forced-alignment timestamp decoding",
            "total_alignment_sec": "sum of decode, prepare, forward and alignment decode; excludes model load",
            "cold_start_total_sec": "model load plus first executed sample wall time",
        },
        "samples": summaries,
        "counts": {
            "total": len(summaries),
            "success": sum(item.get("status") == "success" for item in summaries),
            "failed": sum(item.get("status") == "failed" for item in summaries),
            "skipped_matching_success": sum(item.get("resume_action") == "skipped_matching_success" for item in summaries),
        },
        "run_wall_sec": time.perf_counter() - run_started,
        "full_outputs_root": str(output_dir),
        "evidence_scope": "Lightweight index; full per-sample JSON remains external and is referenced by path and SHA256.",
    }
    atomic_write_json(run_dir / "run_summary.json", run_summary)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
