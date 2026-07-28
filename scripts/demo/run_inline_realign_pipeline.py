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
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.experiment_config import apply_if_unsupplied, get_path, load_yaml, supplied_flags


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
    """Run one stage while teeing output to both the terminal and a log file."""
    log_path = root / "logs" / f"{name}.log"
    live_path = root / "live_status.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    append_jsonl(status_path, {
        "time": started, "stage": name, "status": "running",
        "command": command, "log": str(log_path),
    })
    atomic_json(live_path, {
        "schema_version": "inline_realign_live_status_v1", "updated_at": started,
        "stage": name, "status": "running", "command": command, "log": str(log_path),
    })
    print(f"[pipeline] START {name} | log={log_path}", flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"time": started, "command": command}, ensure_ascii=False) + "\n")
        log.flush()
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line); log.flush()
            print(line, end="", flush=True)
        returncode = process.wait()
    allowed = {0} if allowed_returncodes is None else set(allowed_returncodes)
    accepted = returncode in allowed
    state = "complete" if returncode == 0 else "partial" if accepted else "failed"
    finished = utc_now()
    append_jsonl(status_path, {
        "time": finished, "stage": name, "status": state,
        "returncode": returncode, "log": str(log_path),
    })
    atomic_json(live_path, {
        "schema_version": "inline_realign_live_status_v1", "updated_at": finished,
        "stage": name, "status": state, "returncode": returncode, "log": str(log_path),
    })
    print(f"[pipeline] END {name} rc={returncode} status={state}", flush=True)
    if not accepted:
        raise RuntimeError(f"stage {name} failed with rc={returncode}; see {log_path}")
    return returncode


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("smoke", "formal"), required=True)
    p.add_argument("--config", type=Path, help="authoritative experiment YAML; explicit CLI flags override matching values")
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--demo-root", type=Path)
    p.add_argument("--demo-recursive", action="store_true")
    p.add_argument("--require-demo", action="store_true")
    p.add_argument("--demo-prepared-suffix", default="", help=argparse.SUPPRESS)
    p.add_argument(
        "--demo-prepared-suffixes",
        default="_qwen_fa,_qwen_fa_decoder_realign,_qwen_fa_raw_guarded",
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
    p.add_argument("--m4-long-target-sec", type=float, default=90.0, help=argparse.SUPPRESS)
    p.add_argument("--m4-long-target-secs", default="60,120,180")
    p.add_argument("--model", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--r2-checkpoint", type=Path, required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--local-files-only", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--evidence-cap-mib", type=float, default=8.0)
    p.add_argument("--evidence-max-cases-per-item", type=int, default=4)
    p.add_argument("--max-shadow-cases-per-item", type=int)
    p.add_argument("--max-gt-oracle-cases-per-item", type=int)
    p.add_argument("--max-stable-window-trials-per-item", type=int)
    p.add_argument("--max-expansion-trials-per-item", type=int)
    p.add_argument("--max-clean-control-cases-per-item", type=int)
    p.add_argument("--max-pending-shadow-cases-per-item", type=int)
    p.add_argument("--max-tail-rollback-cases-per-item", type=int)
    p.add_argument("--demo-cap", type=int, help="optional emergency cap; formal defaults to all discovered Demo songs")
    p.add_argument("--demo-per-language-cap", type=int)
    p.add_argument("--mir1k-cap", type=int)
    p.add_argument("--m4-native-cap", type=int)
    p.add_argument("--m4-long-cap", type=int)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--render-profile", choices=("review", "final"), default="review")
    p.add_argument("--render-incomplete", action="store_true")
    p.add_argument(
        "--demo-publish-layout", choices=("central", "adjacent", "directory"), default="central",
        help="central keeps canonical outputs only; adjacent/directory publish lightweight links after rendering",
    )
    p.add_argument("--demo-publish-root", type=Path)
    p.add_argument("--skip-manifest", action="store_true")
    p.add_argument("--skip-experiment", action="store_true")
    p.add_argument("--skip-visualization", action="store_true")
    p.add_argument("--skip-render", action="store_true")
    p.add_argument("--comparison-branches", default="RAW_B2,B0_60_fixed_official,B1_30_fixed_official,B2_30_silence_official")
    p.add_argument("--timeline-page-seconds", type=float, default=60.0)
    p.add_argument("--duration-histogram-bin-ms", type=float, default=5.0)
    p.add_argument("--duration-histogram-max-ms", type=float, default=500.0)
    p.add_argument("--stable-left-overlap-units", type=int, default=8)
    p.add_argument("--deferred-max-windows", type=int, default=3)
    p.add_argument("--deferred-max-seconds", type=float, default=120.0)
    p.add_argument("--deferred-max-units", type=int, default=320)
    p.add_argument("--skip-summary", action="store_true")
    p.add_argument("--skip-collection", action="store_true")
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    supplied = supplied_flags(sys.argv[1:])
    config_payload: dict[str, Any] = {}
    if args.config is not None:
        config_payload = load_yaml(args.config)
        configured_mode = get_path(config_payload, "mode")
        if configured_mode and str(configured_mode) != args.mode:
            raise ValueError(f"config mode {configured_mode!r} does not match --mode {args.mode!r}")
        mappings = [
            ("--demo-cap", "demo_cap", "selection.demo_total_cap"),
            ("--demo-per-language-cap", "demo_per_language_cap", "selection.demo_per_language_cap"),
            ("--mir1k-cap", "mir1k_cap", "selection.mir1k_cap"),
            ("--m4-native-cap", "m4_native_cap", "selection.m4singer_validation_native_cap"),
            ("--m4-long-cap", "m4_long_cap", "selection.m4singer_synthetic_long_total_cap"),
            ("--max-gt-oracle-cases-per-item", "max_gt_oracle_cases_per_item", "shadow.gt_oracle_cases_per_item"),
            ("--max-clean-control-cases-per-item", "max_clean_control_cases_per_item", "shadow.clean_control_cases_per_item"),
            ("--max-stable-window-trials-per-item", "max_stable_window_trials_per_item", "shadow.stable_window_trials_per_item"),
            ("--max-expansion-trials-per-item", "max_expansion_trials_per_item", "shadow.expansion_trials_per_item"),
            ("--max-pending-shadow-cases-per-item", "max_pending_shadow_cases_per_item", "shadow.pending_cases_per_item"),
            ("--max-tail-rollback-cases-per-item", "max_tail_rollback_cases_per_item", "shadow.tail_rollback_cases_per_item"),
            ("--evidence-cap-mib", "evidence_cap_mib", "collection.max_total_mib"),
            ("--evidence-max-cases-per-item", "evidence_max_cases_per_item", "collection.max_cases_per_item"),
            ("--render-profile", "render_profile", "visualization.render_profile"),
            ("--timeline-page-seconds", "timeline_page_seconds", "visualization.timeline_page_seconds"),
            ("--duration-histogram-bin-ms", "duration_histogram_bin_ms", "visualization.duration_histogram_bin_ms"),
            ("--duration-histogram-max-ms", "duration_histogram_max_ms", "visualization.duration_histogram_max_ms"),
            ("--stable-left-overlap-units", "stable_left_overlap_units", "shadow.stable_anchor.left_overlap_units"),
            ("--deferred-max-windows", "deferred_max_windows", "shadow.deferred_realign.max_windows"),
            ("--deferred-max-seconds", "deferred_max_seconds", "shadow.deferred_realign.max_seconds"),
            ("--deferred-max-units", "deferred_max_units", "shadow.deferred_realign.max_units"),
        ]
        for flag, attribute, path in mappings:
            apply_if_unsupplied(args, supplied=supplied, flag=flag, attribute=attribute, value=get_path(config_payload, path))
        targets = get_path(config_payload, "selection.m4singer_synthetic_long_target_seconds")
        if targets is not None and "--m4-long-target-secs" not in supplied:
            args.m4_long_target_secs = ",".join(str(value) for value in targets)
        roles = get_path(config_payload, "selection.mir1k_roles")
        if roles is not None and "--mir1k-roles" not in supplied:
            args.mir1k_roles = ",".join(str(value) for value in roles)
        branches = get_path(config_payload, "visualization.comparison_branches")
        if branches is not None and "--comparison-branches" not in supplied:
            args.comparison_branches = ",".join(str(value) for value in branches)
    root = args.out_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Terminal-state files describe only the current invocation.  Reusable
    # branch outputs remain untouched, but stale failure/complete markers must
    # not leak into a resumed evidence package.
    for stale_name in ("pipeline_failure.json", "pipeline_complete.json"):
        (root / stale_name).unlink(missing_ok=True)
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
        max_expansion_trials = 1 if args.mode == "smoke" else 2
    max_clean_controls = args.max_clean_control_cases_per_item
    if max_clean_controls is None:
        max_clean_controls = 1 if args.mode == "smoke" else 2
    max_pending = args.max_pending_shadow_cases_per_item
    if max_pending is None:
        max_pending = 1 if args.mode == "smoke" else 3
    max_tail_rollback = args.max_tail_rollback_cases_per_item
    if max_tail_rollback is None:
        max_tail_rollback = 1 if args.mode == "smoke" else 2
    mir1k_roles = args.mir1k_roles or (
        "development" if args.mode == "smoke"
        else "development,quick_v2_extra,spare"
    )

    request = {
        "schema_version": "inline_realign_pipeline_request_v3_visual_experiment_suite",
        "config_path": None if args.config is None else str(args.config.expanduser().resolve()),
        "resolved_config": config_payload,
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
        "evidence_max_cases_per_item": args.evidence_max_cases_per_item,
        "max_shadow_cases_per_item": max_shadow,
        "max_gt_oracle_cases_per_item": max_oracle,
        "max_stable_window_trials_per_item": max_stable_trials,
        "max_expansion_trials_per_item": max_expansion_trials,
        "max_clean_control_cases_per_item": max_clean_controls,
        "max_pending_shadow_cases_per_item": max_pending,
        "max_tail_rollback_cases_per_item": max_tail_rollback,
        "demo_cap": args.demo_cap,
        "demo_per_language_cap": args.demo_per_language_cap,
        "demo_publish_layout": args.demo_publish_layout,
        "demo_publish_root": None if args.demo_publish_root is None else str(args.demo_publish_root.expanduser().resolve()),
        "m4_long_target_secs": args.m4_long_target_secs,
        "comparison_branches": args.comparison_branches,
        "timeline_page_seconds": args.timeline_page_seconds,
        "duration_histogram_bin_ms": args.duration_histogram_bin_ms,
        "duration_histogram_max_ms": args.duration_histogram_max_ms,
        "stable_left_overlap_units": args.stable_left_overlap_units,
        "deferred_max_windows": args.deferred_max_windows,
        "deferred_max_seconds": args.deferred_max_seconds,
        "deferred_max_units": args.deferred_max_units,
        "visualization_after_all_alignment": not args.skip_visualization,
        "render_after_all_alignment": not args.skip_render,
        "render_profile": args.render_profile,
        "force": bool(args.force),
    }
    atomic_json(root / "pipeline_request.json", request)
    atomic_json(root / "resolved_config.json", {
        "schema_version": "inline_realign_resolved_config_v1",
        "source_config_path": None if args.config is None else str(args.config.expanduser().resolve()),
        "source_config": config_payload,
        "effective": request,
        "override_rule": "explicit CLI arguments override YAML; all stage commands are generated from this effective record",
    })

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
                "--m4-long-target-secs", args.m4_long_target_secs,
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
                ("--demo-cap", args.demo_cap), ("--demo-per-language-cap", args.demo_per_language_cap), ("--mir1k-cap", args.mir1k_cap),
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
                "--max-clean-control-cases-per-item", str(max_clean_controls),
                "--max-pending-shadow-cases-per-item", str(max_pending),
                "--max-tail-rollback-cases-per-item", str(max_tail_rollback),
                "--stable-left-overlap-units", str(args.stable_left_overlap_units),
                "--deferred-max-windows", str(args.deferred_max_windows),
                "--deferred-max-seconds", str(args.deferred_max_seconds),
                "--deferred-max-units", str(args.deferred_max_units),
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

        if not args.skip_visualization:
            command = [
                python_bin, "scripts/demo/analyze_inline_realign_visuals.py",
                "--manifest", str(manifest_path),
                "--experiment-root", str(root),
                "--timeline-page-seconds", str(args.timeline_page_seconds),
                "--duration-bin-ms", str(args.duration_histogram_bin_ms),
                "--duration-max-ms", str(args.duration_histogram_max_ms),
                "--comparison-branches", args.comparison_branches,
                "--font", args.font,
            ]
            visual_rc = run_stage(
                name="03_visualize_all_items", command=command, root=root,
                status_path=status_path, allowed_returncodes={0, 1},
            )
            if visual_rc == 1:
                partial_failure = True

        if not args.skip_render:
            command = [
                python_bin, "scripts/demo/render_inline_realign_demo_batch.py",
                "--manifest", str(manifest_path),
                "--experiment-root", str(root),
                "--font", args.font,
                "--profile", args.render_profile,
                "--comparison-branches", args.comparison_branches,
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

        if not args.skip_render and args.demo_publish_layout != "central":
            command = [
                python_bin, "scripts/demo/publish_inline_realign_demo_outputs.py",
                "--manifest", str(manifest_path),
                "--experiment-root", str(root),
                "--layout", args.demo_publish_layout,
            ]
            if args.demo_publish_root is not None:
                command.extend(["--publish-root", str(args.demo_publish_root.expanduser().resolve())])
            if args.force:
                command.append("--force")
            publish_rc = run_stage(
                name="03b_publish_demo_outputs", command=command, root=root,
                status_path=status_path, allowed_returncodes={0, 1},
            )
            if publish_rc == 1:
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
                "--max-cases-per-item", str(args.evidence_max_cases_per_item),
            ]
            run_stage(name="05_collect", command=command, root=root, status_path=status_path)

        complete = {
            "schema_version": "inline_realign_pipeline_complete_v3_visual_realign_suite",
            "created_at": utc_now(),
            "status": "partial_failure" if partial_failure else "complete",
            "mode": args.mode,
            "manifest": str(manifest_path),
            "experiment_summary": str(root / "experiment_summary.json"),
            "evidence": str(evidence_path) if evidence_path.is_file() else None,
            "demo_render_summary": str(root / "demo_render_summary.json") if (root / "demo_render_summary.json").is_file() else None,
            "demo_publish_summary": str(root / "demo_publish_summary.json") if (root / "demo_publish_summary.json").is_file() else None,
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
