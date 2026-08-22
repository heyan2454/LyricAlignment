#!/usr/bin/env python3
"""Extract a plain-text lyric slice from MIR-MLPop official JSON.

Useful for creating a short natural-pop smoke input from raw mixture audio.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotation", type=Path, required=True, help="MIR-MLPop official JSON")
    parser.add_argument("--song-id", required=True)
    parser.add_argument("--start-sec", type=float, default=0.0)
    parser.add_argument("--end-sec", type=float, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.annotation.read_text(encoding="utf-8"))
    rec = next((r for r in data if str(r.get("song_id")) == str(args.song_id)), None)
    if rec is None:
        raise SystemExit(f"song_id {args.song_id} not found")
    chars = []
    for row in rec.get("aligned_lyrics", []):
        start, end, text = float(row[0]), float(row[1]), str(row[2])
        if start < args.end_sec and end > args.start_sec:
            chars.append(text)
    text = "".join(chars)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "characters": len(text), "song_id": args.song_id, "range_sec": [args.start_sec, args.end_sec]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
