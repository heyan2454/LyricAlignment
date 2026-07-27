#!/usr/bin/env python3
"""General media/folder entry for the controlled R2 decoder/realign demo."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.karaoke import alignment_unit_mode, parse_lyrics_text
from lyricalign.demo.media_render import atomic_json, detect_font
from scripts.demo import run_raw_guarded_karaoke_batch as LEGACY


def log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def output_root(job: Any, args: argparse.Namespace, job_count: int) -> Path:
    if args.single_output_dir is not None:
        if job_count != 1:
            raise ValueError("--single-output-dir requires exactly one discovered song")
        return args.single_output_dir.expanduser().resolve()
    if args.output_dir is not None:
        return args.output_dir.expanduser().resolve() / job.stem
    return job.parent / f"{job.stem}_qwen_fa_decoder_realign"


def run_command(command: list[str], *, log_path: Path, env: dict[str, str] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log({"command": command, "log": str(log_path)})
    with log_path.open("a", encoding="utf-8") as handle:
        subprocess.run(command, check=True, stdout=handle, stderr=subprocess.STDOUT, env=env)


def align_job(job: Any, out_root: Path, prepared: dict[str, Path], args: argparse.Namespace) -> Path:
    align_root = out_root / "alignments" / "r2_decoder_realign"
    command = [
        args.python_bin,
        str(ROOT / "scripts" / "demo" / "align_qwen_fa_decoder_realign_comparison.py"),
        "--lyrics", str(job.lyrics),
        "--audio", str(prepared["vocal"]),
        "--out-root", str(align_root),
        "--item-id", job.stem,
        "--audio-variant", args.separator,
        "--model", str(args.model),
        "--revision", str(args.revision),
        "--r2-checkpoint", str(args.r2_checkpoint),
        "--device", args.device,
        "--language", args.language,
        "--timestamp-segment-sec", str(args.timestamp_segment_sec),
        "--core-sec", str(args.core_sec),
        "--left-context-sec", str(args.left_context_sec),
        "--right-context-sec", str(args.right_context_sec),
        "--context-agreement-tolerance-sec", str(args.context_agreement_tolerance_sec),
        "--max-repair-boundary-change-sec", str(args.max_repair_boundary_change_sec),
        "--local-projection", args.local_projection,
        "--local-minimum-duration-sec", str(args.local_minimum_duration_sec),
        "--silent-active-ratio-max", str(args.silent_active_ratio_max),
        "--silent-peak-margin-db", str(args.silent_peak_margin_db),
        "--silent-min-sustained-sec", str(args.silent_min_sustained_sec),
        "--startup-vocal-preroll-sec", str(args.startup_vocal_preroll_sec),
        "--startup-minimum-forward-characters", str(args.startup_minimum_forward_characters),
    ]
    command.append("--local-files-only" if args.local_files_only else "--no-local-files-only")
    if args.force_align:
        command.append("--force")
    environment = os.environ.copy()
    if args.local_files_only:
        environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    environment["PYTHONUNBUFFERED"] = "1"
    run_command(command, log_path=out_root / "alignment.log", env=environment)
    return align_root


def render_job(job: Any, out_root: Path, prepared: dict[str, Path], align_root: Path, args: argparse.Namespace) -> None:
    command = [
        args.python_bin,
        str(ROOT / "scripts" / "demo" / "render_decoder_realign_comparison.py"),
        "--alignment-root", str(align_root),
        "--mix-audio", str(prepared["mix"]),
        "--out-root", str(out_root),
        "--font", detect_font(args.font or {
            "Japanese": "Noto Sans CJK JP",
            "Chinese": "Noto Sans CJK SC",
            "Cantonese": "Noto Sans CJK SC",
        }.get(args.language, "Noto Sans")),
    ]
    if job.video is not None:
        command.extend(["--visual-source", str(job.video)])
    if args.subtitle_band_height is not None:
        command.extend(["--subtitle-band-height", str(args.subtitle_band_height)])
    if args.render_pairs:
        command.append("--render-pairs")
    if args.force_render:
        command.append("--force")
    run_command(command, log_path=out_root / "render.log")


def reused_prepared_paths(job: Any, suffix: str) -> dict[str, Path]:
    source_root = job.parent / f"{job.stem}{suffix}" / "work" / "audio"
    paths = {
        "mix": source_root / "mix.wav",
        "vocal": source_root / "vocals.wav",
        "accompaniment": source_root / "accompaniment.wav",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"--reuse-prepared-suffix {suffix!r} missing prepared files: " + ", ".join(missing)
        )
    return paths


def build_parser() -> argparse.ArgumentParser:
    p = LEGACY.build_parser()
    p.description = "Controlled R2 official/raw decoder × realign comparison demo"
    p.add_argument("--local-projection", choices=("isotonic", "forward"), default="isotonic")
    p.add_argument("--local-minimum-duration-sec", type=float, default=0.0)
    p.add_argument("--silent-active-ratio-max", type=float, default=0.01)
    p.add_argument("--silent-peak-margin-db", type=float, default=3.0)
    p.add_argument("--silent-min-sustained-sec", type=float, default=0.40)
    p.add_argument("--startup-vocal-preroll-sec", type=float, default=2.0)
    p.add_argument("--startup-minimum-forward-characters", type=int, default=24)
    p.add_argument("--render-pairs", action="store_true", help="also render optional pairwise comparisons")
    p.add_argument(
        "--reuse-prepared-suffix",
        help="reuse <song><suffix>/work/audio/{mix,vocals,accompaniment}.wav without copying",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.disable_realign:
        raise ValueError("this comparison entry always creates both realign-off and realign-on branches")
    args.r2_checkpoint = args.r2_checkpoint.expanduser().resolve()
    args.spleeter_model_root = args.spleeter_model_root.expanduser().resolve()
    if args.demucs_torch_home is not None:
        args.demucs_torch_home = args.demucs_torch_home.expanduser().resolve()
    if args.force:
        args.force_prepare = args.force_separation = args.force_align = args.force_render = True

    jobs = LEGACY.discover_jobs_with_lyrics_override(args)
    roots = {job.stem: output_root(job, args, len(jobs)) for job in jobs}
    plan = {
        "schema_version": "decoder_realign_comparison_batch_plan_v1",
        "created_at": LEGACY.utc_now(),
        "input": str(args.input),
        "language": args.language,
        "alignment_unit_mode": alignment_unit_mode(args.language),
        "separator": args.separator,
        "reuse_prepared_suffix": args.reuse_prepared_suffix,
        "stage": args.stage,
        "jobs": [
            {
                "stem": job.stem,
                "lyrics": str(job.lyrics),
                "video": str(job.video) if job.video else None,
                "audio": str(job.audio) if job.audio else None,
                "output_root": str(roots[job.stem]),
            }
            for job in jobs
        ],
        "design": {
            "fixed": "same R2 checkpoint + same vocal + 30s core; each decoder owns its production trajectory",
            "branches": ["O0 official", "O1 official+realign", "R0 raw", "R1 raw+realign"],
            "silent_window_skip": "enabled for all branches; not an ablation variable",
            "render": "2x2 comparison only by default, mix audio, no individual/vocal videos",
            "gap_repair": "disabled",
        },
        "weights": {
            "model": str(args.model),
            "revision": args.revision,
            "r2_checkpoint": str(args.r2_checkpoint),
        },
    }
    log({"plan": plan})
    if args.dry_run:
        return 0

    for job in jobs:
        document = parse_lyrics_text(job.lyrics.read_text(encoding="utf-8-sig"), language=args.language)
        log({"lyrics_preflight": job.stem, "unit_count": len(document.characters), "language": document.language})
    for command in ("ffmpeg", "ffprobe"):
        if shutil.which(command) is None:
            raise RuntimeError(f"required command not found: {command}")

    failures: list[dict[str, Any]] = []
    for job in jobs:
        out_root = roots[job.stem]
        out_root.mkdir(parents=True, exist_ok=True)
        atomic_json(out_root / "batch_plan.json", {**plan, "job": job.stem})
        try:
            if args.reuse_prepared_suffix:
                prepared = reused_prepared_paths(job, args.reuse_prepared_suffix)
            elif args.stage in ("all", "prepare"):
                prepared = LEGACY.prepare_job(job, out_root, args)
            else:
                prepared = LEGACY.existing_paths(out_root)
            align_root = out_root / "alignments" / "r2_decoder_realign"
            if args.stage in ("all", "align"):
                if not args.r2_checkpoint.is_dir():
                    raise FileNotFoundError(args.r2_checkpoint)
                align_root = align_job(job, out_root, prepared, args)
            if args.stage in ("all", "render"):
                render_job(job, out_root, prepared, align_root, args)
            atomic_json(out_root / "batch_manifest.json", {
                "schema_version": "decoder_realign_comparison_batch_manifest_v1",
                "created_at": LEGACY.utc_now(),
                "status": "complete",
                "job": job.stem,
                "source": {
                    "lyrics": str(job.lyrics),
                    "video": str(job.video) if job.video else None,
                    "audio": str(job.audio) if job.audio else None,
                },
                "output_root": str(out_root),
                "primary_video": str(out_root / "decoder_realign_demo.mp4"),
                "alignment_root": str(align_root),
            })
        except Exception as exc:  # noqa: BLE001
            failure = {
                "job": job.stem,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            failures.append(failure)
            atomic_json(out_root / "batch_manifest.json", {
                "schema_version": "decoder_realign_comparison_batch_manifest_v1",
                "created_at": LEGACY.utc_now(),
                "status": "failed",
                **failure,
            })
            log({"failure": failure})
            if args.fail_fast:
                raise
    log({"completed_jobs": len(jobs) - len(failures), "failures": failures})
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
