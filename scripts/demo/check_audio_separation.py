#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.audio_separation import evaluate_separation


def decode_mono(path: Path, *, sample_rate: int) -> np.ndarray:
    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-",
    ]
    completed = subprocess.run(command, check=True, stdout=subprocess.PIPE)
    return np.frombuffer(completed.stdout, dtype="<f4").copy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject silent or near-copy Spleeter 2-stem output.")
    parser.add_argument("--mix", type=Path, required=True)
    parser.add_argument("--vocals", type=Path, required=True)
    parser.add_argument("--accompaniment", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=16000)
    args = parser.parse_args()

    for path in (args.mix, args.vocals, args.accompaniment):
        if not path.is_file():
            raise SystemExit(f"missing audio file: {path}")

    mix = decode_mono(args.mix, sample_rate=args.sample_rate)
    vocals = decode_mono(args.vocals, sample_rate=args.sample_rate)
    accompaniment = decode_mono(args.accompaniment, sample_rate=args.sample_rate)
    diagnostics = evaluate_separation(
        mix,
        vocals,
        accompaniment,
        sample_rate=args.sample_rate,
    )
    payload = diagnostics.to_dict()
    payload.update(
        {
            "schema_version": "spleeter_separation_quality_v1",
            "mix": str(args.mix.resolve()),
            "vocals": str(args.vocals.resolve()),
            "accompaniment": str(args.accompaniment.resolve()),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.report)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if diagnostics.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
