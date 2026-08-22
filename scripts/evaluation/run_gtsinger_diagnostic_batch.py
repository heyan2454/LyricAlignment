#!/usr/bin/env python3
"""Run the GTSinger diagnostic batch through the existing serial demo.

Reads a JSONL manifest produced by build_gtsinger_diagnostic_manifest.py.
Skips items whose alignment matrix is already complete. This is a long-running
GPU/CPU batch; use --limit for a smoke.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_complete(out_dir: Path) -> bool:
    marker = out_dir / "alignment_matrix.complete.json"
    if not marker.is_file():
        return False
    # Require at least one r2 vocal windowed alignment as a practical completion signal.
    return (out_dir / "alignments/r2/vocal/windowed/alignment.json").is_file()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--r1-checkpoint", type=Path, required=True)
    parser.add_argument("--r2-checkpoint", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--limit", type=int, help="only run first N items")
    parser.add_argument("--extra", action="append", default=[], help="extra argument appended to serial demo command (can repeat)")
    parser.add_argument("--gate", action="store_true", help="run quality gate on r2/vocal/windowed after each item")
    args = parser.parse_args()

    rows = load_rows(args.manifest)
    if args.limit:
        rows = rows[: args.limit]
    args.out_root.mkdir(parents=True, exist_ok=True)
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    python = sys.executable

    for idx, row in enumerate(rows, 1):
        out_dir = args.out_root / str(row["item_id"])
        if is_complete(out_dir):
            print(f"[{idx}/{len(rows)}] skip {row['item_id']}", flush=True)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        lyrics = out_dir / "lyrics.txt"
        gt_json = Path(row["gt_json_abs"])
        audio = Path(row["audio_abs"])
        # Generate lyrics from GT JSON.
        subprocess.run([
            python, str(ROOT / "scripts/evaluation/build_gtsinger_lyrics.py"),
            "--json", str(gt_json), "--out", str(lyrics), "--join-lines",
        ], check=True, env=env)
        print(f"[{idx}/{len(rows)}] run {row['item_id']}", flush=True)
        subprocess.run([
            python, str(ROOT / "scripts/demo/align_qwen_fa_serial_demo.py"),
            "--lyrics", str(lyrics),
            "--mix-audio", str(audio),
            "--vocal-audio", str(audio),
            "--out-root", str(out_dir),
            "--model", args.model,
            "--revision", args.revision,
            "--r1-checkpoint", str(args.r1_checkpoint),
            "--r2-checkpoint", str(args.r2_checkpoint),
            "--device", args.device,
            "--language", "Chinese",
            "--core-sec", "20",
            "--left-context-sec", "0",
            "--right-context-sec", "0",
            "--minimum-forward-characters", "1",
            "--startup-minimum-forward-characters", "1",
            "--future-line-padding", "0",
            "--future-character-ratio", "1.0",
            "--max-candidate-expansions", "0",
            *args.extra,
        ], check=True, env=env)
        if args.gate:
            gate_alignment = out_dir / "alignments/r2/vocal/windowed/alignment.json"
            if gate_alignment.is_file():
                gate_out = out_dir / "quality_gate.json"
                subprocess.run([
                    python, str(ROOT / "scripts/evaluation/check_alignment_quality_gate.py"),
                    "--alignment", str(gate_alignment),
                    "--out", str(gate_out),
                ], check=False, env=env)
    print("ALL_DONE")


if __name__ == "__main__":
    main()
