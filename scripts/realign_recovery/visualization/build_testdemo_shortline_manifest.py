#!/usr/bin/env python3
"""Build SHORT-WINDOW (line-level) full-slot request manifests.

Each lyric LINE becomes one query window:

  - window units = every character of that line (6-23 units, far below the
    ~150-unit model safety line)
  - audio crop   = line span [first char start, last char end] padded by
    --pad-sec on both sides (clamped to the song, floored to --min-audio-sec)
  - full-slot    = every window unit is queried (timestamp_slot_indices ==
    the full window range)

This replicates the short-window regime of the 20260813 unit-realign
(audio crop mean 8.9s, 0-5 text units per window) that reached 812ms onset
MAE, to test the hypothesis that current 60s long-window full-slot quality
collapse is a window-size issue rather than a model issue.

Unit space / canonical ids / document are identical to the B4 alignment
(the same parse, same characters) — same contract as
build_testdemo_slot_variant_manifest.py, so run_testdemo_slot_infer.py
(Plan A, direct infer_slice) can consume the rows unchanged.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_testdemo_shortline_manifest.py \
      --songs "song=lang=b4_alignment.json=vocals.wav" ... \
      --out <manifest.jsonl> [--pad-sec 3.0] [--min-audio-sec 6.0]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", action="append", default=[],
                    help="song=lang=b4_alignment.json=vocals.wav")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--pad-sec", type=float, default=3.0)
    ap.add_argument("--min-audio-sec", type=float, default=6.0)
    args = ap.parse_args()

    rows = []
    for spec in args.songs:
        song, lang, align_path, vocal_path = spec.split("=")
        d = json.loads(Path(align_path).read_text(encoding="utf-8"))
        b4_chars = d["characters"]
        duration = max((float(c.get("selected_end_sec") or c.get("end_sec") or 0.0)
                        for c in b4_chars), default=0.0)
        units = []
        for c in b4_chars:
            units.append({
                "canonical_unit_id": int(c["global_character_index"]),
                "text": str(c.get("display_text") or c.get("character") or ""),
                "line_index": int(c.get("line_index", 0)),
                "index_in_line": int(c.get("index_in_line", 0)),
                "start_sec": float(c.get("selected_start_sec") or c.get("start_sec") or 0.0),
                "end_sec": float(c.get("selected_end_sec") or c.get("end_sec")
                                 or c.get("start_sec") or 0.0),
            })
        by_line: dict[int, list[dict]] = {}
        for u in units:
            by_line.setdefault(u["line_index"], []).append(u)
        all_cids = [u["canonical_unit_id"] for u in units]
        texts = [u["text"] for u in units]
        audio_sha = _sha(Path(vocal_path))
        align_sha = _sha(Path(align_path))
        n_win = 0
        for li in sorted(by_line):
            line_units = sorted(by_line[li], key=lambda u: u["index_in_line"])
            cids = [u["canonical_unit_id"] for u in line_units]
            # audio crop = line span + pad, clamped, floored to min length
            line_start = min(u["start_sec"] for u in line_units)
            line_end = max(u["end_sec"] for u in line_units)
            audio_s = max(0.0, line_start - args.pad_sec)
            audio_e = min(duration, line_end + args.pad_sec)
            if audio_e - audio_s < args.min_audio_sec:
                mid = (audio_s + audio_e) / 2.0
                half = args.min_audio_sec / 2.0
                audio_s = max(0.0, mid - half)
                audio_e = min(duration, mid + half)
            if audio_e <= audio_s:
                print(f"FAIL {song} L{li}: empty audio crop", flush=True)
                continue
            n_win += 1
            wstart = min(cids)
            wend = max(cids) + 1
            cid_set = set(cids)
            # full-slot: all window units
            slot_local = [i for i in range(wend - wstart) if (wstart + i) in cid_set]
            local = {cid: i for i, cid in enumerate(cids)}
            row = {
                "schema_version": "testdemo_shortline_manifest_v1",
                "request_id": f"{song}:L{li}:shortline",
                "item_id": f"{song}:L{li}:shortline",
                "song_id": song,
                "parent_request_id": None,
                "audio_source": str(Path(vocal_path).resolve()),
                "audio_start_sec": round(audio_s, 4),
                "audio_end_sec": round(audio_e, 4),
                "duration_sec": round(audio_e - audio_s, 4),
                "text_source": "testdemo_timeline",
                "text_start_index": 0,
                "text_end_index": len(texts),
                "text_units": texts,
                "timestamp_slot_indices": slot_local,
                "workflow_mode": "short_line_slot",
                "mutation_type": "baseline",
                "mutation_parameters": {"position": "whole", "requested_ratio": 0.0},
                "model_id": "Qwen3-ForcedAligner-0.6B-hf",
                "checkpoint_id": "r2-step-000750",
                "input_variant": "text_mutation",
                "language": lang,
                "canonical_text_start": min(all_cids),
                "canonical_text_end": max(all_cids) + 1,
                "canonical_to_local": {str(c): i for c, i in local.items()},
                "canonical_ids": all_cids,
                "window_unit_ids": cids,
                "canonical_timeline_file_sha": "sha256:" + align_sha,
                "timeline_align_path": str(Path(align_path).resolve()),
                "canonical_adapter_version": "testdemo_timeline_v1",
                "source_window_sec": [round(audio_s, 4), round(audio_e, 4)],
                "slot_plan_id": f"shortline:L{li}",
                "comparison_group_id": f"{song}:L{li}:shortline",
                "phase": "full",
                "audio_sha256": "sha256:" + audio_sha,
                "status": "ok",
                "core_start_sec": round(line_start, 4),
                "core_end_sec": round(line_end, 4),
                "window_index": li,
                "is_final_core": li == max(by_line),
                "variant": "shortline",
                "window_plan_policy": "line_window_pad%.1f" % args.pad_sec,
                "line_index": li,
                "line_unit_count": len(cids),
            }
            rows.append(row)
        print(f"{song}: {n_win} line windows, duration {duration:.1f}s", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
