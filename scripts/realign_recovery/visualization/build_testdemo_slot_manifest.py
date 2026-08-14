#!/usr/bin/env python3
"""Build long-slot (full-slot) requests for test-demo songs using the frozen
20260806 Base windowing: full slot + 10s left acoustic context + 60s core +
10s right lookahead + silence-aware boundary snap + skip silent windows +
short-tail redistribution / minimum core.

For each song:
  - vocal activity profile from the separated vocals wav (same computation as
    the B4 serial runner);
  - build_silence_aware_window_plan(60/10/10 + snap params identical to B4);
  - each non-skipped core -> one full-slot AlignmentRequest: audio input =
    [core_start-10, core_end+10], text = canonical units whose start falls in
    the input span (plus future line padding), timestamp_slot_indices = all
    (full-slot, explicit), decoder official (RealAligner default).

Canonical timeline source: an existing full-song alignment (B4 or legacy
Current) provides the unit list (global_character_index / text / start/end).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_testdemo_slot_manifest.py \
      --songs "song:lang:timelinealign:audio(vocals)" ... \
      --out <manifest.jsonl> [--skip-silent]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo"))

from lyricalign.demo.window_planning import build_silence_aware_window_plan  # noqa: E402
from align_qwen_fa_serial_demo import build_vocal_activity_profile  # noqa: E402
from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa: E402

# Frozen Base window params (20260806; identical to B4_60_silence_official).
CORE_SEC = 60.0
LEFT_SEC = 10.0
RIGHT_SEC = 10.0
MIN_SILENCE = 0.8
STRONG_SILENCE = 1.5
SEARCH_SEC = 6.0
LEADING_MIN = 2.0
TAIL_MIN = 18.0
MIN_CORE = 12.0
FUTURE_LINE_PADDING = 1


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", action="append", default=[],
                    help="song=lang=timeline_align.json=vocals.wav")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--no-skip-silent", action="store_true",
                    help="disable skip-silent-windows (default: skip essentially silent cores)")
    args = ap.parse_args()

    rows = []
    for spec in args.songs:
        song, lang, align_path, vocal_path = spec.split("=")
        d = json.loads(Path(align_path).read_text(encoding="utf-8"))
        chars = sorted(
            [c for c in d["characters"]
             if (c.get("selected_start_sec") or c.get("start_sec")) is not None],
            key=lambda c: (c.get("selected_start_sec") or c.get("start_sec")),
        )
        units = [{
            "canonical_unit_id": int(c["global_character_index"]),
            "text": c.get("display_text") or c.get("character"),
            "start_sec": float(c.get("selected_start_sec") or c.get("start_sec")),
            "end_sec": float(c.get("selected_end_sec") or c.get("end_sec")),
        } for c in chars]
        audio = decode_audio(str(vocal_path))
        duration = float(len(audio) / 16000.0)
        profile = build_vocal_activity_profile(audio)
        plan = build_silence_aware_window_plan(
            duration, profile,
            target_core_sec=CORE_SEC, left_context_sec=LEFT_SEC,
            right_context_sec=RIGHT_SEC, min_silence_sec=MIN_SILENCE,
            strong_silence_sec=STRONG_SILENCE, boundary_search_sec=SEARCH_SEC,
            leading_silence_min_sec=LEADING_MIN, tail_min_core_sec=TAIL_MIN,
            minimum_core_sec=MIN_CORE,
        )
        windows = plan["windows"]
        audio_sha = _sha(Path(vocal_path))
        for w in windows:
            core_s, core_e = float(w["core_start_sec"]), float(w["core_end_sec"])
            inp_s = max(0.0, core_s - LEFT_SEC)
            inp_e = min(duration, core_e + RIGHT_SEC)
            # skip essentially silent non-final cores (skip-silent windows)
            if (not args.no_skip_silent) and (not w.get("is_final_core")):
                si = w.get("core_start_silence_id")
                ei = w.get("core_end_silence_id")
                # core fully inside one silence interval => essentially silent
                if si is not None and si == ei:
                    rows.append({
                        "schema_version": "testdemo_slot_manifest_v1",
                        "song_id": song, "lang": lang,
                        "window_index": int(w["window_index"]),
                        "status": "skipped_silent_core",
                        "core_start_sec": core_s, "core_end_sec": core_e,
                    })
                    continue
            # canonical units whose start falls in the input span
            in_units = [u for u in units if inp_s <= u["start_sec"] < inp_e]
            if not in_units:
                # fall back to units overlapping the input span
                in_units = [u for u in units if u["start_sec"] < inp_e and u["end_sec"] > inp_s]
            if not in_units:
                rows.append({
                    "schema_version": "testdemo_slot_manifest_v1",
                    "song_id": song, "lang": lang,
                    "window_index": int(w["window_index"]),
                    "status": "no_units_in_window",
                    "core_start_sec": core_s, "core_end_sec": core_e,
                })
                continue
            # order by canonical id
            in_units.sort(key=lambda u: u["canonical_unit_id"])
            cids = [u["canonical_unit_id"] for u in in_units]
            # include units from the following line for lookahead context
            last_line_end = max(u["end_sec"] for u in in_units)
            lookahead = [u for u in units
                         if u["start_sec"] >= inp_e and u["start_sec"] < inp_e + RIGHT_SEC
                         and u["canonical_unit_id"] not in set(cids)]
            all_units = in_units + sorted(lookahead, key=lambda u: u["canonical_unit_id"])
            cids_all = [u["canonical_unit_id"] for u in all_units]
            local = {cid: i for i, cid in enumerate(cids_all)}
            texts = [u["text"] for u in all_units]
            full_slots = list(range(len(all_units)))  # full-slot: query all
            rows.append({
                "schema_version": "testdemo_slot_manifest_v1",
                "request_id": f"{song}:w{w['window_index']}:full",
                "item_id": f"{song}:w{w['window_index']}:full",
                "song_id": song,
                "parent_request_id": None,
                "audio_source": vocal_path,
                "audio_start_sec": round(inp_s, 4),
                "audio_end_sec": round(inp_e, 4),
                "duration_sec": round(inp_e - inp_s, 4),
                "text_source": "testdemo_timeline",
                "text_start_index": 0,
                "text_end_index": len(texts),
                "text_units": texts,
                "timestamp_slot_indices": full_slots,
                "workflow_mode": "long_slot_60s",
                "mutation_type": "baseline",
                "mutation_parameters": {"position": "whole", "requested_ratio": 0.0},
                "model_id": "Qwen3-ForcedAligner-0.6B-hf",
                "checkpoint_id": "r2-step-000750",
                "input_variant": "text_mutation",
                "language": lang,
                "canonical_text_start": min(cids_all),
                "canonical_text_end": max(cids_all) + 1,
                "canonical_to_local": {str(c): i for c, i in local.items()},
                "canonical_ids": cids_all,
                "canonical_timeline_file_sha": "sha256:" + _sha(Path(align_path)),
                "canonical_adapter_version": "testdemo_timeline_v1",
                "source_window_sec": [round(inp_s, 4), round(inp_e, 4)],
                "slot_plan_id": f"full:{w['window_index']}",
                "comparison_group_id": f"{song}:w{w['window_index']}",
                "phase": "full",
                "audio_sha256": "sha256:" + audio_sha,
                "status": "ok",
                "core_start_sec": core_s, "core_end_sec": core_e,
                "window_index": int(w["window_index"]),
                "is_final_core": bool(w.get("is_final_core")),
            })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ok = sum(1 for r in rows if r.get("status") == "ok")
    skip = sum(1 for r in rows if r.get("status") == "skipped_silent_core")
    print(f"wrote {len(rows)} rows ({ok} ok, {skip} skipped_silent) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
