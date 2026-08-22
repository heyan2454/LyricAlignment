#!/usr/bin/env python3
"""Build full-slot request manifests for the strict/compress 2x2 variant group
(C2 strict-only, C3 compress-only, C4 strict+compress).

The unit space, canonical ids and lyric text are identical to the B4
alignment (same parse, same characters), but the window plan comes from the
variant planner instead of the B4 window_trace:

- strict:          build_strict_silence_boundary_window_plan(strict_silence_sec=5.0)
                   -> hard split at >=5s silence, then the SAME soft logic runs
                   independently inside each active region; small island
                   regions keep their own single window; inputs never cross a
                   strict silence (clipped to the region).
- compress:        soft plan on the original clock, then silence >=2s trimmed
                   to 2s (trim_to_sec=2.0) on the audio, then the plan is
                   projected onto the compressed clock.  Units keep their
                   ORIGINAL times; window core spans for unit ownership are the
                   original-clock cores (projection keeps original_* fields).
- strict_compress: strict plan on the original clock, then the same
                   compression + projection as compress.

Unit ownership per window = canonical units whose start_sec falls in the
window's original-clock core span (B4 owner_window_index is not reused; the
variant windows differ from B4's).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_testdemo_slot_variant_manifest.py \
      --songs "song=lang=b4_alignment.json=vocals.wav" ... \
      --variant strict --audio-out <dir> --out <manifest.jsonl>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts/demo"))

from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
from lyricalign.demo.window_planning import (  # noqa: E402
    build_silence_aware_window_plan,
    build_strict_silence_boundary_window_plan,
    compress_silence_audio,
    project_silence_aware_plan_to_compressed_timeline,
)
from align_qwen_fa_serial_demo import (  # noqa: E402
    build_vocal_activity_profile, vocal_activity_for_interval,
)
from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

VARIANT_PARAMS = {
    "strict": {
        "strict_silence_sec": 5.0,
        "compress_trim_to_sec": None,
        "compress_min_sec": None,
    },
    "compress": {
        "strict_silence_sec": None,
        "compress_trim_to_sec": 2.0,
        "compress_min_sec": 2.0,
    },
    "strict_compress": {
        "strict_silence_sec": 5.0,
        "compress_trim_to_sec": 2.0,
        "compress_min_sec": 2.0,
    },
}
# frozen 20260806 Base windowing parameters (same as B4)
BASE = dict(
    target_core_sec=60.0,
    left_context_sec=10.0,
    right_context_sec=10.0,
    min_silence_sec=0.8,
    strong_silence_sec=1.5,
    boundary_search_sec=6.0,
    leading_silence_min_sec=2.0,
    tail_min_core_sec=18.0,
    minimum_core_sec=12.0,
)
# model input safety line: >~150 units degrades (all-zero collapse to
# input_start); guard window unit sets against B4-timeline collapse artifacts
# (e.g. 冬之花 w1 all at 58.5s) that pile units into one window.
MAX_WINDOW_UNITS = 150


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", action="append", default=[],
                    help="song=lang=b4_alignment.json=vocals.wav")
    ap.add_argument("--variant", required=True, choices=sorted(VARIANT_PARAMS))
    ap.add_argument("--audio-out", required=True, type=Path,
                    help="dir for compressed audio + mapping artifacts (C3/C4)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-units", type=int, default=MAX_WINDOW_UNITS)
    args = ap.parse_args()

    params = VARIANT_PARAMS[args.variant]
    max_units = args.max_units
    args.audio_out.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in args.songs:
        song, lang, align_path, vocal_path = spec.split("=")
        d = json.loads(Path(align_path).read_text(encoding="utf-8"))
        b4_chars = d["characters"]
        by_gidx = {int(c["global_character_index"]): c for c in b4_chars}
        units = []
        for c in b4_chars:
            units.append({
                "canonical_unit_id": int(c["global_character_index"]),
                "text": str(c.get("display_text") or c.get("character") or ""),
                "line_index": int(c.get("line_index", 0)),
                "index_in_line": int(c.get("index_in_line", 0)),
                "owner_window_index": c.get("owner_window_index"),
            })
        for u in units:
            g = u["canonical_unit_id"]
            if g in by_gidx:
                bc = by_gidx[g]
                u["start_sec"] = float(bc.get("selected_start_sec") or bc.get("start_sec") or 0.0)
                u["end_sec"] = float(bc.get("selected_end_sec") or bc.get("end_sec") or u["start_sec"])
            else:
                u["start_sec"] = u["end_sec"] = 0.0

        # B4-identical decode: 16 kHz mono (decode_audio resamples; raw
        # sf.read would keep 44.1 kHz and break the 16 kHz profile/window math)
        audio = decode_audio(str(vocal_path))
        sr = 16000
        duration = float(len(audio) / sr)
        profile = build_vocal_activity_profile(audio)

        # 1) window plan on the ORIGINAL clock
        if params["strict_silence_sec"] is not None:
            original_plan = build_strict_silence_boundary_window_plan(
                duration, profile,
                target_core_sec=BASE["target_core_sec"],
                left_context_sec=BASE["left_context_sec"],
                right_context_sec=BASE["right_context_sec"],
                min_silence_sec=BASE["min_silence_sec"],
                strong_silence_sec=BASE["strong_silence_sec"],
                strict_silence_sec=params["strict_silence_sec"],
                boundary_search_sec=BASE["boundary_search_sec"],
                leading_silence_min_sec=BASE["leading_silence_min_sec"],
                tail_min_core_sec=BASE["tail_min_core_sec"],
                minimum_core_sec=BASE["minimum_core_sec"],
            )
        else:
            original_plan = build_silence_aware_window_plan(
                duration, profile,
                target_core_sec=BASE["target_core_sec"],
                left_context_sec=BASE["left_context_sec"],
                right_context_sec=BASE["right_context_sec"],
                min_silence_sec=BASE["min_silence_sec"],
                strong_silence_sec=BASE["strong_silence_sec"],
                boundary_search_sec=BASE["boundary_search_sec"],
                leading_silence_min_sec=BASE["leading_silence_min_sec"],
                tail_min_core_sec=BASE["tail_min_core_sec"],
                minimum_core_sec=BASE["minimum_core_sec"],
            )

        # 2) optional compression (post-windowing audio processing)
        mapping_path = None
        compressed = None
        windows = list(original_plan["windows"])
        plan_policy = original_plan.get("policy", original_plan.get("schema_version", args.variant))
        if params["compress_trim_to_sec"] is not None:
            compressed, mapping = compress_silence_audio(
                audio, profile,
                min_silence_sec=BASE["min_silence_sec"],
                strong_silence_sec=BASE["strong_silence_sec"],
                remove_silence_sec=params["compress_min_sec"],
                trim_to_sec=params["compress_trim_to_sec"],
            )
            comp_path = args.audio_out / f"{song}.compressed.wav"
            sf.write(comp_path, compressed, sr)
            mapping_path = args.audio_out / f"{song}.compression_mapping.json"
            mapping_path.write_text(
                json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
            # 3) project the original-clock plan onto the compressed clock
            original_plan = project_silence_aware_plan_to_compressed_timeline(
                original_plan, mapping)
            windows = list(original_plan["windows"])
            plan_policy = original_plan.get("policy", plan_policy)

        audio_source = str(Path(comp_path).resolve()) if compressed is not None else str(Path(vocal_path).resolve())
        audio_sha = _sha(Path(audio_source))
        seen_req = set()
        # ---- lyric-order slicing (B4 future-slice rule, data-independent) ----
        # Windows are ordered by original-clock core; each window's units are a
        # contiguous lyric slice from a cursor, sized by the SAME budget rule as
        # B4: target = max(min, ceil(cps * budget_support * 1.35)) with
        # cps = max(global_rate, recent_rate) and budget_support = min(input
        # span, sustained-active duration).  No B4 timestamps/owners involved.
        # active span must be the ORIGINAL-clock span: for compressed variants
        # `original_plan` was overwritten by the projection (compressed clock),
        # which would inflate the density estimate.
        orig_active_span = float(original_plan.get("active_span_duration_sec") or duration)
        windows_sorted = sorted(
            windows,
            key=lambda w: float(w.get("original_core_start_sec") or w.get("core_start_sec") or 0.0),
        )
        total_units_n = len(units)
        global_rate = total_units_n / max(orig_active_span, 1e-9)
        cursor = 0
        prev_count = 0
        prev_core_dur = 0.0
        for w in windows_sorted:
            if not isinstance(w, dict):
                continue
            wi = int(w.get("window_index", -1))
            # budget/activity math runs on the ORIGINAL clock (lyric density is
            # defined on the original timeline even for compressed variants)
            # audio crop for the runner: ALWAYS the window's own clock
            # (compressed variants project input onto the compressed clock)
            audio_s = float(w.get("input_start_sec") or w.get("core_start_sec") or 0.0)
            audio_e = float(w.get("input_end_sec") or w.get("core_end_sec") or audio_s + 60.0)
            # budget/activity math on the ORIGINAL clock (lyric density is
            # defined on the original timeline even for compressed variants)
            inp_s = float(w.get("original_input_start_sec") or audio_s)
            inp_e = float(w.get("original_input_end_sec") or audio_e)
            core_s = float(w.get("original_core_start_sec") or w.get("core_start_sec") or 0.0)
            core_e = float(w.get("original_core_end_sec") or w.get("core_end_sec") or inp_e)
            covered = max(0.0, inp_e - inp_s)
            activity = vocal_activity_for_interval(profile, inp_s, inp_e)
            budget_support = min(covered, float(activity.get("sustained_active_duration_sec") or 0.0))
            recent_rate = prev_count / prev_core_dur if prev_core_dur > 0 else 0.0
            cps = max(global_rate, recent_rate)
            min_target = 24 if cursor == 0 else 64
            target = max(min_target, int(math.ceil(cps * budget_support * 1.35)))
            is_final = bool(w.get("is_final_core", False))
            if is_final:
                target = max(0, total_units_n - cursor)
            in_units = units[cursor: cursor + target]
            if not in_units:
                rows.append({
                    "schema_version": "testdemo_slot_variant_manifest_v1",
                    "song_id": song, "lang": lang,
                    "window_index": wi, "status": "no_units_in_window",
                    "core_start_sec": core_s, "core_end_sec": core_e,
                })
                continue
            truncated = len(in_units) > max_units
            truncated_count = 0
            if truncated and not is_final:
                # non-final windows cap at max_units (the next window starts at
                # the cut cursor and takes over the tail); the FINAL window must
                # keep every remaining unit (no later window exists to inherit)
                truncated_count = len(in_units) - max_units
                in_units = in_units[:max_units]
            cids = [u["canonical_unit_id"] for u in in_units]
            cid_set = set(cids)
            max_cid = max(cids)
            # line-padding lookahead (B4 future_character_range line_padding=1)
            lookahead = [u for u in units
                         if u["canonical_unit_id"] > max_cid
                         and u["line_index"] <= in_units[-1]["line_index"] + 1
                         and u["canonical_unit_id"] not in cid_set]
            lookahead.sort(key=lambda u: u["canonical_unit_id"])
            window_cids = cids + [u["canonical_unit_id"] for u in lookahead]
            prev_count = len(in_units)
            prev_core_dur = max(0.0, core_e - core_s)
            # cursor advances past the window's OWN slice (not the lookahead)
            cursor = max(cursor, cids[-1] + 1)
            all_cids = [u["canonical_unit_id"] for u in units]
            texts = [u["text"] for u in units]
            slot_set = set(window_cids)
            slot_local = [i for i, cid in enumerate(all_cids) if cid in slot_set]
            local = {cid: i for i, cid in enumerate(window_cids)}
            rid = f"{song}:w{wi}:{args.variant}"
            if rid in seen_req:
                continue
            seen_req.add(rid)
            row = {
                "schema_version": "testdemo_slot_variant_manifest_v1",
                "request_id": rid,
                "item_id": rid,
                "song_id": song,
                "parent_request_id": None,
                "audio_source": audio_source,
                "audio_start_sec": round(audio_s, 4),
                "audio_end_sec": round(audio_e, 4),
                "duration_sec": round(audio_e - audio_s, 4),
                "text_source": "testdemo_timeline",
                "text_start_index": 0,
                "text_end_index": len(texts),
                "text_units": texts,
                "timestamp_slot_indices": slot_local,
                "workflow_mode": "long_slot_60s",
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
                "window_unit_ids": window_cids,
                "canonical_timeline_file_sha": "sha256:" + _sha(Path(align_path)),
                "timeline_align_path": str(Path(align_path).resolve()),
                "canonical_adapter_version": "testdemo_timeline_v1",
                "source_window_sec": [round(audio_s, 4), round(audio_e, 4)],
                "slot_plan_id": f"{args.variant}:{wi}",
                "comparison_group_id": f"{song}:w{wi}:{args.variant}",
                "phase": "full",
                "audio_sha256": "sha256:" + audio_sha,
                "status": "ok",
                "core_start_sec": core_s, "core_end_sec": core_e,
                "window_index": wi,
                "is_final_core": bool(w.get("is_final_core", wi == len(windows) - 1)),
                "variant": args.variant,
                "window_plan_policy": plan_policy,
            }
            if mapping_path is not None:
                row["compressed_mapping_path"] = str(mapping_path.resolve())
                row["compressed_audio_path"] = audio_source
                row["original_duration_sec"] = round(duration, 4)
                row["compressed_duration_sec"] = round(float(len(compressed) / sr), 4)
                row["core_clock"] = "original"
                row["audio_clock"] = "compressed"
            else:
                row["core_clock"] = "original"
                row["audio_clock"] = "original"
            # original-clock geometry for renderers (compressed variants project
            # core/input onto the compressed clock; the timeline is original)
            row["original_core_start_sec"] = round(float(w.get("original_core_start_sec", core_s)), 4)
            row["original_core_end_sec"] = round(float(w.get("original_core_end_sec", core_e)), 4)
            row["original_input_start_sec"] = round(float(w.get("original_input_start_sec", inp_s)), 4)
            row["original_input_end_sec"] = round(float(w.get("original_input_end_sec", inp_e)), 4)
            row["compressed_input_start_sec"] = round(audio_s, 4)
            row["compressed_input_end_sec"] = round(audio_e, 4)
            if truncated:
                row["status"] = "ok_truncated_units"
                row["truncated_unit_count"] = truncated_count
            rows.append(row)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"variant={args.variant} wrote {len(rows)} rows ({ok} ok) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
