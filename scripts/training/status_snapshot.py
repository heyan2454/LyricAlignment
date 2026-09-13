#!/usr/bin/env python3
"""One-screen status snapshot for a running funnel-training job (cheap to call every 30 minutes).

Prints process liveness, step/epoch/ETA, the training-loss trend, the latest funnel validation
points (L1 rolling + newest L2/L3), disk headroom versus the weights-only fallback, and GPU usage.

    PYTHONPATH=src python scripts/training/status_snapshot.py --run-dir <run>
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

VARIANTS = ("fixed", "raw", "raw_targeted")
STEPS_PER_EPOCH = 17748 / 32


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def match_process(lines: list[str], run_dir: Path) -> tuple[str, str]:
    """Find the trainer for `run_dir`, strictly.

    A launcher shell whose command *text* mentions the script and the directory is not the trainer,
    so two conditions are required: the command is a python invocation, and `--run-dir <this dir>`
    appears as an adjacent argument pair.  (Observed bug: a queued `bash -c` carrying the whole
    here-document was reported as the live training process, with the wrong elapsed time.)
    """
    marker = f"--run-dir {run_dir}"
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, elapsed, args = parts
        if not args.strip().startswith(("python", "/python")) and "/python" not in args.split()[0]:
            continue
        if "run_qwen_fa_lora.py" not in args or marker not in args:
            continue
        try:
            return pid, f"{int(elapsed) / 3600:.2f}h"
        except ValueError:
            continue
    return "none", "-"


def process_status(run_dir: Path) -> tuple[str, str]:
    try:
        listing = subprocess.run(["ps", "-eo", "pid,etimes,args"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown", "unknown"
    return match_process(listing.stdout.splitlines(), run_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--tail", type=int, default=3, help="how many recent L1 points to show")
    args = parser.parse_args()
    run_dir = args.run_dir
    print(f"RUN {run_dir.name}")

    pid, elapsed = process_status(run_dir)
    print(f"process: pid={pid} alive={'YES' if pid not in {'none', 'unknown'} else 'NO'} elapsed={elapsed}")

    metrics = [row for row in read_jsonl(run_dir / "metrics.jsonl") if "step" in row and "training_loss" in row]
    cfg = {}
    config_path = run_dir / "config.yaml"
    if config_path.exists():
        import yaml
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    cap = int((cfg.get("stages", {}).get("r2", {}) or {}).get("max_steps", 0)) or 12000
    if metrics:
        last = metrics[-1]
        step, wall = int(last["step"]), float(last["wall_sec"])
        recent = metrics[-200:]
        older = [row for row in metrics if row["step"] <= step - 1000]
        rate = ((step - int(older[-1]["step"])) / (wall - float(older[-1]["wall_sec"]))) if older else 0.0
        eta = (cap - step) / rate / 3600 if rate > 0 else float("inf")
        finish = datetime.now(timezone.utc) + timedelta(hours=eta) if rate > 0 else None
        print(f"train: step {step}/{cap} ({100 * step / cap:.1f}%) epoch {last.get('epoch')} wall {wall / 3600:.2f}h "
              f"loss(last)={last['training_loss']:.4f} loss(last200)={statistics.mean(r['training_loss'] for r in recent):.4f} "
              f"lr={last.get('lr', float('nan')):.3g}")
        if older:
            delta = statistics.mean(r["training_loss"] for r in recent) - \
                statistics.mean(r["training_loss"] for r in older[-200:])
            print(f"rate: {rate * 3600:.0f} steps/h  eta_to_cap={eta:.1f}h"
                  + (f"  finish~{finish.astimezone().strftime('%m-%d %H:%M')}" if finish else "")
                  + f"  loss_delta_vs_1000_steps_ago={delta:+.4f}")
    else:
        print("train: no metrics yet")

    funnel = read_jsonl(run_dir / "funnel_evals.jsonl")
    l1 = [row["funnel_eval"] for row in funnel if (row.get("funnel_eval") or {}).get("level") == "l1"]
    for block in l1[-args.tail:]:
        summary = block.get("variants") or {}
        values = " ".join(f"{variant}={summary.get(variant, {}).get('macro_within_primary', float('nan')):.4f}"
                          for variant in VARIANTS)
        print(f"val L1 step {block['evaluated_step']}: {values} usable(fixed)="
              f"{summary.get('fixed', {}).get('usable_rate', float('nan')):.4f}")
    if not l1:
        print("val L1: none yet")
    for level in ("l2", "l3"):
        points = [row["funnel_eval"] for row in funnel if (row.get("funnel_eval") or {}).get("level") == level]
        if points:
            best = max(points, key=lambda block: (block.get("variants") or {}).get("fixed", {})
                       .get("macro_within_primary", -1))
            summary = best.get("variants") or {}
            values = " ".join(f"{variant}={summary.get(variant, {}).get('macro_within_primary', float('nan')):.4f}"
                              for variant in VARIANTS)
            print(f"val {level.upper()} n={len(points)} best step {best['evaluated_step']}: {values}")
    topup_path = run_dir / "topup_evals.jsonl"
    topup = read_jsonl(topup_path)
    if topup:
        print(f"topup: {len(topup)} extra evaluations (see TOPUP.json / results/by_run)")

    usage = shutil.disk_usage(run_dir)
    floor = float((cfg.get("training") or {}).get("disk_floor_gb", 20.0))
    mode = "full" if usage.free / 1e9 >= floor else "weights_only"
    print(f"disk: run_dir fs free {usage.free / 1e9:.1f}G floor {floor:.0f}G -> mode={mode}")
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        print(f"gpu: {gpu}")
    except (OSError, subprocess.SubprocessError):
        pass
    print(f"checked_at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
