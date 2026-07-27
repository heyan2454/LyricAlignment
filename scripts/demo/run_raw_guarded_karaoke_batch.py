#!/usr/bin/env python3
"""General same-stem batch entry for the R2 raw + guarded karaoke demo.

This mirrors the input discovery and media preparation behaviour of
``run_qwen_fa_batch.py`` while replacing only the alignment policy with:

R2 raw timestamp argmax -> serial raw baseline -> guarded exact/+2 realignment.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.batch import (  # noqa: E402
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaJob,
    discover_jobs,
)
from lyricalign.demo.karaoke import alignment_unit_mode, normalize_alignment_language, parse_lyrics_text  # noqa: E402
from lyricalign.demo.media_render import atomic_json, detect_font  # noqa: E402
from scripts.demo import run_qwen_fa_batch as BATCH  # noqa: E402

DEFAULT_MODEL = BATCH.DEFAULT_MODEL_ID
DEFAULT_REVISION = BATCH.DEFAULT_MODEL_REVISION
DEFAULT_R2 = Path(
    "/root/autodl-tmp/AST_storage/Data/lyricalign/runs/"
    "20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _pick_by_extension(paths: list[Path], extensions: tuple[str, ...]) -> Path | None:
    for extension in extensions:
        candidates = sorted(
            (path for path in paths if path.suffix.lower() == extension),
            key=lambda path: path.name.lower(),
        )
        if candidates:
            return candidates[0]
    return None


def discover_jobs_with_lyrics_override(args: argparse.Namespace) -> list[MediaJob]:
    """Discover exactly one media task when lyrics may have another basename.

    The shared ``discover_jobs`` helper intentionally requires a same-stem TXT.
    For ``--lyrics`` we instead discover media first, then attach the explicit
    lyrics file. Directory inputs without ``--name`` are accepted only when they
    contain exactly one media stem, preventing an ambiguous lyrics-to-media map.
    """
    if args.lyrics_override is None:
        return discover_jobs(args.input, name=args.name, recursive=args.recursive)

    lyrics = args.lyrics_override.expanduser().resolve()
    if not lyrics.is_file():
        raise FileNotFoundError(lyrics)
    path = args.input.expanduser()
    selected_stem = args.name
    groups: dict[tuple[Path, str], list[Path]] = {}

    def add_media(candidate: Path) -> None:
        if not candidate.is_file():
            return
        if candidate.suffix.lower() not in VIDEO_EXTENSIONS + AUDIO_EXTENSIONS:
            return
        groups.setdefault((candidate.parent.resolve(), candidate.stem), []).append(candidate.resolve())

    if path.exists() and path.is_file():
        selected_stem = selected_stem or path.stem
        for candidate in path.parent.iterdir():
            if candidate.stem == selected_stem:
                add_media(candidate)
    elif path.exists() and path.is_dir():
        iterator = path.rglob("*") if args.recursive else path.iterdir()
        for candidate in iterator:
            if selected_stem is None or candidate.stem == selected_stem:
                add_media(candidate)
    else:
        directory = (path.parent if str(path.parent) not in ("", ".") else Path.cwd()).resolve()
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        selected_stem = selected_stem or path.name
        for candidate in directory.iterdir():
            if candidate.stem == selected_stem:
                add_media(candidate)

    jobs: list[MediaJob] = []
    for (parent, stem), files in sorted(groups.items(), key=lambda item: (str(item[0][0]), item[0][1])):
        video = _pick_by_extension(files, VIDEO_EXTENSIONS)
        audio = _pick_by_extension(files, AUDIO_EXTENSIONS)
        if video is None and audio is None:
            continue
        jobs.append(MediaJob(stem=stem, parent=parent, lyrics=lyrics, video=video, audio=audio))
    if len(jobs) != 1:
        raise ValueError(
            "--lyrics must resolve to exactly one media stem; "
            f"found {len(jobs)}. Pass a media file/basename or use --name for a directory."
        )
    return jobs


def output_root(job: Any, args: argparse.Namespace, job_count: int) -> Path:
    if args.single_output_dir is not None:
        if job_count != 1:
            raise ValueError("--single-output-dir requires exactly one discovered song")
        return args.single_output_dir.expanduser().resolve()
    if args.output_dir is not None:
        return args.output_dir.expanduser().resolve() / job.stem
    return job.parent / f"{job.stem}_qwen_fa_raw_guarded"


def preparation_namespace(args: argparse.Namespace, out_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output_dir=out_root.parent,
        media_duration_tolerance_sec=args.media_duration_tolerance_sec,
        allow_duration_mismatch=args.allow_duration_mismatch,
        separator=args.separator,
        spleeter_model_root=args.spleeter_model_root,
        spleeter_model_name=args.spleeter_model_name,
        spleeter_env=args.spleeter_env,
        spleeter_command=args.spleeter_command,
        demucs_version=args.demucs_version,
        demucs_model=args.demucs_model,
        demucs_env=args.demucs_env,
        demucs_command=args.demucs_command,
        demucs_device=args.demucs_device,
        demucs_shifts=args.demucs_shifts,
        demucs_overlap=args.demucs_overlap,
        demucs_segment=args.demucs_segment,
        demucs_jobs=args.demucs_jobs,
        demucs_clip_mode=args.demucs_clip_mode,
        demucs_torch_home=args.demucs_torch_home,
        force_prepare=args.force_prepare,
        force_separation=args.force_separation,
        render_audio="source",
    )


def prepare_job(job: Any, out_root: Path, args: argparse.Namespace) -> dict[str, Path]:
    ns = preparation_namespace(args, out_root)
    if job.video is not None and job.audio is not None:
        video_duration = BATCH._probe_duration(job.video)
        audio_duration = BATCH._probe_duration(job.audio)
        difference = abs(video_duration - audio_duration)
        if difference > args.media_duration_tolerance_sec and not args.allow_duration_mismatch:
            raise RuntimeError(
                "same-stem video/audio duration mismatch exceeds tolerance: "
                f"video={video_duration:.3f}s audio={audio_duration:.3f}s "
                f"difference={difference:.3f}s tolerance={args.media_duration_tolerance_sec:.3f}s"
            )
    work_audio = out_root / "work" / "audio"
    mix = work_audio / "mix.wav"
    BATCH._write_mix_audio(job.mix_source, mix, work_audio / "mix.identity.json", force=args.force_prepare)
    vocals, accompaniment = BATCH._prepare_vocals(
        mix=mix,
        work_audio=work_audio,
        args=ns,
        force=args.force_prepare or args.force_separation,
    )
    return {"mix": mix, "vocal": vocals, "accompaniment": accompaniment}


def existing_paths(out_root: Path) -> dict[str, Path]:
    work_audio = out_root / "work" / "audio"
    paths = {
        "mix": work_audio / "mix.wav",
        "vocal": work_audio / "vocals.wav",
        "accompaniment": work_audio / "accompaniment.wav",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("render/align stage requires prepared media: " + ", ".join(missing))
    return paths


def run_command(command: list[str], *, log_path: Path, env: dict[str, str] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log({"command": command, "log": str(log_path)})
    with log_path.open("a", encoding="utf-8") as handle:
        subprocess.run(command, check=True, stdout=handle, stderr=subprocess.STDOUT, env=env)


def align_job(job: Any, out_root: Path, prepared: dict[str, Path], args: argparse.Namespace) -> Path:
    align_root = out_root / "alignments" / "r2_raw_guarded"
    command = [
        args.python_bin,
        str(ROOT / "scripts" / "demo" / "align_qwen_fa_raw_guarded_demo.py"),
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
    ]
    if args.local_files_only:
        command.append("--local-files-only")
    else:
        command.append("--no-local-files-only")
    if args.disable_realign:
        command.append("--disable-realign")
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
        str(ROOT / "scripts" / "demo" / "render_raw_guarded_karaoke.py"),
        "--alignment-root", str(align_root),
        "--mix-audio", str(prepared["mix"]),
        "--vocal-audio", str(prepared["vocal"]),
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
    if args.force_render:
        command.append("--force")
    run_command(command, log_path=out_root / "render.log")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="General media/folder entry for the R2 raw + guarded karaoke demo."
    )
    p.add_argument("input", type=Path, help="media file, TXT file, basename, or directory")
    p.add_argument("--name", help="only process this exact stem when input is a directory")
    p.add_argument(
        "--lyrics", dest="lyrics_override", type=Path,
        help="explicit lyrics TXT for a single discovered song; allows media and lyrics to have different basenames",
    )
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--output-dir", type=Path, help="shared root; each song uses <root>/<stem>")
    p.add_argument("--single-output-dir", type=Path, help="exact output directory for one song")
    p.add_argument("--stage", choices=("all", "prepare", "align", "render"), default="all")
    p.add_argument("--language", type=normalize_alignment_language, default="Chinese")
    p.add_argument(
        "--separator", choices=("demucs", "spleeter"),
        default=os.environ.get("LYRICALIGN_SEPARATOR", "demucs"),
        help="vocal separator; Demucs is the supported/default demo path, Spleeter is legacy-only",
    )
    p.add_argument("--model", default=os.environ.get("MODEL_SOURCE", DEFAULT_MODEL))
    p.add_argument("--revision", default=os.environ.get("MODEL_REVISION", DEFAULT_REVISION))
    p.add_argument("--r2-checkpoint", type=Path, default=Path(os.environ.get("R2_CHECKPOINT", DEFAULT_R2)))
    p.add_argument("--python-bin", default=os.environ.get("PYTHON_BIN", sys.executable))
    p.add_argument("--device", default="cuda")
    p.add_argument("--local-files-only", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    p.add_argument("--core-sec", type=float, default=30.0)
    p.add_argument("--left-context-sec", type=float, default=10.0)
    p.add_argument("--right-context-sec", type=float, default=10.0)
    p.add_argument("--context-agreement-tolerance-sec", type=float, default=0.16)
    p.add_argument("--max-repair-boundary-change-sec", type=float, default=0.80)
    p.add_argument("--disable-realign", action="store_true")
    p.add_argument("--font")
    p.add_argument("--subtitle-band-height", type=int)
    p.add_argument("--media-duration-tolerance-sec", type=float, default=0.5)
    p.add_argument("--allow-duration-mismatch", action="store_true")
    p.add_argument("--spleeter-model-root", type=Path, default=Path(os.environ.get("SPLEETER_MODEL_ROOT", Path.home() / ".cache/spleeter_models")))
    p.add_argument("--spleeter-model-name", default="2stems")
    p.add_argument("--spleeter-env", default=os.environ.get("SPLEETER_ENV", "spleeter"))
    p.add_argument("--spleeter-command")
    p.add_argument("--demucs-version", default=os.environ.get("DEMUCS_VERSION", "4.1.0"))
    p.add_argument("--demucs-model", default=os.environ.get("DEMUCS_MODEL", "htdemucs_ft"))
    p.add_argument("--demucs-env", default=os.environ.get("DEMUCS_ENV", "demucs"))
    p.add_argument("--demucs-command")
    p.add_argument("--demucs-device", default=os.environ.get("DEMUCS_DEVICE", "cuda"))
    p.add_argument("--demucs-shifts", type=int, default=int(os.environ.get("DEMUCS_SHIFTS", "0")))
    p.add_argument("--demucs-overlap", type=float, default=float(os.environ.get("DEMUCS_OVERLAP", "0.25")))
    p.add_argument("--demucs-segment", type=int)
    p.add_argument("--demucs-jobs", type=int, default=int(os.environ.get("DEMUCS_JOBS", "0")))
    p.add_argument("--demucs-clip-mode", choices=("rescale", "clamp"), default="rescale")
    p.add_argument(
        "--demucs-torch-home", type=Path,
        default=Path(os.environ.get(
            "TORCH_HOME",
            "/root/autodl-tmp/AST_storage/Data/lyricalign/models/torch",
        )),
        help="external Demucs/PyTorch model cache",
    )
    p.add_argument("--force-prepare", action="store_true")
    p.add_argument("--force-separation", action="store_true")
    p.add_argument("--force-align", action="store_true")
    p.add_argument("--force-render", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--fail-fast", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    args.r2_checkpoint = args.r2_checkpoint.expanduser().resolve()
    args.spleeter_model_root = args.spleeter_model_root.expanduser().resolve()
    if args.demucs_torch_home is not None:
        args.demucs_torch_home = args.demucs_torch_home.expanduser().resolve()
    if args.force:
        args.force_prepare = args.force_separation = args.force_align = args.force_render = True
    jobs = discover_jobs_with_lyrics_override(args)
    roots = {job.stem: output_root(job, args, len(jobs)) for job in jobs}
    plan = {
        "schema_version": "raw_guarded_karaoke_batch_plan_v1",
        "created_at": utc_now(),
        "input": str(args.input),
        "language": args.language,
        "alignment_unit_mode": alignment_unit_mode(args.language),
        "separator": args.separator,
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
        "alignment_policy": "r2_raw_serial_baseline_plus_guarded_exact_verified_by_matched_plus2",
        "terminology": {
            "raw": "Qwen timestamp-slot argmax before the official processor monotonic repair",
            "baseline": "complete serial-window alignment built from raw timestamps, before local realignment",
            "guarded": "detector plus exact/+2 verification and safety gates; not a separate decoder",
            "final": "baseline after only approved guarded repairs; it may equal baseline",
        },
        "weights": {"model": str(args.model), "revision": args.revision, "r2_checkpoint": str(args.r2_checkpoint)},
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
            if args.stage in ("all", "prepare"):
                prepared = prepare_job(job, out_root, args)
            else:
                prepared = existing_paths(out_root)
            align_root = out_root / "alignments" / "r2_raw_guarded"
            if args.stage in ("all", "align"):
                if not args.r2_checkpoint.is_dir():
                    raise FileNotFoundError(args.r2_checkpoint)
                align_root = align_job(job, out_root, prepared, args)
            if args.stage in ("all", "render"):
                render_job(job, out_root, prepared, align_root, args)
            atomic_json(out_root / "batch_manifest.json", {
                "schema_version": "raw_guarded_karaoke_batch_manifest_v1",
                "created_at": utc_now(),
                "status": "complete",
                "job": job.stem,
                "source": {"lyrics": str(job.lyrics), "video": str(job.video) if job.video else None, "audio": str(job.audio) if job.audio else None},
                "output_root": str(out_root),
                "primary_video": str(out_root / "raw_guarded_demo.mp4"),
                "alignment_root": str(align_root),
            })
        except Exception as exc:  # noqa: BLE001
            failure = {"job": job.stem, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            failures.append(failure)
            atomic_json(out_root / "batch_manifest.json", {
                "schema_version": "raw_guarded_karaoke_batch_manifest_v1",
                "created_at": utc_now(), "status": "failed", **failure,
            })
            log({"failure": failure})
            if args.fail_fast:
                raise
    log({"completed_jobs": len(jobs) - len(failures), "failures": failures})
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
