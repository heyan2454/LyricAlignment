#!/usr/bin/env python3
"""Resumable one-click pipeline for the consolidated alignment research v6 suite.

Stages:
  manifest -> baseline(B4) -> pilot -> freeze -> formal -> visuals -> collect(full/light3m)

Pilot is deterministic and excludes held-out rows. Formal consumes every row in
its manifest.  The controller never silently caps a dataset in formal mode.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def run_stage(args: argparse.Namespace, name: str, command: list[str], outputs: list[Path], allowed_returncodes: set[int] | None = None) -> str:
    marker = args.out_root / "state" / f"{name}.json"
    if args.resume and marker.is_file() and all(path.exists() and path.stat().st_size > 0 for path in outputs):
        print(json.dumps({"stage": name, "status": "resume_skipped"}, ensure_ascii=False), flush=True)
        payload = json.loads(marker.read_text(encoding="utf-8"))
        return str(payload.get("status", "complete"))
    log = args.out_root / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(args.out_root / "run_status.jsonl", {"time": now(), "stage": name, "status": "running", "command": command})
    atomic_json(args.out_root / "live_status.json", {"time": now(), "stage": name, "status": "running", "log": str(log)})
    print(f"[research-v6] START {name}\n  {shlex.join(command)}\n  log={log}", flush=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"time": now(), "command": command}, ensure_ascii=False) + "\n")
        handle.flush()
        proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            handle.write(line); handle.flush(); print(line, end="", flush=True)
        rc = proc.wait()
    allowed = {0} if allowed_returncodes is None else set(allowed_returncodes)
    outputs_ok = all(path.exists() and path.stat().st_size > 0 for path in outputs)
    ok = rc in allowed and outputs_ok
    status = "complete" if rc == 0 and outputs_ok else "partial_failure" if ok else "failed"
    payload = {"time": now(), "stage": name, "status": status, "returncode": rc, "outputs": [str(p) for p in outputs]}
    atomic_json(marker, payload)
    append_jsonl(args.out_root / "run_status.jsonl", payload)
    atomic_json(args.out_root / "live_status.json", payload)
    if not ok:
        raise RuntimeError(f"stage {name} failed or outputs missing; see {log}")
    return status


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("smoke", "formal"), required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--demo-root", type=Path, required=True)
    p.add_argument("--demo-prepared-suffixes", default="_qwen_fa,_qwen_fa_decoder_realign,_qwen_fa_raw_guarded")
    p.add_argument("--mir1k-subset-root", type=Path, required=True)
    p.add_argument("--m4-labels", type=Path, required=True)
    p.add_argument("--m4-audio-root", type=Path, required=True)
    p.add_argument("--m4-splits", default="train,validation,test")
    p.add_argument("--m4-long-target-secs", default="60,120,180")
    p.add_argument("--model", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--r2-checkpoint", type=Path, required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--item-id", help="single manifest item; smoke uses this after manifest creation")
    p.add_argument("--pilot-items-per-dataset", type=int, default=2)
    p.add_argument("--formal-cases-per-item", type=int, default=0, help="eligible local windows per formal item; 0 means all")
    p.add_argument("--formal-max-chunk-groups-per-item", type=int, default=0, help="96-unit groups per formal item; 0 means all")
    p.add_argument("--formal-max-realign-cases-per-item", type=int, default=0, help="detector-requested realign cases per formal item; 0 means all")
    p.add_argument("--reuse-baseline-root", type=Path, help="completed immutable B4 baseline to verify and reuse in a new output root")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--skip-visuals", action="store_true")
    p.add_argument("--skip-collection", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    args.out_root = args.out_root.expanduser().resolve()
    args.out_root.mkdir(parents=True, exist_ok=True)
    py = str(Path(args.python_bin).expanduser())
    manifest = args.out_root / "manifest" / "experiment_manifest.jsonl"
    active_manifest = args.out_root / "manifest" / "active_manifest.jsonl"
    baseline = (args.reuse_baseline_root.expanduser().resolve() if args.reuse_baseline_root else args.out_root / "baseline")
    pilot = args.out_root / "pilot"
    frozen = args.out_root / "frozen_parameters.json"
    formal = args.out_root / "formal"
    report = args.out_root / "formal_report.md"
    visuals = args.out_root / "visuals"
    evidence = args.out_root / "evidence"

    # A smoke run selects one Demo item after manifest construction.  It must
    # therefore use the manifest builder's bounded smoke defaults; forcing the
    # formal zero-caps here eagerly materializes every M4Singer synthetic-long
    # item before the selection happens, which defeats smoke and can exhaust
    # the diagnostics volume.
    manifest_cmd = [
        py, "scripts/demo/build_inline_realign_manifest.py", "--mode", args.mode,
        "--out-root", str(args.out_root / "manifest"), "--output", str(manifest),
        "--demo-root", str(args.demo_root), "--demo-recursive", "--require-demo",
        "--demo-prepared-suffixes", args.demo_prepared_suffixes,
        "--mir1k-subset-root", str(args.mir1k_subset_root),
        "--m4-labels", str(args.m4_labels), "--m4-audio-root", str(args.m4_audio_root),
        "--m4-splits", args.m4_splits, "--m4-long-target-secs", args.m4_long_target_secs,
    ]
    if args.mode == "formal":
        manifest_cmd += [
            "--include-heldout", "--mir1k-roles", "development,quick_v2_extra,spare,heldout", "--mir1k-cap", "0",
            "--m4-native-cap", "0", "--m4-long-cap", "0",
        ]
    select_cmd = [py, "scripts/research/select_research_manifest.py", "--input", str(manifest), "--output", str(active_manifest), "--mode", args.mode]
    if args.item_id:
        select_cmd += ["--item-id", args.item_id]
    baseline_cmd = [
        py, "scripts/demo/run_inline_realign_experiment.py", "--manifest", str(active_manifest),
        "--out-root", str(baseline), "--model", args.model, "--revision", args.revision,
        "--r2-checkpoint", str(args.r2_checkpoint), "--device", args.device,
        "--primary-variant", "B4_60_silence_official", "--baseline-matrix-variants", "B4_60_silence_official",
        "--decoder-top-k", "8", "--disable-inline-shadow", "--disable-stable-window-assistance",
        "--disable-text-dosage-trials", "--disable-pending-confirmation-shadow", "--disable-tail-rollback-shadow",
        "--no-construct-incomplete-cases", "--compact-artifacts",
    ]
    if args.cache_dir: baseline_cmd += ["--cache-dir", str(args.cache_dir)]
    if args.resume: baseline_cmd += ["--resume"]

    common_suite = [
        "--manifest", str(active_manifest), "--baseline-root", str(baseline),
        "--model", args.model, "--revision", args.revision, "--r2-checkpoint", str(args.r2_checkpoint),
        "--device", args.device,
    ]
    if args.cache_dir: common_suite += ["--cache-dir", str(args.cache_dir)]
    pilot_cmd = [py, "scripts/research/run_alignment_research_suite.py", "--mode", "pilot", "--out-root", str(pilot),
                 "--pilot-items-per-dataset", str(args.pilot_items_per_dataset), "--cases-per-item", "1",
                 "--max-chunk-groups-per-item", "1", "--max-realign-cases-per-item", "2", *common_suite]
    formal_cmd = [py, "scripts/research/run_alignment_research_suite.py", "--mode", "formal", "--out-root", str(formal),
                  "--cases-per-item", str(args.formal_cases_per_item),
                  "--max-chunk-groups-per-item", str(args.formal_max_chunk_groups_per_item),
                  "--max-realign-cases-per-item", str(args.formal_max_realign_cases_per_item),
                  "--frozen-params", str(frozen), "--compact-artifacts", *common_suite]
    if args.item_id:
        pilot_cmd += ["--item-id", args.item_id]
        formal_cmd += ["--item-id", args.item_id]
    if args.resume:
        pilot_cmd += ["--resume"]; formal_cmd += ["--resume"]
    freeze_cmd = [py, "scripts/research/freeze_research_parameters.py", "--pilot-root", str(pilot), "--output", str(frozen)]
    report_cmd = [py, "scripts/research/summarize_research_v6.py", "--formal-root", str(formal), "--pilot-root", str(pilot), "--frozen-params", str(frozen), "--output", str(report)]
    visual_cmd = [py, "scripts/research/render_research_v6_visuals.py", "--formal-root", str(formal),
                  "--baseline-root", str(baseline), "--out-root", str(visuals)]
    collect_full = [py, "scripts/research/collect_research_evidence.py", "--run-root", str(args.out_root),
                    "--output", str(evidence / "alignment_research_v6_full.tar.gz"), "--profile", "full"]
    collect_light = [py, "scripts/research/collect_research_evidence.py", "--run-root", str(args.out_root),
                     "--output", str(evidence / "alignment_research_v6_light3m.tar.gz"), "--profile", "light3m"]

    stages = [
        ("manifest", manifest_cmd, [manifest, args.out_root / "manifest" / "input_audit.json"], {0}),
        ("active_manifest", select_cmd, [active_manifest, active_manifest.with_suffix(".audit.json")], {0}),
        ("pilot", pilot_cmd, [pilot / "complete.json", pilot / "research_summary.json"], {0, 3}),
        ("freeze", freeze_cmd, [frozen], {0}),
        ("formal", formal_cmd, [formal / "complete.json", formal / "research_summary.json"], {0, 3}),
        ("formal_report", report_cmd, [report], {0}),
    ]
    if args.reuse_baseline_root:
        required = [baseline / "complete.json", baseline / "experiment_summary.json"]
        if not all(path.is_file() and path.stat().st_size > 0 for path in required):
            raise FileNotFoundError(f"reusable baseline is incomplete: {baseline}")
        # The formal suite validates every requested item against this root
        # before inference.  Record the immutable source in the new run root.
        atomic_json(args.out_root / "baseline_reuse.json", {
            "baseline_root": str(baseline),
            "complete_sha256": __import__("hashlib").sha256((baseline / "complete.json").read_bytes()).hexdigest(),
        })
    else:
        stages.insert(2, ("baseline", baseline_cmd, [baseline / "complete.json", baseline / "experiment_summary.json"], {0, 3}))
    if not args.skip_visuals:
        stages.append(("visuals", visual_cmd, [visuals / "visual_index.md", visuals / "complete.json"], {0}))
    if not args.skip_collection:
        stages += [
            ("collect_full", collect_full, [evidence / "alignment_research_v6_full.tar.gz"], {0}),
            ("collect_light3m", collect_light, [evidence / "alignment_research_v6_light3m.tar.gz"], {0}),
        ]
    atomic_json(args.out_root / "pipeline_request.json", {"created_at": now(), "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}, "stages": [{"name": n, "command": c, "allowed_returncodes": sorted(allowed)} for n,c,_,allowed in stages]})
    if args.dry_run:
        for name, cmd, outputs, allowed in stages:
            print(json.dumps({"stage": name, "command": cmd, "outputs": [str(p) for p in outputs], "allowed_returncodes": sorted(allowed)}, ensure_ascii=False))
        return 0
    stage_statuses = {}
    for name, cmd, outputs, allowed in stages:
        stage_statuses[name] = run_stage(args, name, cmd, outputs, allowed)
    final_status = "partial_failure" if any(value == "partial_failure" for value in stage_statuses.values()) else "complete"
    atomic_json(args.out_root / "pipeline_complete.json", {"status": final_status, "stage_statuses": stage_statuses, "completed_at": now(), "formal_summary": str(formal / "research_summary.json")})
    print(json.dumps({"status": final_status, "out_root": str(args.out_root)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
