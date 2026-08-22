#!/usr/bin/env python3
"""Build a PJS productization manifest with phoneme counts.

Reads PJS lab files and WAV durations, and joins with Evaluation V1 tier from
the split manifest.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import wave
from collections import defaultdict
from pathlib import Path

DEFAULT_DATASETS_ROOT = Path("/home/hyan/Data/datasets")


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--datasets-root", type=Path, default=DEFAULT_DATASETS_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = load_rows(args.manifest)
    tier_by_group = {}
    for row in rows:
        if row.get("dataset_id") == "pjs":
            tier_by_group[row["group_id"]] = row.get("tier")

    root = args.datasets_root / "pjs"
    corpus = root / "raw/extracted/PJS_corpus_ver1.1"
    out_rows = []
    for pid_dir in sorted(corpus.iterdir()):
        if not pid_dir.is_dir() or not pid_dir.name.startswith("pjs") or not pid_dir.name[3:].isdigit():
            continue
        pid = pid_dir.name
        lab = pid_dir / f"{pid}.lab"
        song_wav = pid_dir / f"{pid}_song.wav"
        speech_wav = pid_dir / f"{pid}_speech.wav"
        phonemes = []
        if lab.is_file():
            for line in lab.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] != "pau":
                    phonemes.append(parts[2])
        def wav_dur(p):
            try:
                with wave.open(str(p), "rb") as w:
                    return w.getnframes() / w.getframerate()
            except Exception:
                return None
        group_id = f"pjs_song_{pid}"
        out_rows.append({
            "dataset_id": "pjs",
            "item_id": f"pjs_{pid}",
            "group_id": group_id,
            "tier": tier_by_group.get(group_id),
            "song_id": pid,
            "song_wav_relpath": str(song_wav.relative_to(root)),
            "speech_wav_relpath": str(speech_wav.relative_to(root)),
            "lab_relpath": str(lab.relative_to(root)),
            "song_duration_sec": wav_dur(song_wav),
            "speech_duration_sec": wav_dur(speech_wav),
            "phoneme_count": len(phonemes),
            "phoneme_types": sorted(set(phonemes)),
        })
    atomic_jsonl(args.out, out_rows)
    print(json.dumps({"out": str(args.out), "pjs_items": len(out_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
