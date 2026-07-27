#!/usr/bin/env python3
"""Run manifest preparation, inline-realign experiment, and bounded collection.

The controller is intentionally synchronous and resumable. Each stage writes a
separate log plus a compact status record. Re-running the same command reuses
alignment outputs whose request hashes still match; use --force to invalidate
all experiment branches.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def run_stage(
    *, name: str, command: list[str], root: Path, status_path: Path,
    allowed_returncodes: set[int] | None = None,
) -> int:
    log_path = root / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(status_path, {
        "time": utc_now(), "stage": name, "status": "running",
        "command": command, "log": str(log_path),
    })
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"time": utc_now(), "command": command}, ensure_ascii=False) + "\n")
        log.flush()
        process = subprocess.run(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    allowed = {0} if allowed_returncodes is None else set(allowed_returncodes)
    accepted = process.returncode in allowed
    append_jsonl(status_path, {
        "time": utc_now(), "stage": name,
        "status": "complete" if process.returncode == 0 else "partial" if accepted else "failed",
        "returncode": process.returncode, "log": str(log_path),
    })
    if not accepted:
        raise RuntimeError(f"stage {name} failed with rc={process.returncode}; see {log_path}")
    return process.returncode


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("smoke", "formal"), required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--demo-root", type=Path)
    p.add_argument("--demo-recursive", action="store_true")
    p.add_argument("--require-demo", action="store_true")
    p.add_argument("--demo-prepared-suffix", default="", help=argparse.SUPPRESS)
    p.add_argument(
        "--demo-prepared-suffixes",
        default="_qwen_fa_decoder_realign,_qwen_fa_raw_guarded,_qwen_fa",
    )
    p.add_argument("--mir1k-subset-root", type=Path, required=True)
    p.add_argument("--mir1k-audio-variant", choices=("official_vocal", "demucs", "mix"), default="official_vocal")
    p.add_argument("--mir1k-demucs-model", default="htdemucs_ft")
    p.add_argument("--include-heldout", action="store_true")
    p.add_argument("--mir1k-roles")
    p.add_argument(
        "--materialize-missing-mir1k",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p.add_argument("--m4-labels", type=Path, required=True)
    p.add_argument("--m4-audio-root", type=Path, required=True)
    p.add_argument("--m4-splits", default="validation")
    p.add_argument("--m4-long-target-sec", type=float, default=90.0)
    p.add_argument("--model", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--r2-checkpoint", type=Path, required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--local-files-only", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--evidence-cap-mib", type=float, default=8.0)
    p.add_argument("--max-shadow-cases-per-item", type=int)
    p.add_argument("--max-gt-oracle-cases-per-item", type=int)
    p.add_argument("--max-stable-window-trials-per-item", type=int)
    p.add_argument("--max-expansion-trials-per-item", type=int)
    p.add_argument("--demo-cap", type=int)
    p.add_argument("--mir1k-cap", type=int)
    p.add_argument("--m4-native-cap", type=int)
    p.add_argument("--m4-long-cap", type=int)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--render-profile", choices=("review", "final"), default="review")
    p.add_argument("--render-incomplete", action="store_true")
    p.add_argument("--skip-manifest", action="store_true")
    p.add_argument("--skip-experiment", action="store_true")
    p.add_argument("--skip-render", action="store_true")
    p.add_argument("--skip-summary", action="store_true")
    p.add_argument("--skip-collection", action="store_true")
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    root = args.out_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    status_path = root / "pipeline_status.jsonl"
    manifest_path = root / "experiment_manifest.jsonl"
    evidence_path = root / "inline_realign_evidence.tar.gz"
    followup_summary_path = root / "followup_analysis_summary.json"
    followup_markdown_path = root / "followup_analysis_summary.md"
    max_shadow = args.max_shadow_cases_per_item
    if max_shadow is None:
        max_shadow = 2 if args.mode == "smoke" else 8
    max_oracle = args.max_gt_oracle_cases_per_item
    if max_oracle is None:
        max_oracle = 1 if args.mode == "smoke" else 3
    max_stable_trials = args.max_stable_window_trials_per_item
    if max_stable_trials is None:
        max_stable_trials = 1 if args.mode == "smoke" else 2
    max_expansion_trials = args.max_expansion_trials_per_item
    if max_expansion_trials is None:
        max_expansion_trials = 1
    mir1k_roles = args.mir1k_roles or (
        "development" if args.mode == "smoke"
        else "development,quick_v2_extra,spare"
    )

    request = {
        "schema_version": "inline_realign_pipeline_request_v1",
        "created_at": utc_now(),
        "mode": args.mode,
        "out_root": str(root),
        "demo_root": None if args.demo_root is None else str(args.demo_root.expanduser().resolve()),
        "mir1k_subset_root": str(args.mir1k_subset_root.expanduser().resolve()),
        "m4_labels": str(args.m4_labels.expanduser().resolve()),
        "m4_audio_root": str(args.m4_audio_root.expanduser().resolve()),
        "include_heldout": bool(args.include_heldout),
        "mir1k_roles": mir1k_roles,
        "materialize_missing_mir1k": bool(args.materialize_missing_mir1k),
        "demo_prepared_suffixes": args.demo_prepared_suffixes,
        "require_demo": bool(args.require_demo),
        "model": str(args.model),
        "revision": args.revision,
        "r2_checkpoint": str(args.r2_checkpoint.expanduser().resolve()),
        "device": args.device,
        "evidence_cap_mib": args.evidence_cap_mib,
        "max_shadow_cases_per_item": max_shadow,
        "max_gt_oracle_cases_per_item": max_oracle,
        "max_stable_window_trials_per_item": max_stable_trials,
        "max_expansion_trials_per_item": max_expansion_trials,
        "render_after_all_alignment": not args.skip_render,
        "render_profile": args.render_profile,
        "force": bool(args.force),
    }
    atomic_json(root / "pipeline_request.json", request)

    python_bin = args.python_bin
    partial_failure = False
    try:
        if not args.skip_manifest:
            command = [
                python_bin, "scripts/demo/build_inline_realign_manifest.py",
                "--mode", args.mode,
                "--out-root", str(root),
                "--output", str(manifest_path),
                "--mir1k-subset-root", str(args.mir1k_subset_root.expanduser().resolve()),
                "--mir1k-audio-variant", args.mir1k_audio_variant,
                "--mir1k-demucs-model", args.mir1k_demucs_model,
                "--m4-labels", str(args.m4_labels.expanduser().resolve()),
                "--m4-audio-root", str(args.m4_audio_root.expanduser().resolve()),
                "--m4-splits", args.m4_splits,
                "--m4-long-target-sec", str(args.m4_long_target_sec),
                "--demo-prepared-suffixes", args.demo_prepared_suffixes,
                "--mir1k-roles", mir1k_roles,
            ]
            if args.demo_root is not None:
                command.extend(["--demo-root", str(args.demo_root.expanduser().resolve())])
            if args.demo_recursive:
                command.append("--demo-recursive")
            if args.require_demo:
                command.append("--require-demo")
            for flag, value in (
                ("--demo-cap", args.demo_cap), ("--mir1k-cap", args.mir1k_cap),
                ("--m4-native-cap", args.m4_native_cap), ("--m4-long-cap", args.m4_long_cap),
            ):
                if value is not None:
                    command.extend([flag, str(value)])
            if args.include_heldout:
                command.append("--include-heldout")
            command.append(
                "--materialize-missing-mir1k"
                if args.materialize_missing_mir1k
                else "--no-materialize-missing-mir1k"
            )
            run_stage(name="01_manifest", command=command, root=root, status_path=status_path)
        elif not manifest_path.is_file():
            raise FileNotFoundError(f"--skip-manifest requested but missing {manifest_path}")

        if not args.skip_experiment:
            command = [
                python_bin, "scripts/demo/run_inline_realign_experiment.py",
                "--manifest", str(manifest_path),
                "--out-root", str(root),
                "--model", str(args.model),
                "--revision", args.revision,
                "--r2-checkpoint", str(args.r2_checkpoint.expanduser().resolve()),
                "--device", args.device,
                "--max-shadow-cases-per-item", str(max_shadow),
                "--max-gt-oracle-cases-per-item", str(max_oracle),
                "--max-stable-window-trials-per-item", str(max_stable_trials),
                "--max-expansion-trials-per-item", str(max_expansion_trials),
            ]
            if args.cache_dir is not None:
                command.extend(["--cache-dir", str(args.cache_dir.expanduser().resolve())])
            command.append("--local-files-only" if args.local_files_only else "--no-local-files-only")
            if args.force:
                command.append("--force")
            experiment_rc = run_stage(
                name="02_experiment", command=command, root=root, status_path=status_path,
                allowed_returncodes={0, 1},
            )
            if experiment_rc == 1:
                if not (root / "experiment_summary.json").is_file():
                    raise RuntimeError(
                        f"experiment returned partial/failure without summary; see {root / 'logs' / '02_experiment.log'}"
                    )
                partial_failure = True
        elif not (root / "experiment_summary.json").is_file():
            raise FileNotFoundError(f"--skip-experiment requested but missing {root / 'experiment_summary.json'}")
        else:
            existing_complete = json.loads((root / "complete.json").read_text(encoding="utf-8")) \
                if (root / "complete.json").is_file() else {}
            partial_failure = existing_complete.get("status") == "partial_failure"

        if not args.skip_render:
            command = [
                python_bin, "scripts/demo/render_inline_realign_demo_batch.py",
                "--manifest", str(manifest_path),
                "--experiment-root", str(root),
                "--font", args.font,
                "--profile", args.render_profile,
            ]
            if args.render_incomplete:
                command.append("--render-incomplete")
            if args.force:
                command.append("--force")
            render_rc = run_stage(
                name="03_render_demo_after_all_alignments", command=command,
                root=root, status_path=status_path, allowed_returncodes={0, 1},
            )
            if render_rc == 1:
                partial_failure = True

        if not args.skip_summary:
            command = [
                python_bin, "scripts/demo/summarize_inline_realign_followup.py",
                str(root), "--output", str(followup_summary_path),
                "--markdown-output", str(followup_markdown_path),
            ]
            run_stage(name="04_summarize", command=command, root=root, status_path=status_path)

        if not args.skip_collection:
            command = [
                python_bin, "scripts/demo/collect_inline_realign_evidence.py",
                str(root), "--output", str(evidence_path),
                "--max-total-mib", str(args.evidence_cap_mib),
                "--max-cases-per-item", str(max_shadow),
            ]
            run_stage(name="05_collect", command=command, root=root, status_path=status_path)

        complete = {
            "schema_version": "inline_realign_pipeline_complete_v1",
            "created_at": utc_now(),
            "status": "partial_failure" if partial_failure else "complete",
            "mode": args.mode,
            "manifest": str(manifest_path),
            "experiment_summary": str(root / "experiment_summary.json"),
            "evidence": str(evidence_path) if evidence_path.is_file() else None,
            "demo_render_summary": str(root / "demo_render_summary.json") if (root / "demo_render_summary.json").is_file() else None,
            "followup_analysis_summary": str(followup_summary_path) if followup_summary_path.is_file() else None,
            "followup_analysis_markdown": str(followup_markdown_path) if followup_markdown_path.is_file() else None,
            "resume": "rerun the same command; matching branch request hashes are reused; render starts only after experiment_summary exists",
        }
        atomic_json(root / "pipeline_complete.json", complete)
        append_jsonl(status_path, {
            "time": utc_now(), "stage": "pipeline",
            "status": "partial_failure" if partial_failure else "complete",
        })
        print(json.dumps(complete, ensure_ascii=False), flush=True)
        return 1 if partial_failure else 0
    except Exception as exc:
        failure = {
            "schema_version": "inline_realign_pipeline_failure_v1",
            "created_at": utc_now(), "status": "failed",
            "error_type": type(exc).__name__, "error": str(exc),
        }
        atomic_json(root / "pipeline_failure.json", failure)
        append_jsonl(status_path, {"time": utc_now(), "stage": "pipeline", "status": "failed", "error": str(exc)})
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
