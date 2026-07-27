#!/usr/bin/env python3
"""Resumable smoke/overnight controller for multi-GPU decoders and realignment.

The controller avoids a Cartesian matrix:

1. cache Qwen/M4Singer timestamp evidence once;
2. train/evaluate TCN and Transformer on the same cache;
3. scan official, TCN and Transformer serial baselines;
4. build one union of natural anomalies;
5. run all three decoders on exact, then only escalate unresolved/disagreeing
   cases to +2 and +4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DECODERS = ("official", "gpu_tcn", "gpu_transformer")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def stage_status_path(out_root: Path, stage: str) -> Path:
    return out_root / "stage_status" / f"{stage}.json"


def run_stage(
    out_root: Path,
    stage: str,
    command: list[str],
    *,
    cwd: Path,
    force: bool,
    allow_empty_plan: Path | None = None,
) -> None:
    status_path = stage_status_path(out_root, stage)
    identity = {"stage": stage, "command": command, "cwd": str(cwd.resolve())}
    request_hash = canonical_hash(identity)
    if allow_empty_plan is not None and allow_empty_plan.is_file() and allow_empty_plan.stat().st_size == 0:
        atomic_json(status_path, {
            "status": "complete_empty_plan",
            "request_hash": request_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **identity,
        })
        return
    if not force and status_path.is_file():
        previous = json.loads(status_path.read_text(encoding="utf-8"))
        if previous.get("status") in {"complete", "complete_empty_plan"} and previous.get("request_hash") == request_hash:
            print(json.dumps({"stage": stage, "status": "skip_identity_match"}), flush=True)
            return
    log_path = out_root / "logs" / f"{stage}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(status_path, {
        "status": "running",
        "request_hash": request_hash,
        "started_at": datetime.now(timezone.utc).isoformat(),
        **identity,
    })
    print(json.dumps({"stage": stage, "status": "start", "command": shlex.join(command)}), flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            log.write(line)
            log.flush()
        rc = process.wait()
    atomic_json(status_path, {
        "status": "complete" if rc == 0 else "failed",
        "request_hash": request_hash,
        "return_code": rc,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "log": str(log_path.resolve()),
        **identity,
    })
    if rc != 0:
        raise RuntimeError(f"stage {stage} failed with rc={rc}; see {log_path}")


def ensure_reuse_links(stage_root: Path, baseline_root: Path) -> None:
    stage_root.mkdir(parents=True, exist_ok=True)
    for relative in ("evidence", "q1_anchor_scan"):
        target = baseline_root / relative
        link = stage_root / relative
        if link.exists() or link.is_symlink():
            if link.resolve() != target.resolve():
                raise RuntimeError(f"reuse link points elsewhere: {link}")
            continue
        link.symlink_to(target, target_is_directory=True)


def first_smoke_item(subset_root: Path) -> str:
    rows = read_jsonl(subset_root / "selection.jsonl")
    candidates = [row for row in rows if row.get("selection_role") == "development"]
    if not candidates:
        raise ValueError("smoke needs at least one development item")
    return str(sorted(candidates, key=lambda row: row.get("selection_order") or 0)[0]["item_id"])


def audit_inputs(args: argparse.Namespace) -> None:
    labels = read_jsonl(args.m4_labels)
    subset = read_jsonl(args.subset_root / "selection.jsonl")
    split_counts = Counter(str(row.get("split")) for row in labels)
    role_counts = Counter(str(row.get("selection_role")) for row in subset)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "m4singer": {
            "label_item_count": len(labels),
            "unique_song_count": len({str(row.get("song_id")) for row in labels}),
            "unique_singer_count": len({str(row.get("singer_id")) for row in labels}),
            "split_counts": dict(sorted(split_counts.items())),
            "character_count": sum(int(row.get("character_count", 0)) for row in labels),
            "interpretation": "item count is not natural-anomaly count; anomaly count is measured after baseline scans",
        },
        "mir1k_subset": {
            "item_count": len(subset),
            "role_counts": dict(sorted(role_counts.items())),
            "selected_roles": args.roles,
            "selected_audio_variants": args.audio_variants,
            "selected_core_sec": args.core_sec,
        },
        "execution_contract": {
            "decoder_training_device": args.device,
            "gpu_required": not args.allow_cpu_test,
            "decoder_families": ["official", "tcn", "transformer"],
            "shared_qwen_feature_cache": True,
            "realign_funnel": ["exact", "plus2", "plus4"],
            "cartesian_product_disabled": True,
        },
    }
    atomic_json(args.out_root / "input_audit.json", payload)


def checkpoint_for(args: argparse.Namespace, decoder_kind: str) -> Path | None:
    if decoder_kind == "gpu_tcn":
        return args.tcn_checkpoint
    if decoder_kind == "gpu_transformer":
        return args.transformer_checkpoint
    return None


def common_quick(args: argparse.Namespace, out_root: Path, decoder_kind: str, phases: list[str]) -> list[str]:
    command = [
        args.python_bin,
        "scripts/demo/run_demo_realign_quick.py",
        "--subset-root", str(args.subset_root),
        "--out-root", str(out_root),
        "--phase", *phases,
        "--roles", *args.roles,
        "--model-kind", "lora",
        "--checkpoint", str(args.r2_checkpoint),
        "--model", str(args.model),
        "--revision", args.revision,
        "--local-files-only",
        "--device", args.device,
        "--decoder-kind", decoder_kind,
        "--audio-variants", *args.audio_variants,
        "--core-sec", *[str(value) for value in args.core_sec],
        "--padding-sec", "0.5",
        "--matched-context-units", "2", "4",
        "--max-target-units", str(args.max_target_units),
        "--max-automatic-anchor-policies", str(args.max_anchor_policies),
        "--no-q2-require-context-agreement",
    ]
    checkpoint = checkpoint_for(args, decoder_kind)
    if checkpoint is not None:
        command.extend(["--gpu-decoder-checkpoint", str(checkpoint)])
    if args.mode == "smoke":
        command.extend(["--item-id", first_smoke_item(args.subset_root)])
    return command


def q2_stage_command(
    args: argparse.Namespace,
    out_root: Path,
    decoder_kind: str,
    plan: Path,
    profile: str,
) -> list[str]:
    return common_quick(args, out_root, decoder_kind, ["q2"]) + [
        "--q2-case-plan", str(plan),
        "--q2-trial-profile", profile,
    ]


def train_command(
    args: argparse.Namespace,
    cache_root: Path,
    architecture: str,
    run_dir: Path,
    steps: int,
    batch_size: int,
) -> list[str]:
    command = [
        args.python_bin, "scripts/demo/train_gpu_decoder.py",
        "--cache-root", str(cache_root),
        "--run-dir", str(run_dir),
        "--architecture", architecture,
        "--device", args.device,
        "--batch-size", str(batch_size),
        "--max-steps", str(steps),
        "--validation-every", str(max(1, min(100, steps))),
        "--save-every", str(max(1, min(100, steps))),
    ]
    if architecture == "transformer":
        command.extend([
            "--layers", str(args.transformer_layers),
            "--transformer-heads", str(args.transformer_heads),
            "--transformer-ffn-dim", str(args.transformer_ffn_dim),
        ])
    if args.mode == "smoke":
        command.extend(["--validation-fallback", "song_holdout"])
    if args.allow_cpu_test:
        command.append("--allow-cpu")
    if (run_dir / "last.pt").is_file():
        command.extend(["--resume", str(run_dir / "last.pt")])
    return command


def resolve_best(run_dir: Path) -> Path:
    best = run_dir / "best.pt"
    if best.is_file():
        return best
    last = run_dir / "last.pt"
    if last.is_file():
        return last
    raise FileNotFoundError(f"decoder checkpoint missing under {run_dir}")


def decoder_root_args(roots: dict[str, Path]) -> list[str]:
    result: list[str] = []
    for decoder, root in sorted(roots.items()):
        result.extend(["--decoder-root", f"{decoder}={root}"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "overnight"), required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--subset-root", type=Path, required=True)
    parser.add_argument("--m4-labels", type=Path, required=True)
    parser.add_argument("--m4-audio-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--r2-checkpoint", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--allow-cpu-test", action="store_true")
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--roles", nargs="+", default=["development", "quick_v2_extra"])
    parser.add_argument("--audio-variants", nargs="+", default=["demucs"])
    parser.add_argument("--core-sec", nargs="+", type=float, default=[30.0])
    parser.add_argument("--m4-max-items", type=int)
    parser.add_argument("--decoder-steps", type=int, help="Set both TCN and Transformer steps")
    parser.add_argument("--tcn-steps", type=int)
    parser.add_argument("--transformer-steps", type=int)
    parser.add_argument("--tcn-batch-size", type=int, default=64)
    parser.add_argument("--transformer-batch-size", type=int, default=32)
    parser.add_argument("--transformer-layers", type=int, default=4)
    parser.add_argument("--transformer-heads", type=int, default=6)
    parser.add_argument("--transformer-ffn-dim", type=int, default=768)
    parser.add_argument("--realign-max-cases", type=int)
    parser.add_argument("--max-target-units", type=int, default=8)
    parser.add_argument("--max-anchor-policies", type=int, default=1)
    parser.add_argument("--force-stage", action="append", default=[])
    args = parser.parse_args()

    args.repo_root = args.repo_root.resolve()
    args.out_root = args.out_root.resolve()
    args.subset_root = args.subset_root.resolve()
    args.m4_labels = args.m4_labels.resolve()
    args.m4_audio_root = args.m4_audio_root.resolve()
    args.r2_checkpoint = args.r2_checkpoint.resolve()
    args.out_root.mkdir(parents=True, exist_ok=True)
    default_steps = 8 if args.mode == "smoke" else 2500
    if args.decoder_steps is not None:
        args.tcn_steps = args.decoder_steps
        args.transformer_steps = args.decoder_steps
    args.tcn_steps = args.tcn_steps if args.tcn_steps is not None else default_steps
    args.transformer_steps = args.transformer_steps if args.transformer_steps is not None else default_steps
    if args.mode == "smoke":
        args.m4_max_items = args.m4_max_items if args.m4_max_items is not None else 16
        args.realign_max_cases = args.realign_max_cases if args.realign_max_cases is not None else 4
        args.audio_variants = args.audio_variants[:1]
        args.roles = ["development"]
        args.tcn_batch_size = min(args.tcn_batch_size, 8)
        args.transformer_batch_size = min(args.transformer_batch_size, 8)
    else:
        args.m4_max_items = args.m4_max_items if args.m4_max_items is not None else 0
        args.realign_max_cases = args.realign_max_cases if args.realign_max_cases is not None else 1000
    if not args.device.startswith("cuda") and not args.allow_cpu_test:
        raise RuntimeError("smoke/overnight decoder path is GPU-first; CUDA is required")

    cache_root = args.out_root / "decoder_cache"
    training_roots = {
        "gpu_tcn": args.out_root / "decoder_training" / "tcn",
        "gpu_transformer": args.out_root / "decoder_training" / "transformer",
    }
    evaluation_roots = {
        decoder: args.out_root / "decoder_evaluation" / decoder.removeprefix("gpu_")
        for decoder in training_roots
    }
    baseline_roots = {decoder: args.out_root / "baselines" / decoder for decoder in DECODERS}
    plans = args.out_root / "plans"
    force = set(args.force_stage)
    audit_inputs(args)

    cache_command = [
        args.python_bin, "scripts/demo/cache_gpu_decoder_features.py",
        "--model", str(args.model), "--revision", args.revision,
        "--checkpoint", str(args.r2_checkpoint), "--checkpoint-kind", "lora",
        "--labels", str(args.m4_labels), "--audio-root", str(args.m4_audio_root),
        "--out-root", str(cache_root), "--device", args.device,
        "--batch-size", "8", "--shard-items", "256", "--local-files-only",
        "--split", "train", "--split", "validation",
        "--min-items-per-split", "4" if args.mode == "smoke" else "1",
    ]
    if args.m4_max_items:
        cache_command.extend(["--max-items", str(args.m4_max_items)])
    if args.cache_dir:
        cache_command.extend(["--cache-dir", str(args.cache_dir)])
    run_stage(args.out_root, "01_decoder_cache", cache_command, cwd=args.repo_root, force="01_decoder_cache" in force)

    run_stage(
        args.out_root,
        "02_train_tcn",
        train_command(args, cache_root, "tcn", training_roots["gpu_tcn"], args.tcn_steps, args.tcn_batch_size),
        cwd=args.repo_root,
        force="02_train_tcn" in force,
    )
    args.tcn_checkpoint = resolve_best(training_roots["gpu_tcn"])
    run_stage(
        args.out_root,
        "03_train_transformer",
        train_command(
            args,
            cache_root,
            "transformer",
            training_roots["gpu_transformer"],
            args.transformer_steps,
            args.transformer_batch_size,
        ),
        cwd=args.repo_root,
        force="03_train_transformer" in force,
    )
    args.transformer_checkpoint = resolve_best(training_roots["gpu_transformer"])

    for stage_number, decoder in ((4, "gpu_tcn"), (5, "gpu_transformer")):
        eval_command = [
            args.python_bin, "scripts/demo/evaluate_gpu_decoder.py",
            "--cache-root", str(cache_root),
            "--checkpoint", str(checkpoint_for(args, decoder)),
            "--out-dir", str(evaluation_roots[decoder]),
            "--device", args.device,
        ]
        if args.mode == "overnight":
            eval_command.extend(["--split", "validation"])
        if args.allow_cpu_test:
            eval_command.append("--allow-cpu")
        stage = f"{stage_number:02d}_evaluate_{decoder.removeprefix('gpu_')}"
        run_stage(args.out_root, stage, eval_command, cwd=args.repo_root, force=stage in force)

    for stage_number, decoder in enumerate(DECODERS, start=6):
        stage = f"{stage_number:02d}_baseline_{decoder}"
        run_stage(
            args.out_root,
            stage,
            common_quick(args, baseline_roots[decoder], decoder, ["evidence", "q1"]),
            cwd=args.repo_root,
            force=stage in force,
        )

    exact_plan = plans / "exact.jsonl"
    union_command = [
        args.python_bin, "scripts/demo/build_realign_funnel.py",
        "--mode", "union",
        *decoder_root_args(baseline_roots),
        "--out-plan", str(exact_plan),
        "--max-cases", str(args.realign_max_cases),
        "--max-target-units", str(args.max_target_units),
    ]
    run_stage(args.out_root, "09_build_exact_union", union_command, cwd=args.repo_root, force="09_build_exact_union" in force)

    previous_plan = exact_plan
    previous_roots: dict[str, Path] | None = None
    stage_number = 10
    for profile in ("exact", "plus2", "plus4"):
        if profile != "exact":
            assert previous_roots is not None
            next_plan = plans / f"{profile}.jsonl"
            build_stage = f"{stage_number:02d}_build_{profile}_plan"
            escalation_command = [
                args.python_bin, "scripts/demo/build_realign_funnel.py",
                "--mode", "escalate",
                *decoder_root_args(previous_roots),
                "--previous-plan", str(previous_plan),
                "--next-stage", profile,
                "--out-plan", str(next_plan),
                "--max-cases", str(args.realign_max_cases),
            ]
            run_stage(args.out_root, build_stage, escalation_command, cwd=args.repo_root, force=build_stage in force)
            previous_plan = next_plan
            stage_number += 1
        current_roots = {
            decoder: args.out_root / "realign" / profile / decoder
            for decoder in DECODERS
        }
        for decoder in DECODERS:
            ensure_reuse_links(current_roots[decoder], baseline_roots[decoder])
            stage = f"{stage_number:02d}_{profile}_{decoder}"
            run_stage(
                args.out_root,
                stage,
                q2_stage_command(args, current_roots[decoder], decoder, previous_plan, profile),
                cwd=args.repo_root,
                force=stage in force,
                allow_empty_plan=previous_plan,
            )
            stage_number += 1
        previous_roots = current_roots

    collect_command = [
        args.python_bin, "scripts/demo/collect_demo_realign_overnight.py",
        "--out-root", str(args.out_root),
        "--archive", str(args.out_root / f"demo_realign_{args.mode}_compact.tar.gz"),
        "--max-archive-mib", "10",
    ]
    run_stage(args.out_root, "99_collect", collect_command, cwd=args.repo_root, force="99_collect" in force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
