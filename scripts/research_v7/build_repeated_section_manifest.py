#!/usr/bin/env python3
"""Build C10 no-GT repeated-section cases from real demo lyric repetitions."""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

PUNCT = set("，。！？、,.!?;:：；()（）[]【】\"'“”‘’—-…")


def lyric_units(path: str) -> list[str]:
    return [c for c in Path(path).read_text(encoding="utf-8") if not c.isspace() and c not in PUNCT]


def duration(path: str) -> float:
    with wave.open(path, "rb") as f: return f.getnframes() / f.getframerate()


def repeat(units: list[str]) -> tuple[int, int, int] | None:
    for size in range(min(16, len(units)//2), 3, -1):
        seen = {}
        for start in range(len(units) - size + 1):
            key = tuple(units[start:start+size])
            if key in seen and start - seen[key] >= size: return seen[key], start, size
            seen.setdefault(key, start)
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--manifest", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args(argv); output = []
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if not line: continue
        r = json.loads(line)
        if r.get("dataset") != "demo" or r.get("gt_path") is not None: continue
        audio = Path(r["audio_path"]); lyrics = Path(r["lyrics_path"])
        if not audio.is_file() or not lyrics.is_file(): continue
        units = lyric_units(str(lyrics)); found = repeat(units)
        if not found: continue
        first, second, size = found; phrase = units[first:first+size]; total = duration(str(audio))
        common = {"item_id": r["item_id"], "song_id": r.get("source_song_id"), "source_song_id": r.get("source_song_id"), "dataset": "demo", "split": "demo_challenge", "language": r.get("language"), "gt_available": False, "audio_path": r["audio_path"], "text_source": r["lyrics_path"], "audio_start_sec": 0., "audio_end_sec": total, "duration_sec": total, "baseline_unit_count": size, "n_base": size, "audio_relation": "full_source_audio", "repeat_positions": [first, second], "repeat_unit_count": size, "provenance": {"repeat_detector": "exact_normalized_character_ngram"}}
        output.append({**common, "request_id": f"{r['item_id']}:C10:short-repeat", "mutation_type": "baseline", "text_relation": "ambiguous_repeated_section", "text_units": phrase})
        output.append({**common, "request_id": f"{r['item_id']}:C10:double-repeat", "mutation_type": "extra", "requested_ratio": 1., "actual_ratio": 1., "actual_added_units": size, "mutation_position": "tail", "position": "tail", "source": "same_song_repeat", "text_relation": "two_repeated_sections", "text_units": phrase + phrase})
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True); target.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in output),encoding="utf-8")
    print(json.dumps({"ok":True,"items":len({x['item_id'] for x in output}),"requests":len(output),"out":str(target)},ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
