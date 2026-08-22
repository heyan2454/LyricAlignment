#!/usr/bin/env python3
"""Fully B4-INDEPENDENT 60s coarse alignment runner.

The B4 baseline was only ever a *reference*; the product pipeline must not
read any B4 alignment file.  This runner derives everything from audio +
lyrics text:

  1. window plan = build_silence_aware_window_plan(audio activity)  (pure audio)
  2. full-slot infer_slice per window (same R2 model as everywhere else)
  3. serial commit by core boundary (cursor + split_core_commit_prefix)
  4. output alignment.json with the same schema as serial3

Document = parse_lyrics_text(lyrics.txt) — no B4 lines, no B4 timestamps,
no B4 window_trace.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_independent_60s.py \
      --song "song=lang=lyrics.txt=vocals.wav" --out-root <dir> \
      --model-dir <snap> --revision <rev> --checkpoint-path <ckpt>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo"))

import align_qwen_fa_serial_demo as SERIAL  # noqa: E402
from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
from lyricalign.demo.window_planning import build_silence_aware_window_plan  # noqa: E402
from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa: E402

# frozen 20260806 Base windowing parameters (identical to B4's planner)
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


def _fix60_window_plan(duration: float, profile: dict, *, target_core_sec: float,
                       left_context_sec: float, right_context_sec: float,
                       leading_silence_min_sec: float, tail_min_core_sec: float,
                       minimum_core_sec: float, min_silence_sec: float = 0.8,
                       strong_silence_sec: float = 1.5,
                       boundary_search_sec: float = 6.0) -> dict:
    """FIXED-60s grid plan with leading/trailing silence trim (same semantics
    as soft), NO internal boundary snap, and short-tail redistribution.

    core 0 starts at active_start (leading silence >= leading_silence_min_sec
    is trimmed, identical to soft); subsequent cores are fixed every
    target_core_sec (no snap to silence); a tail shorter than tail_min_core_sec
    is redistributed across the two previous windows (soft _rebalance_short_tail);
    input = core ± context, clamped to [0, duration].
    """
    from lyricalign.demo.window_planning import detect_silence_intervals  # noqa: PLC0415

    intervals = detect_silence_intervals(
        profile, duration_sec=duration, min_silence_sec=min_silence_sec,
        strong_silence_sec=strong_silence_sec,
    )
    # leading/trailing trim (same rule as soft)
    active_start, active_end = 0.0, duration
    leading = next((r for r in intervals if float(r["start_sec"]) <= 1e-9), None)
    if leading is not None and float(leading["duration_sec"]) + 1e-9 >= leading_silence_min_sec:
        active_start = float(leading["end_sec"])
    trailing = next((r for r in reversed(intervals)
                     if float(r["end_sec"]) >= duration - 1e-9), None)
    if trailing is not None and float(trailing["duration_sec"]) + 1e-9 >= leading_silence_min_sec:
        active_end = float(trailing["start_sec"])
    if active_end <= active_start + 1e-6:
        active_start, active_end = 0.0, duration
    # fixed grid boundaries (no snap)
    boundaries = [active_start]
    cursor = active_start + target_core_sec
    while cursor < active_end - 1e-9:
        boundaries.append(cursor)
        cursor += target_core_sec
    boundaries.append(active_end)
    # short-tail redistribution (identical to soft _rebalance_short_tail)
    if len(boundaries) > 2:
        tail = boundaries[-1] - boundaries[-2]
        if tail + 1e-9 < tail_min_core_sec:
            if len(boundaries) == 3:
                boundaries = [boundaries[0], boundaries[-1]]
            else:
                a, b, c, end = boundaries[-4], boundaries[-3], boundaries[-2], boundaries[-1]
                boundaries = boundaries[:-4] + [a, b + tail / 2.0, end]
    windows = []
    for i in range(len(boundaries) - 1):
        cs, ce = boundaries[i], boundaries[i + 1]
        if ce - cs < minimum_core_sec - 1e-9:
            continue
        windows.append({
            "window_index": i,
            "core_start_sec": round(cs, 4),
            "core_end_sec": round(ce, 4),
            "input_start_sec": round(max(0.0, cs - left_context_sec), 4),
            "input_end_sec": round(min(duration, ce + right_context_sec), 4),
            "is_final_core": i == len(boundaries) - 2,
            "plan_kind": "fixed60",
        })
    return {"windows": windows, "active_span_duration_sec": round(active_end - active_start, 4),
            "leading_silence_skipped": leading, "trailing_silence_skipped": trailing}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", required=True, help="song=lang=lyrics.txt=vocals.wav")
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--checkpoint-path", required=True)
    ap.add_argument("--target-core-sec", type=float, default=60.0)
    ap.add_argument("--left-context-sec", type=float, default=10.0)
    ap.add_argument("--right-context-sec", type=float, default=10.0)
    ap.add_argument("--budget-covered-core", action="store_true",
                    help="budget support = CORE span (short windows); default = input span (B4 frozen)")
    ap.add_argument("--window-plan", choices=("soft", "strict", "fix60"), default="soft",
                    help="window plan: soft=silence-aware (default), strict=5s hard boundary, "
                         "fix60=fixed 60s grid with leading/tail trim, no snap")
    ap.add_argument("--propagate-raw", action="store_true",
                    help="serial commit uses RAW timestamps for propagation "
                         "(20260812 freeze: raw is the propagation view); output "
                         "geometry stays official (legalization view)")
    args = ap.parse_args()

    song, lang, lyrics_path, vocal_path = args.song.split("=")
    doc = parse_lyrics_text(Path(lyrics_path).read_text(encoding="utf-8"), language=lang)
    units = list(doc.characters)
    total = len(units)
    audio = decode_audio(str(vocal_path))
    sr = 16000
    duration = float(len(audio) / sr)
    profile = SERIAL.build_vocal_activity_profile(audio)
    base = dict(BASE, target_core_sec=args.target_core_sec,
                left_context_sec=args.left_context_sec,
                right_context_sec=args.right_context_sec)
    if args.window_plan == "fix60":
        plan = _fix60_window_plan(duration, profile, **base)
    elif args.window_plan == "strict":
        from lyricalign.demo.window_planning import build_strict_silence_boundary_window_plan  # noqa: PLC0415
        plan = build_strict_silence_boundary_window_plan(duration, profile,
                                                         strict_silence_sec=5.0, **base)
    else:
        plan = build_silence_aware_window_plan(duration, profile, **base)
    windows = sorted(plan["windows"], key=lambda w: float(w.get("core_start_sec", 0)))
    print(f"{song}: units={total} windows={len(windows)} duration={duration:.1f}s "
          f"plan={args.window_plan}", flush=True)

    infer_args = SimpleNamespace(
        device="cuda", model=args.model_dir, revision=args.revision,
        local_files_only=True, cache_dir=None,
        timestamp_segment_sec=0.08, decoder_kind="official",
        decoder_top_k=8, decoder_beam_size=96,
    )
    processor, model = SERIAL.load_model(infer_args, kind="lora", checkpoint=Path(args.checkpoint_path))

    global_rate = total / max(duration, 1e-9)
    cursor = 0
    prev_count = 0
    prev_core_dur = 0.0
    committed_rows: list[dict] = []
    trace_rows: list[dict] = []
    for wi, w in enumerate(windows):
        core_s = float(w["core_start_sec"])
        core_e = float(w["core_end_sec"])
        inp_s = float(w["input_start_sec"])
        inp_e = float(w["input_end_sec"])
        final = bool(w.get("is_final_core", wi == len(windows) - 1))
        if cursor >= total:
            trace_rows.append({**w, "status": "no_units_left", "committed_cursor": cursor})
            continue
        activity = SERIAL.vocal_activity_for_interval(profile, core_s, core_e)
        # skip-silent (B4 frozen semantics: sustained < 0.40s AND (active_ratio
        # <= 0.01 OR peak <= reliable_threshold+3dB); final core never skipped)
        essentially_silent = (
            float(activity.get("sustained_active_duration_sec") or 0.0) < 0.40
            and (float(activity.get("active_ratio") or 1.0) <= 0.01 + 1e-12
                 or float(activity.get("peak_db") or 0.0)
                 <= float(activity.get("reliable_threshold_db") or 0.0) + 3.0 + 1e-12)
        )
        if essentially_silent and not final:
            trace_rows.append({**w, "status": "skipped_silent_core",
                               "vocal_activity": activity,
                               "committed_cursor": cursor})
            print(f"  w{wi} core=[{core_s:.1f},{core_e:.1f}] SKIP silent", flush=True)
            continue
        activity = SERIAL.vocal_activity_for_interval(profile, inp_s, inp_e)
        if args.budget_covered_core:
            # short windows: model must place queried units inside the CORE,
            # so budget from the core span (input span would overshoot by
            # (input/core) ratio and compress too many units into the window)
            covered = max(0.0, core_e - core_s)
        else:
            # B4 frozen semantics: input span
            covered = max(0.0, inp_e - inp_s)
        budget_support = min(covered, float(activity.get("sustained_active_duration_sec") or 0.0))
        recent = prev_count / prev_core_dur if prev_core_dur > 0 else 0.0
        cps = max(global_rate, recent)
        if args.budget_covered_core:
            # short windows: minimum forward characters scales with the core
            # (B4's frozen 24/64 constants assume a 60s core; on a 12s core
            # they would overshoot ~2-5x and force the model to compress all
            # queried units into the window -> commit cascade)
            startup_min = max(4, int(round(24 * args.target_core_sec / 60.0)))
            min_target = max(4, int(round(64 * args.target_core_sec / 60.0)))
        else:
            startup_min, min_target = 24, 64  # B4 frozen
        target = max(startup_min if cursor == 0 else min_target,
                     int(math.ceil(cps * budget_support
                                   * (1.0 if args.budget_covered_core else 1.35))))
        if final:
            target = total - cursor
        end = min(total, cursor + target)
        win_ids = list(range(cursor, end))
        lookahead_end = end
        if not args.budget_covered_core and end < total:
            # B4 frozen line-padding lookahead (60s windows tolerate the
            # overshoot; short windows must query ONLY their own core units,
            # otherwise the model compresses neighbours into the window)
            last_line = units[end - 1].line_index
            while lookahead_end < total and units[lookahead_end].line_index <= last_line + 1:
                lookahead_end += 1
        query_ids = list(range(cursor, lookahead_end))
        start = int(round(inp_s * sr)); stop = int(round(inp_e * sr))
        stop = min(stop, len(audio))
        if stop <= start:
            trace_rows.append({**w, "status": "empty_crop"})
            continue
        try:
            rows_out, audit = SERIAL.infer_slice(
                processor=processor, model=model,
                audio=audio[start:stop], document=doc,
                character_start=cursor, character_end=lookahead_end,
                global_audio_offset_sec=inp_s, args=infer_args,
                timestamp_slot_indices=list(range(lookahead_end - cursor)),
            )
        except Exception as e:  # noqa: BLE001
            print(f"  w{wi} FAIL: {e}", flush=True)
            trace_rows.append({**w, "status": "fail", "error": str(e)})
            continue
        context, committed, lookahead_out = SERIAL.split_core_commit_prefix(
            rows_out, expected_input_character_start=cursor,
            committed_character_start=cursor,
            core_start_sec=core_s, core_end_sec=core_e, final_core=final,
            start_key=("raw_global_start_sec" if args.propagate_raw
                       else "fixed_global_start_sec"),
        )
        committed_rows.extend(committed)
        prev_count = len(committed)
        prev_core_dur = max(0.0, core_e - core_s)
        committed_ids = [int(r["global_character_index"]) for r in committed]
        next_cursor = cursor + len(committed_ids) if committed_ids else cursor
        if not committed_ids and not final:
            next_cursor = min(end, total)
        trace_rows.append({**w, "status": "ok",
                           "committed": len(committed_ids),
                           "queried": len(query_ids),
                           "cursor_before": cursor,
                           "cursor_after": next_cursor})
        print(f"  w{wi} core=[{core_s:.1f},{core_e:.1f}] queried={len(query_ids)} "
              f"committed={len(committed_ids)} cursor={cursor}->{next_cursor}", flush=True)
        cursor = next_cursor
        if cursor >= total:
            break

    # ---- GLOBAL official legalization (2026-08-16 design) ----
    # Propagation runs on RAW timestamps (per-window, unmodified).  The final
    # output is legalized GLOBALLY: collect every committed row's raw start/end
    # (song-wide, character order), interleave to a 2N ms array and run the
    # official _fix_timestamps (LIS monotonic fix) ONCE over the whole song —
    # NOT per window.  This is what "raw local, official global" means.
    from transformers.models.qwen3_asr.processing_qwen3_asr import _fix_timestamps  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    committed_rows.sort(key=lambda r: int(r["global_character_index"]))
    raw_ms: list[float] = []
    for row in committed_rows:
        rs = row.get("raw_global_start_sec")
        re_ = row.get("raw_global_end_sec")
        if rs is None or re_ is None:
            raise RuntimeError(f"row {row.get('global_character_index')} missing raw geometry")
        raw_ms.extend([float(rs) * 1000.0, float(re_) * 1000.0])
    fixed_ms = _fix_timestamps(np.asarray(raw_ms, dtype=np.float64))
    fixed_sec = [float(v) / 1000.0 for v in fixed_ms]

    def _norm(i, row):
        s = fixed_sec[2 * i]
        e = fixed_sec[2 * i + 1]
        out = dict(row)
        out["start_sec"] = s; out["end_sec"] = e
        out["selected_start_sec"] = s; out["selected_end_sec"] = e
        out["official_fixed_global_start_sec"] = s
        out["official_fixed_global_end_sec"] = e
        out["decoder_kind"] = "official"
        return out
    rows = [_norm(i, r) for i, r in enumerate(committed_rows)]
    rows.sort(key=lambda r: int(r["global_character_index"]))
    best = {}
    for row in rows:
        g = int(row["global_character_index"])
        if g not in best:
            best[g] = row
    merged = [best[k] for k in sorted(best)]
    mono_fixed = 0
    merged.sort(key=lambda r: float(r.get("selected_start_sec") or 0))
    by_line = {}
    for row in merged:
        by_line.setdefault(int(row.get("line_index", 0)), []).append(row)
    lines = [{"line_index": li,
              "display_text": "".join(r.get("display_text") or r.get("character") or ""
                                      for r in sorted(rs, key=lambda x: int(x.get("index_in_line", 0)))),
              "character_start": min((int(r.get("global_character_index", -1)) for r in rs), default=0),
              "character_end": max((int(r.get("global_character_index", -1)) + 1 for r in rs), default=0)}
             for li, rs in sorted(by_line.items())]
    dur = max((float(r.get("selected_end_sec") or 0) for r in merged), default=0.0)
    out_dir = args.out_root / song / "alignments/r2/vocal/windowed"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "independent_60s_serial_v1",
        "identity": {"request_mode": "full_slot", "decoder_view": "official",
                     "window_plan": "silence_aware_60s_10_10_skip_silent",
                     "transition": "serial_commit",
                     "runner": "run_independent_60s.py (no B4 input)",
                     "target_core_sec": float(args.target_core_sec),
                     "propagation_view": ("raw" if args.propagate_raw else "official"),
                     "output_view": "official",
                     "legalization": "global_fix_timestamps_2N",
                     "monotonic_fixed_rows": mono_fixed},
        "summary": {"audio_duration_sec": round(dur, 4), "characters": len(merged),
                    "committed": len(merged), "total_units": total},
        "lines": lines, "characters": merged, "window_trace": trace_rows,
        "artifact_stage": "real",
    }
    p = out_dir / "alignment.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"song": song, "committed": len(merged), "of": total,
                      "coverage": len(merged) / max(total, 1), "path": str(p)},
                     ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    import math  # noqa: PLC0415
    raise SystemExit(main())
