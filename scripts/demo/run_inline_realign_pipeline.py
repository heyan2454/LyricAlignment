#!/usr/bin/env python3
"""Run the complete multilingual inline-realign experiment with strict resume.

Order is intentionally: manifest -> model experiment -> summary -> static
visualization -> compact evidence -> analysis_complete -> slow Demo rendering.
Thus video rendering can be deferred or resumed without invalidating completed
model/metric work.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.experiment_config import apply_if_unsupplied, get_path, load_yaml, supplied_flags
from lyricalign.demo.run_state import RunState, atomic_json, canonical_hash, file_identity


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _script_identity(paths: Iterable[Path]) -> dict[str, Any]:
    """Content identity for code that affects experiment semantics.

    Modification times are deliberately excluded: extracting the same archive or
    restoring a file from backup must not invalidate a scientifically identical
    resume.  A changed SHA-256 still forces a new run identity.
    """
    result: dict[str, Any] = {}
    for path in paths:
        if not path.is_file():
            continue
        identity = file_identity(path)
        result[str(path.relative_to(ROOT))] = {
            key: identity.get(key) for key in ("path", "exists", "size", "sha256")
        }
    return result


def experiment_force_requested(*, force: bool, invalidated_stages: Iterable[str]) -> bool:
    """Experiment invalidation means recompute item/branch outputs, not only the top-level stage record."""
    return bool(force or "experiment" in set(invalidated_stages))


def option_assignment(flag: str, value: Any) -> str:
    """Return an argparse-safe ``--option=value`` token.

    Text-dosage CSV values begin with a negative number.  Passing such a value
    as the next argv token makes argparse interpret it as another option and
    raises ``expected one argument``.
    """
    if not flag.startswith("--"):
        raise ValueError(f"long option required, got {flag!r}")
    return f"{flag}={value}"


def final_pipeline_status(*, render_mode: str, partial_failure: bool, render_failure: bool) -> str:
    if partial_failure:
        return "partial_failure_render_deferred" if render_mode == "skip" else "partial_failure"
    if render_mode == "skip":
        return "analysis_complete_render_deferred"
    if render_failure:
        return "render_partial_failure"
    return "complete"


def run_stage(
    *, name: str, command: list[str], root: Path, status_path: Path,
    state: RunState, request: dict[str, Any], expected_outputs: list[Path],
    resume: bool, allowed_returncodes: set[int] | None = None,
    allow_stage_resume_skip: bool = True,
) -> int:
    request_hash = canonical_hash(request)
    # Itemized stages must always enter their controller on resume.  Their own
    # per-item state validates every alignment/page/video; skipping only from a
    # top-level summary would miss deleted or modified child artifacts.
    if allow_stage_resume_skip and resume and state.stage_is_complete(
        name, request_hash=request_hash, outputs=expected_outputs
    ):
        append_jsonl(status_path, {"time": utc_now(), "stage": name, "status": "resume_skipped_complete"})
        print(f"[pipeline] RESUME SKIP {name}", flush=True)
        return 0
    log_path = root / "logs" / f"{name}.log"
    live_path = root / "live_status.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    state.begin_stage(name, request=request, outputs=expected_outputs)
    append_jsonl(status_path, {
        "time": started, "stage": name, "status": "running",
        "command": command, "log": str(log_path),
    })
    atomic_json(live_path, {
        "schema_version": "inline_realign_live_status_v2_resumable",
        "updated_at": started, "stage": name, "status": "running",
        "command": command, "log": str(log_path),
    })
    print(f"[pipeline] START {name} | log={log_path}", flush=True)
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"time": started, "command": command}, ensure_ascii=False) + "\n")
            log.flush()
            process = subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line); log.flush(); print(line, end="", flush=True)
            returncode = process.wait()
        allowed = {0} if allowed_returncodes is None else set(allowed_returncodes)
        accepted = returncode in allowed
        status = "complete" if returncode == 0 else "partial_failure" if accepted else "failed"
        outputs_present = all(path.is_file() and path.stat().st_size > 0 for path in expected_outputs)
        if accepted and not outputs_present:
            status = "failed"
            accepted = False
            returncode = 2
        finished = utc_now()
        state.finish_stage(
            name, status=status, request_hash=request_hash, outputs=expected_outputs,
            returncode=returncode,
            error=None if accepted else f"stage failed or expected outputs missing; see {log_path}",
        )
        append_jsonl(status_path, {
            "time": finished, "stage": name, "status": status,
            "returncode": returncode, "log": str(log_path),
        })
        atomic_json(live_path, {
            "schema_version": "inline_realign_live_status_v2_resumable",
            "updated_at": finished, "stage": name, "status": status,
            "returncode": returncode, "log": str(log_path),
        })
        print(f"[pipeline] END {name} rc={returncode} status={status}", flush=True)
        if not accepted:
            raise RuntimeError(f"stage {name} failed or missed expected artifacts; see {log_path}")
        return returncode
    except Exception as exc:
        state.finish_stage(
            name, status="failed", request_hash=request_hash, outputs=expected_outputs,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("smoke", "formal"), required=True)
    p.add_argument("--config", type=Path)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--demo-root", type=Path)
    p.add_argument("--demo-recursive", action="store_true")
    p.add_argument("--require-demo", action="store_true")
    p.add_argument("--demo-prepared-suffixes", default="_qwen_fa,_qwen_fa_decoder_realign,_qwen_fa_raw_guarded")
    p.add_argument("--mir1k-subset-root", type=Path, required=True)
    p.add_argument("--mir1k-audio-variant", choices=("official_vocal", "demucs", "mix"), default="official_vocal")
    p.add_argument("--mir1k-demucs-model", default="htdemucs_ft")
    p.add_argument("--include-heldout", action="store_true")
    p.add_argument("--mir1k-roles")
    p.add_argument("--materialize-missing-mir1k", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--m4-labels", type=Path, required=True)
    p.add_argument("--m4-audio-root", type=Path, required=True)
    p.add_argument("--m4-splits", default="validation")
    p.add_argument("--m4-long-target-secs", default="60,120,180")
    p.add_argument("--model", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--r2-checkpoint", type=Path, required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--local-files-only", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--evidence-cap-mib", type=float, default=12.0)
    p.add_argument("--evidence-max-cases-per-item", type=int, default=4)
    p.add_argument("--max-shadow-cases-per-item", type=int)
    p.add_argument("--max-gt-oracle-cases-per-item", type=int)
    p.add_argument("--max-stable-window-trials-per-item", type=int)
    p.add_argument("--max-expansion-trials-per-item", type=int)
    p.add_argument("--max-clean-control-cases-per-item", type=int)
    p.add_argument("--max-pending-shadow-cases-per-item", type=int)
    p.add_argument("--max-tail-rollback-cases-per-item", type=int)
    p.add_argument("--demo-cap", type=int)
    p.add_argument("--demo-per-language-cap", type=int)
    p.add_argument("--mir1k-cap", type=int)
    p.add_argument("--m4-native-cap", type=int)
    p.add_argument("--m4-long-cap", type=int)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--render-profile", choices=("review", "final"), default="review")
    p.add_argument("--render-incomplete", action="store_true")
    p.add_argument("--render-mode", choices=("after", "skip"), default="after")
    p.add_argument("--demo-publish-layout", choices=("central", "adjacent", "directory"), default="central")
    p.add_argument("--demo-publish-root", type=Path)
    p.add_argument("--primary-variant", default="B4_60_silence_official")
    p.add_argument(
        "--baseline-matrix-variants",
        default="B0_60_fixed_official,B1_30_fixed_official,B2_30_silence_official,B3_30_silence_raw_control,B4_60_silence_official,B5_30_strict_silence_official,B6_60_strict_silence_official,C0_30_silence_compressed_diagnostic,C1_60_silence_compressed_diagnostic",
    )
    p.add_argument("--comparison-branches", default="B0_60_fixed_official,B4_60_silence_official,C1_60_silence_compressed_diagnostic,B6_60_strict_silence_official")
    p.add_argument("--timeline-page-seconds", type=float, default=30.0)
    p.add_argument("--stable-left-overlap-units", type=int, default=8, help=argparse.SUPPRESS)
    p.add_argument("--deferred-max-windows", type=int, default=3)
    p.add_argument("--deferred-max-seconds", type=float, default=120.0)
    p.add_argument("--deferred-max-units", type=int, default=320)
    p.add_argument("--text-dosage-end-deltas", default="-8,-4,-2,0,2,4,8,16")
    p.add_argument("--text-dosage-start-deltas", default="-4,-2,0,2,4")
    p.add_argument("--inline-shadow", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--stable-window-assistance", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--text-dosage-trials", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--pending-confirmation-shadow", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--strict-silence-boundary-sec", type=float, default=1.5)
    p.add_argument("--silence-compression-min-sec", type=float, default=1.5)
    p.add_argument("--silence-compression-padding-sec", type=float, default=0.20)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--retry-failed-only", action="store_true")
    p.add_argument("--restart-item", action="append", default=[])
    p.add_argument("--from-stage", choices=("manifest", "experiment", "summary", "visualization", "collection", "video_pages", "render"))
    p.add_argument("--invalidate-stage", action="append", default=[])
    p.add_argument("--force", action="store_true")
    return p


def _apply_config(args: argparse.Namespace, argv: list[str]) -> dict[str, Any]:
    supplied = supplied_flags(argv)
    payload: dict[str, Any] = {}
    if args.config is None:
        return payload
    payload = load_yaml(args.config)
    configured_mode = get_path(payload, "mode")
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
        ("--max-expansion-trials-per-item", "max_expansion_trials_per_item", "shadow.text_dosage_trials_per_item"),
        ("--max-pending-shadow-cases-per-item", "max_pending_shadow_cases_per_item", "shadow.pending_cases_per_item"),
        ("--max-tail-rollback-cases-per-item", "max_tail_rollback_cases_per_item", "shadow.tail_rollback_cases_per_item"),
        ("--evidence-cap-mib", "evidence_cap_mib", "collection.max_total_mib"),
        ("--evidence-max-cases-per-item", "evidence_max_cases_per_item", "collection.max_cases_per_item"),
        ("--render-profile", "render_profile", "visualization.render_profile"),
        ("--timeline-page-seconds", "timeline_page_seconds", "visualization.timeline_page_seconds"),
        ("--render-mode", "render_mode", "visualization.render_mode"),
        ("--deferred-max-windows", "deferred_max_windows", "shadow.deferred_realign.max_windows"),
        ("--deferred-max-seconds", "deferred_max_seconds", "shadow.deferred_realign.max_seconds"),
        ("--deferred-max-units", "deferred_max_units", "shadow.deferred_realign.max_units"),
        ("--strict-silence-boundary-sec", "strict_silence_boundary_sec", "window_parameters.strict_silence_boundary_sec"),
        ("--silence-compression-min-sec", "silence_compression_min_sec", "window_parameters.silence_compression_min_sec"),
        ("--silence-compression-padding-sec", "silence_compression_padding_sec", "window_parameters.silence_compression_padding_sec"),
    ]
    for flag, attribute, key in mappings:
        apply_if_unsupplied(args, supplied=supplied, flag=flag, attribute=attribute, value=get_path(payload, key))
    roles = get_path(payload, "selection.mir1k_roles")
    if roles and "--mir1k-roles" not in supplied:
        args.mir1k_roles = ",".join(str(value) for value in roles)
    targets = get_path(payload, "selection.m4singer_synthetic_long_target_seconds")
    if targets and "--m4-long-target-secs" not in supplied:
        args.m4_long_target_secs = ",".join(str(value) for value in targets)
    primary_variant = get_path(payload, "variants.primary")
    if primary_variant and "--primary-variant" not in supplied:
        args.primary_variant = str(primary_variant)
    matrix_variants = list(get_path(payload, "variants.window_matrix") or [])
    raw_control = get_path(payload, "variants.raw_control")
    if raw_control and str(raw_control) not in {str(value) for value in matrix_variants}:
        matrix_variants.append(str(raw_control))
    if matrix_variants and "--baseline-matrix-variants" not in supplied:
        args.baseline_matrix_variants = ",".join(str(value) for value in matrix_variants)
    branches = get_path(payload, "visualization.comparison_branches")
    if branches and "--comparison-branches" not in supplied:
        args.comparison_branches = ",".join(str(value) for value in branches)
    end_deltas = get_path(payload, "shadow.text_dosage.end_deltas")
    if end_deltas and "--text-dosage-end-deltas" not in supplied:
        args.text_dosage_end_deltas = ",".join(str(value) for value in end_deltas)
    start_deltas = get_path(payload, "shadow.text_dosage.start_deltas")
    if start_deltas and "--text-dosage-start-deltas" not in supplied:
        args.text_dosage_start_deltas = ",".join(str(value) for value in start_deltas)
    boolean_mappings = [
        ("--inline-shadow", "inline_shadow", "shadow.enabled", True),
        ("--stable-window-assistance", "stable_window_assistance", "shadow.stable_anchor.enabled", True),
        ("--text-dosage-trials", "text_dosage_trials", "shadow.text_dosage.enabled", True),
        ("--pending-confirmation-shadow", "pending_confirmation_shadow", "shadow.deferred_realign.enabled", True),
    ]
    for flag,attribute,key,default in boolean_mappings:
        value=get_path(payload,key,default)
        if flag not in supplied and f"--no-{flag[2:]}" not in supplied:
            setattr(args,attribute,bool(value))
    # Reject unsupported semantic changes rather than silently ignoring YAML.
    contracts = {
        "shadow.automatic_writeback": False,
        "shadow.local_context_units": [0, 2, 4],
        "shadow.stable_anchor.audio_text_synchronized": True,
        "shadow.stable_anchor.variants": ["anchor_only", "sync_exact", "sync_minus2", "sync_minus4"],
        "shadow.deferred_realign.immediate_inline": True,
        "shadow.deferred_realign.delayed_after_anchor_recovery": True,
        "shadow.deferred_realign.bounded_final_sweep": True,
        "visualization.enabled": True,
        "visualization.character_rainbow": True,
        "visualization.duration_distribution": "discrete_pmf_including_negative_zero_positive",
    }
    for key,expected in contracts.items():
        value=get_path(payload,key,expected)
        if value != expected:
            raise ValueError(f"unsupported config change {key}={value!r}; expected {expected!r}")
    return payload


def main() -> int:
    argv = sys.argv[1:]
    args = parser().parse_args(argv)
    config_payload = _apply_config(args, argv)
    root = args.out_root.expanduser().resolve(); root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "experiment_manifest.jsonl"
    summary_path = root / "followup_analysis_summary.json"
    summary_md_path = root / "followup_analysis_summary.md"
    evidence_path = root / "inline_realign_evidence.tar.gz"
    status_path = root / "pipeline_status.jsonl"
    state = RunState(root)

    # Freeze only files that can change model inference, serial planning or the
    # experiment artifact schema.  Presentation code has its own stage identity;
    # changing plots or video encoding must not invalidate expensive old model runs.
    implementation_files = [
        ROOT / "scripts/demo/run_inline_realign_experiment.py",
        ROOT / "scripts/demo/align_qwen_fa_serial_demo.py",
        ROOT / "scripts/demo/build_inline_realign_manifest.py",
        ROOT / "src/lyricalign/demo/window_planning.py",
        ROOT / "src/lyricalign/demo/inline_realign.py",
        ROOT / "src/lyricalign/demo/alignment_artifacts.py",
    ]
    presentation_files = [
        ROOT / "scripts/demo/run_inline_realign_pipeline.py",
        ROOT / "scripts/demo/analyze_inline_realign_visuals.py",
        ROOT / "scripts/demo/render_inline_realign_demo_batch.py",
        ROOT / "src/lyricalign/demo/visual_diagnostics.py",
        ROOT / "src/lyricalign/demo/timeline_video.py",
        ROOT / "scripts/demo/summarize_inline_realign_followup.py",
        ROOT / "scripts/demo/collect_inline_realign_evidence.py",
    ]
    run_identity = {
        "schema_version": "inline_realign_pipeline_identity_v1",
        "mode": args.mode,
        "config": config_payload,
        "demo_root": None if args.demo_root is None else str(args.demo_root.expanduser().resolve()),
        "mir1k_subset_root": str(args.mir1k_subset_root.expanduser().resolve()),
        "m4_labels": file_identity(args.m4_labels),
        "m4_audio_root": str(args.m4_audio_root.expanduser().resolve()),
        "model": str(args.model), "revision": args.revision,
        "r2_checkpoint": str(args.r2_checkpoint.expanduser().resolve()),
        "device": args.device,
        "selection": {
            "demo_cap": args.demo_cap, "demo_per_language_cap": args.demo_per_language_cap,
            "mir1k_cap": args.mir1k_cap, "m4_native_cap": args.m4_native_cap,
            "m4_long_cap": args.m4_long_cap, "m4_long_target_secs": args.m4_long_target_secs,
            "include_heldout": args.include_heldout,
        },
        "experiment": {
            "primary_variant": args.primary_variant,
            "baseline_matrix_variants": args.baseline_matrix_variants,
            "max_shadow": args.max_shadow_cases_per_item,
            "max_oracle": args.max_gt_oracle_cases_per_item,
            "max_stable": args.max_stable_window_trials_per_item,
            "max_text_dosage": args.max_expansion_trials_per_item,
            "max_clean": args.max_clean_control_cases_per_item,
            "max_deferred": args.max_pending_shadow_cases_per_item,
            "text_dosage_end_deltas": args.text_dosage_end_deltas,
            "text_dosage_start_deltas": args.text_dosage_start_deltas,
            "inline_shadow": args.inline_shadow,
            "stable_window_assistance": args.stable_window_assistance,
            "text_dosage_trials": args.text_dosage_trials,
            "pending_confirmation_shadow": args.pending_confirmation_shadow,
            "strict_silence_boundary_sec": args.strict_silence_boundary_sec,
            "silence_compression_min_sec": args.silence_compression_min_sec,
            "silence_compression_padding_sec": args.silence_compression_padding_sec,
        },
        "experiment_implementation": _script_identity(implementation_files),
    }
    state.initialize(run_identity, resume=args.resume)
    for stage_name in args.invalidate_stage:
        state.invalidate_stage(stage_name)
    state.set_run_status("running", mode=args.mode)

    request_record = {
        "schema_version": "inline_realign_pipeline_request_v4_resumable_full_suite",
        "created_at": utc_now(), "run_identity_hash": canonical_hash(run_identity),
        "effective": vars(args), "config": config_payload,
        "presentation_implementation": _script_identity(presentation_files),
    }
    serializable = json.loads(json.dumps(request_record, default=str))
    atomic_json(root / "pipeline_request.json", serializable)
    atomic_json(root / "resolved_config.json", {
        "schema_version": "inline_realign_resolved_config_v2",
        "source_config_path": None if args.config is None else str(args.config.expanduser().resolve()),
        "source_config": config_payload,
        "effective": json.loads(json.dumps(vars(args), default=str)),
    })

    max_shadow = args.max_shadow_cases_per_item if args.max_shadow_cases_per_item is not None else (4 if args.mode == "smoke" else 12)
    max_oracle = args.max_gt_oracle_cases_per_item if args.max_gt_oracle_cases_per_item is not None else (2 if args.mode == "smoke" else 5)
    max_stable = args.max_stable_window_trials_per_item if args.max_stable_window_trials_per_item is not None else (2 if args.mode == "smoke" else 5)
    max_dosage = args.max_expansion_trials_per_item if args.max_expansion_trials_per_item is not None else (2 if args.mode == "smoke" else 5)
    max_clean = args.max_clean_control_cases_per_item if args.max_clean_control_cases_per_item is not None else (1 if args.mode == "smoke" else 3)
    max_pending = args.max_pending_shadow_cases_per_item if args.max_pending_shadow_cases_per_item is not None else (2 if args.mode == "smoke" else 5)
    max_tail = args.max_tail_rollback_cases_per_item if args.max_tail_rollback_cases_per_item is not None else 0
    mir1k_roles = args.mir1k_roles or ("development" if args.mode == "smoke" else "development,quick_v2_extra,spare")

    stages = ["manifest", "experiment", "summary", "visualization", "collection", "video_pages", "render"]
    from_index = stages.index(args.from_stage) if args.from_stage else 0
    partial_failure = False
    render_failure = False
    try:
        if from_index <= 0:
            command = [
                args.python_bin, "scripts/demo/build_inline_realign_manifest.py",
                "--mode", args.mode, "--out-root", str(root), "--output", str(manifest_path),
                "--mir1k-subset-root", str(args.mir1k_subset_root.expanduser().resolve()),
                "--mir1k-audio-variant", args.mir1k_audio_variant,
                "--mir1k-demucs-model", args.mir1k_demucs_model,
                "--m4-labels", str(args.m4_labels.expanduser().resolve()),
                "--m4-audio-root", str(args.m4_audio_root.expanduser().resolve()),
                "--m4-splits", args.m4_splits, "--m4-long-target-secs", args.m4_long_target_secs,
                "--demo-prepared-suffixes", args.demo_prepared_suffixes, "--mir1k-roles", mir1k_roles,
            ]
            if args.demo_root is not None: command += ["--demo-root", str(args.demo_root.expanduser().resolve())]
            if args.demo_recursive: command.append("--demo-recursive")
            if args.require_demo: command.append("--require-demo")
            for flag, value in (("--demo-cap", args.demo_cap), ("--demo-per-language-cap", args.demo_per_language_cap), ("--mir1k-cap", args.mir1k_cap), ("--m4-native-cap", args.m4_native_cap), ("--m4-long-cap", args.m4_long_cap)):
                if value is not None: command += [flag, str(value)]
            if args.include_heldout: command.append("--include-heldout")
            command.append("--materialize-missing-mir1k" if args.materialize_missing_mir1k else "--no-materialize-missing-mir1k")
            run_stage(name="manifest", command=command, root=root, status_path=status_path, state=state,
                      request={"command": command, "config": config_payload.get("selection")},
                      expected_outputs=[manifest_path, root / "input_audit.json"], resume=args.resume)
        elif not manifest_path.is_file():
            raise FileNotFoundError(f"--from-stage requires existing {manifest_path}")

        if from_index <= 1:
            command = [
                args.python_bin, "scripts/demo/run_inline_realign_experiment.py",
                "--manifest", str(manifest_path), "--out-root", str(root),
                "--model", str(args.model), "--revision", args.revision,
                "--r2-checkpoint", str(args.r2_checkpoint.expanduser().resolve()), "--device", args.device,
                "--primary-variant", args.primary_variant,
                "--baseline-matrix-variants", args.baseline_matrix_variants,
                "--max-shadow-cases-per-item", str(max_shadow),
                "--max-gt-oracle-cases-per-item", str(max_oracle),
                "--max-stable-window-trials-per-item", str(max_stable),
                "--max-text-dosage-trials-per-item", str(max_dosage),
                "--max-clean-control-cases-per-item", str(max_clean),
                "--max-pending-shadow-cases-per-item", str(max_pending),
                "--max-tail-rollback-cases-per-item", str(max_tail),
                "--stable-left-overlap-units", str(args.stable_left_overlap_units),
                "--deferred-max-windows", str(args.deferred_max_windows),
                "--deferred-max-seconds", str(args.deferred_max_seconds),
                "--deferred-max-units", str(args.deferred_max_units),
                option_assignment("--text-dosage-end-deltas", args.text_dosage_end_deltas),
                option_assignment("--text-dosage-start-deltas", args.text_dosage_start_deltas),
                "--strict-silence-boundary-sec", str(args.strict_silence_boundary_sec),
                "--silence-compression-min-sec", str(args.silence_compression_min_sec),
                "--silence-compression-padding-sec", str(args.silence_compression_padding_sec),
            ]
            if not args.inline_shadow: command.append("--disable-inline-shadow")
            if not args.stable_window_assistance: command.append("--disable-stable-window-assistance")
            if not args.text_dosage_trials: command.append("--disable-text-dosage-trials")
            if not args.pending_confirmation_shadow: command.append("--disable-pending-confirmation-shadow")
            if args.cache_dir is not None: command += ["--cache-dir", str(args.cache_dir.expanduser().resolve())]
            command.append("--local-files-only" if args.local_files_only else "--no-local-files-only")
            if args.resume: command.append("--resume")
            if args.retry_failed_only: command.append("--retry-failed-only")
            for item_id in args.restart_item: command += ["--restart-item", item_id]
            if experiment_force_requested(force=args.force, invalidated_stages=args.invalidate_stage):
                command.append("--force")
            rc = run_stage(name="experiment", command=command, root=root, status_path=status_path, state=state,
                           request={"command": command, "manifest": file_identity(manifest_path)},
                           expected_outputs=[root / "experiment_summary.json", root / "complete.json"],
                           resume=args.resume, allowed_returncodes={0, 1},
                           allow_stage_resume_skip=False)
            partial_failure |= rc == 1
        elif not (root / "experiment_summary.json").is_file():
            raise FileNotFoundError("experiment_summary.json is required")

        if from_index <= 2:
            command = [args.python_bin, "scripts/demo/summarize_inline_realign_followup.py", str(root), "--output", str(summary_path), "--markdown-output", str(summary_md_path)]
            run_stage(name="summary", command=command, root=root, status_path=status_path, state=state,
                      request={"command": command, "experiment": file_identity(root / "experiment_summary.json")},
                      expected_outputs=[summary_path, summary_md_path], resume=args.resume)

        if from_index <= 3:
            command = [
                args.python_bin, "scripts/demo/analyze_inline_realign_visuals.py",
                "--manifest", str(manifest_path), "--experiment-root", str(root),
                "--timeline-page-seconds", str(args.timeline_page_seconds),
                "--behavior-page-seconds", str(args.timeline_page_seconds),
                "--comparison-branches", args.comparison_branches, "--font", args.font,
                "--video-pages-mode", "off",
            ]
            if args.resume: command.append("--resume")
            for item_id in args.restart_item: command += ["--restart-item", item_id]
            if args.force or "visualization" in args.invalidate_stage: command.append("--force")
            rc = run_stage(name="visualization", command=command, root=root, status_path=status_path, state=state,
                           request={"command": command, "experiment": file_identity(root / "experiment_summary.json")},
                           expected_outputs=[root / "visualization_summary.json"], resume=args.resume,
                           allowed_returncodes={0, 1}, allow_stage_resume_skip=False)
            partial_failure |= rc == 1

        if from_index <= 4:
            command = [
                args.python_bin, "scripts/demo/collect_inline_realign_evidence.py", str(root),
                "--output", str(evidence_path), "--max-total-mib", str(args.evidence_cap_mib),
                "--max-cases-per-item", str(args.evidence_max_cases_per_item),
            ]
            run_stage(name="collection", command=command, root=root, status_path=status_path, state=state,
                      request={
                          "command": command,
                          "summary": file_identity(summary_path),
                          "visualization": file_identity(root / "visualization_summary.json"),
                      },
                      expected_outputs=[evidence_path], resume=args.resume)

        analysis_complete_path = root / "analysis_complete.json"
        if from_index <= 4:
            analysis_complete = {
                "schema_version": "inline_realign_analysis_complete_v1",
                "created_at": utc_now(), "status": "partial_failure" if partial_failure else "complete",
                "render_status": "deferred" if args.render_mode == "skip" else "pending",
                "experiment_summary": str(root / "experiment_summary.json"),
                "analysis_summary": str(summary_path), "evidence": str(evidence_path),
                "resume_command": "rerun the same smoke/formal entry with --resume",
            }
            atomic_json(analysis_complete_path, analysis_complete)
            state.set_run_status("analysis_complete", partial_failure=partial_failure)
        else:
            analysis_complete = json.loads(analysis_complete_path.read_text(encoding="utf-8"))                 if analysis_complete_path.is_file() else {}
            if not analysis_complete:
                raise FileNotFoundError(
                    f"--from-stage {args.from_stage} requires existing {analysis_complete_path}"
                )
            partial_failure = analysis_complete.get("status") == "partial_failure"

        if args.render_mode == "skip":
            atomic_json(root / "render_complete.json", {
                "schema_version": "inline_realign_render_complete_v1",
                "created_at": utc_now(), "status": "deferred",
                "resume_command": "rerun the same entry with RESUME=1 FROM_STAGE=render RENDER_MODE=after",
                "analysis_complete": str(root / "analysis_complete.json"),
            })

        if args.render_mode == "after" and from_index <= 5:
            command = [
                args.python_bin, "scripts/demo/analyze_inline_realign_visuals.py",
                "--manifest", str(manifest_path), "--experiment-root", str(root),
                "--timeline-page-seconds", str(args.timeline_page_seconds),
                "--behavior-page-seconds", str(args.timeline_page_seconds),
                "--comparison-branches", args.comparison_branches, "--font", args.font,
                "--video-pages-mode", "on", "--video-pages-only",
            ]
            if args.resume: command.append("--resume")
            for item_id in args.restart_item: command += ["--restart-item", item_id]
            if args.force or "video_pages" in args.invalidate_stage or "visualization" in args.invalidate_stage:
                command.append("--force")
            rc = run_stage(
                name="video_pages", command=command, root=root, status_path=status_path, state=state,
                request={
                    "command": command,
                    "experiment": file_identity(root / "experiment_summary.json"),
                    "analysis_complete": file_identity(root / "analysis_complete.json"),
                },
                expected_outputs=[root / "visualization_summary.json"], resume=args.resume,
                allowed_returncodes={0, 1}, allow_stage_resume_skip=False,
            )
            partial_failure |= rc == 1

        if args.render_mode == "after" and from_index <= 6:
            command = [
                args.python_bin, "scripts/demo/render_inline_realign_demo_batch.py",
                "--manifest", str(manifest_path), "--experiment-root", str(root),
                "--font", args.font, "--profile", args.render_profile,
                "--comparison-branches", args.comparison_branches,
            ]
            if args.render_incomplete: command.append("--render-incomplete")
            if args.resume: command.append("--resume")
            for item_id in args.restart_item: command += ["--restart-item", item_id]
            if args.force or "render" in args.invalidate_stage: command.append("--force")
            try:
                rc = run_stage(name="render", command=command, root=root, status_path=status_path, state=state,
                               request={"command": command, "visualization": file_identity(root / "visualization_summary.json")},
                               expected_outputs=[root / "demo_render_summary.json"], resume=args.resume,
                               allowed_returncodes={0, 1}, allow_stage_resume_skip=False)
                render_failure = rc == 1
            except Exception as exc:
                render_failure = True
                atomic_json(root / "render_complete.json", {
                    "schema_version": "inline_realign_render_complete_v1",
                    "created_at": utc_now(), "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "analysis_complete_available": (root / "analysis_complete.json").is_file(),
                })
            if render_failure:
                atomic_json(root / "render_complete.json", {
                    "schema_version": "inline_realign_render_complete_v1",
                    "created_at": utc_now(), "status": "partial_failure",
                    "summary": str(root / "demo_render_summary.json") if (root / "demo_render_summary.json").is_file() else None,
                    "analysis_complete": str(root / "analysis_complete.json"),
                    "resume_command": "rerun the same entry with RESUME=1 FROM_STAGE=render RENDER_MODE=after",
                })
            else:
                atomic_json(root / "render_complete.json", {
                    "schema_version": "inline_realign_render_complete_v1",
                    "created_at": utc_now(), "status": "complete",
                    "summary": str(root / "demo_render_summary.json"),
                    "analysis_complete": str(root / "analysis_complete.json"),
                })
            if not render_failure and args.demo_publish_layout != "central":
                publish = [args.python_bin, "scripts/demo/publish_inline_realign_demo_outputs.py", "--manifest", str(manifest_path), "--experiment-root", str(root), "--layout", args.demo_publish_layout]
                if args.demo_publish_root is not None: publish += ["--publish-root", str(args.demo_publish_root.expanduser().resolve())]
                if args.force: publish.append("--force")
                run_stage(name="publish", command=publish, root=root, status_path=status_path, state=state,
                          request={"command": publish, "render": file_identity(root / "demo_render_summary.json")},
                          expected_outputs=[root / "demo_publish_summary.json"], resume=args.resume)

        final_status = final_pipeline_status(
            render_mode=args.render_mode, partial_failure=partial_failure, render_failure=render_failure,
        )
        complete = {
            "schema_version": "inline_realign_pipeline_complete_v4_resumable_full_suite",
            "created_at": utc_now(), "status": final_status, "mode": args.mode,
            "analysis_complete": str(root / "analysis_complete.json"),
            "experiment_summary": str(root / "experiment_summary.json"),
            "analysis_summary": str(summary_path), "evidence": str(evidence_path),
            "visualization_summary": str(root / "visualization_summary.json"),
            "demo_render_summary": str(root / "demo_render_summary.json") if (root / "demo_render_summary.json").is_file() else None,
            "resume": "rerun the same entry command with --resume; completed items/stages are skipped only when identity and expected outputs match",
        }
        atomic_json(root / "pipeline_complete.json", complete)
        state.set_run_status(final_status, render_failure=render_failure, partial_failure=partial_failure)
        append_jsonl(status_path, {"time": utc_now(), "stage": "pipeline", "status": final_status})
        print(json.dumps(complete, ensure_ascii=False), flush=True)
        return 1 if partial_failure or render_failure else 0
    except Exception as exc:
        failure = {
            "schema_version": "inline_realign_pipeline_failure_v2_resumable",
            "created_at": utc_now(), "status": "failed",
            "error_type": type(exc).__name__, "error": str(exc),
            "analysis_complete_available": (root / "analysis_complete.json").is_file(),
        }
        atomic_json(root / "pipeline_failure.json", failure)
        state.set_run_status("failed", error=failure["error"])
        append_jsonl(status_path, {"time": utc_now(), "stage": "pipeline", "status": "failed", "error": str(exc)})
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
