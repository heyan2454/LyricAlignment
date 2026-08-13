#!/usr/bin/env python3
"""WP2 helper — transcode gallery/demo media that soundfile cannot open into WAV.

Root cause (U4, verified): the 3 failing Test Demo items ("Side by Side.mp4",
"祈愿花开.mp4", "夜苏打.mp4") fail at the detector media-open stage because
scripts/realign_gate/test_demo.py uses ``soundfile.read`` (sf.read), which does
not support mp4 containers. The files are not corrupt (ffprobe/ffmpeg read them).

This helper re-encodes a media file to mono 16 kHz float32 WAV so the
soundfile-based loader and the visualization audio pipeline can consume it.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/transcode_media_to_wav.py \
      --media <in.mp4> --out <song>.wav
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def transcode_to_wav(media: Path, out: Path, *, sample_rate: int = 16000) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(media),
        "-ac", "1", "-ar", str(sample_rate),
        "-c:a", "pcm_f32le",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sample-rate", type=int, default=16000)
    args = parser.parse_args()

    transcode_to_wav(args.media, args.out, sample_rate=args.sample_rate)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
