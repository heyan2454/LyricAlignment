#!/usr/bin/env python3
"""Full-slot + SERIAL runner (the Current/T2-style baseline): same soft windows
and same full-slot query as the independent Plan-A (C1), but with a serial
commit state machine between windows:

  - cursor starts at 0; window units = lyric slice from cursor (B4 budget rule)
  - infer_slice queries ALL window units (full-slot)
  - commit: units whose start < core_end are permanently committed
    (split_core_commit_prefix), cursor advances past the committed units
  - uncommitted units (audio doesn't match / past core end) stay for the next
    window to re-observe — this is the serial correction of "outside-window"
    words that the independent plan leaves stuck at window edges

Output per song: alignment.json (same schema as Plan-A C1).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_testdemo_slot_serial.py \
      --song "祈愿花开=Chinese=<b4_alignment.json>=<vocals.wav>" \
      --out-root <dir> --model-dir <snap> --revision <rev> --checkpoint-path <ckpt>
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

import math  # noqa: E402

import align_qwen_fa_serial_demo as SERIAL  # noqa: E402
from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa: E402

BUDGET_RATIO = 1.35
MIN_TARGET = 64
STARTUP_MIN = 24


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", required=True, help="song=lang=b4_alignment.json=vocals.wav")
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--checkpoint-path", required=True)
    args = ap.parse_args()

    song, lang, align_path, vocal_path = args.song.split("=")
    b4d = json.loads(Path(align_path).read_text(encoding="utf-8"))
    line_text = "\n".join(l.get("display_text", "") for l in (b4d.get("lines") or []))
    doc = parse_lyrics_text(line_text, language=lang)
    units = list(doc.characters)
    total = len(units)
    windows = sorted((b4d.get("window_trace") or []),
                     key=lambda w: float(w.get("core_start_sec", 0)))
    duration = float(windows[-1]["core_end_sec"]) if windows else 0.0
    print(f"{song}: units={total} windows={len(windows)}", flush=True)

    infer_args = SimpleNamespace(
        device="cuda", model=args.model_dir, revision=args.revision,
        local_files_only=True, cache_dir=None,
        timestamp_segment_sec=0.08, decoder_kind="official",
        decoder_top_k=8, decoder_beam_size=96,
    )
    processor, model = SERIAL.load_model(infer_args, kind="lora", checkpoint=Path(args.checkpoint_path))
    audio = decode_audio(str(vocal_path))
    sr = 16000

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
        # budget (B4 rule) with recent rate from the previous window's commits
        activity = SERIAL.vocal_activity_for_interval(
            SERIAL.build_vocal_activity_profile(audio), inp_s, inp_e)
        covered = max(0.0, inp_e - inp_s)
        budget_support = min(covered, float(activity.get("sustained_active_duration_sec") or 0.0))
        recent = prev_count / prev_core_dur if prev_core_dur > 0 else 0.0
        cps = max(global_rate, recent)
        target = max(STARTUP_MIN if cursor == 0 else MIN_TARGET,
                     int(math.ceil(cps * budget_support * BUDGET_RATIO)))
        if final:
            target = total - cursor
        # window units: lyric slice from cursor + one line lookahead
        end = min(total, cursor + target)
        win_ids = list(range(cursor, end))
        lookahead_end = end
        if end < total:
            last_line = units[end - 1].line_index
            while lookahead_end < total and units[lookahead_end].line_index <= last_line + 1:
                lookahead_end += 1
        query_ids = list(range(cursor, lookahead_end))
        # audio crop
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
        # commit by core boundary (serial state machine)
        context, committed, lookahead_out = SERIAL.split_core_commit_prefix(
            rows_out, expected_input_character_start=cursor,
            committed_character_start=cursor,
            core_start_sec=core_s, core_end_sec=core_e, final_core=final,
        )
        committed_rows.extend(committed)
        prev_count = len(committed)
        prev_core_dur = max(0.0, core_e - core_s)
        committed_ids = [int(r["global_character_index"]) for r in committed]
        next_cursor = cursor + len(committed_ids) if committed_ids else cursor
        # uncommitted window units stay for the next window
        if not committed_ids and not final:
            next_cursor = min(end, total)  # still advance past queried slice
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

    # finalize alignment (same schema as Plan-A C1)
    def _norm(row):
        s = float(row.get("official_fixed_global_start_sec")
                  if row.get("official_fixed_global_start_sec") is not None
                  else row.get("fixed_global_start_sec") or row.get("raw_global_start_sec") or 0.0)
        e = float(row.get("official_fixed_global_end_sec")
                  if row.get("official_fixed_global_end_sec") is not None
                  else row.get("fixed_global_end_sec") or row.get("raw_global_end_sec") or s)
        out = dict(row)
        out["start_sec"] = s; out["end_sec"] = e
        out["selected_start_sec"] = s; out["selected_end_sec"] = e
        out["decoder_kind"] = "official"
        return out
    rows = [_norm(r) for r in committed_rows]
    rows.sort(key=lambda r: int(r["global_character_index"]))
    best = {}
    for row in rows:
        g = int(row["global_character_index"])
        if g not in best:
            best[g] = row
    merged = [best[k] for k in sorted(best)]
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
        "schema_version": "testdemo_fullslot_serial_v1",
        "identity": {"request_mode": "full_slot", "decoder_view": "official",
                     "window_plan": "silence_aware_60s_10_10_skip_silent",
                     "transition": "serial_commit", "runner": "run_testdemo_slot_serial.py"},
        "summary": {"audio_duration_sec": round(dur, 4), "characters": len(merged),
                    "committed": len(merged), "total_units": total},
        "lines": lines, "characters": merged, "window_trace": trace_rows,
        "artifact_stage": "real",
    }
    p = out_dir / "alignment.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"song": song, "committed": len(merged), "of": total,
                      "coverage": len(merged) / max(total, 1),
                      "path": str(p)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
