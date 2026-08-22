#!/usr/bin/env python3
"""Short-window (line-level) FULL-SLOT + SERIAL runner.

Same shortline manifests as run_testdemo_slot_infer.py (one window per lyric
line, audio crop = line span ± pad), but with a serial commit state machine
between windows:

  - cursor starts at the first uncommitted character
  - for each line window (in line order):
      * query range = [max(cursor, line_start), line_end+1) + one-line
        lookahead past the query end (B4 future_character_range padding)
      * infer_slice with full-slot on the window range
      * commit characters whose start < core_end (line end) via
        split_core_commit_prefix
  - committed rows are final; uncommitted window units stay for the next
    window to re-observe (serial correction of edge words)

Output per song: alignment.json (same schema as the serial 60s runner,
window_plan marked shortline).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_testdemo_shortline_serial.py \
      --manifest <shortline.jsonl> --out-root <dir> \
      --model-dir <snap> --revision <rev> --checkpoint-path <ckpt> [--limit N]
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
from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--checkpoint-path", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.manifest.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok_rows = [r for r in rows if r.get("status") in ("ok", "ok_truncated_units")]
    if args.limit:
        ok_rows = ok_rows[:args.limit]

    infer_args = SimpleNamespace(
        device="cuda", model=args.model_dir, revision=args.revision,
        local_files_only=True, cache_dir=None,
        timestamp_segment_sec=0.08, decoder_kind="official",
        decoder_top_k=8, decoder_beam_size=96,
    )
    processor, model = SERIAL.load_model(infer_args, kind="lora", checkpoint=Path(args.checkpoint_path))

    by_song: dict[str, list[dict]] = {}
    order: list[str] = []
    doc_cache: dict[str, object] = {}
    audio_cache: dict[str, object] = {}
    done = 0
    for r in ok_rows:
        song = r["song_id"]
        if song not in by_song:
            by_song[song] = []
            order.append(song)
            tpath = r.get("timeline_align_path")
            b4d = json.loads(Path(tpath).read_text(encoding="utf-8"))
            line_text = "\n".join(l.get("display_text", "") for l in (b4d.get("lines") or []))
            doc_cache[song] = parse_lyrics_text(line_text, language=r["language"])
            audio_cache[song] = decode_audio(str(r["audio_source"]))
        by_song[song].append(r)
        done += 1

    for song in order:
        reqs = sorted(by_song[song], key=lambda r: int(r.get("window_index", -1)))
        doc = doc_cache[song]
        audio = audio_cache[song]
        total = len(doc.characters)
        cursor = 0
        committed_rows: list[dict] = []
        trace_rows: list[dict] = []
        for r in reqs:
            wi = int(r.get("window_index", -1))
            line_ids = sorted(int(x) for x in r["window_unit_ids"])
            line_start = min(line_ids)
            line_end = max(line_ids) + 1
            core_s = float(r["core_start_sec"])
            core_e = float(r["core_end_sec"])
            final = bool(r.get("is_final_core", False))
            if cursor >= total:
                trace_rows.append({"window_index": wi, "status": "no_units_left",
                                   "committed_cursor": cursor})
                continue
            # query range: from cursor (or line start, whichever is later)
            # to line end + one-line lookahead past the query end
            qstart = max(cursor, line_start)
            if qstart >= line_end:
                qstart = line_end  # nothing new; still allow re-observe
            qend = line_end
            if qend < total:
                last_line = doc.characters[qend - 1].line_index
                while qend < total and doc.characters[qend].line_index <= last_line + 1:
                    qend += 1
            start = int(round(float(r["audio_start_sec"]) * 16000))
            stop = int(round(float(r["audio_end_sec"]) * 16000))
            stop = min(stop, len(audio))
            if stop <= start or qstart >= qend:
                trace_rows.append({**r, "status": "empty_query"})
                continue
            try:
                rows_out, audit = SERIAL.infer_slice(
                    processor=processor, model=model,
                    audio=audio[start:stop], document=doc,
                    character_start=qstart, character_end=qend,
                    global_audio_offset_sec=float(r["audio_start_sec"]),
                    args=infer_args,
                    timestamp_slot_indices=list(range(qend - qstart)),
                )
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {song} L{wi}: {e}", flush=True)
                trace_rows.append({**r, "status": "fail", "error": str(e)})
                continue
            context, committed, lookahead_out = SERIAL.split_core_commit_prefix(
                rows_out, expected_input_character_start=qstart,
                committed_character_start=cursor,
                core_start_sec=core_s, core_end_sec=core_e, final_core=final,
            )
            committed_rows.extend(committed)
            committed_ids = [int(x["global_character_index"]) for x in committed]
            next_cursor = cursor
            if committed_ids:
                next_cursor = max(cursor, max(committed_ids) + 1)
            else:
                next_cursor = min(qend, total)
            trace_rows.append({**r, "status": "ok",
                               "committed": len(committed_ids),
                               "queried": qend - qstart,
                               "cursor": f"{cursor}->{next_cursor}"})
            print(f"  {song} L{wi} core=[{core_s:.1f},{core_e:.1f}] "
                  f"queried={qend - qstart} committed={len(committed_ids)} "
                  f"cursor={cursor}->{next_cursor}", flush=True)
            cursor = next_cursor
            if cursor >= total:
                break

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
        rows_m = [_norm(x) for x in committed_rows]
        best: dict[int, dict] = {}
        for row in rows_m:
            g = int(row["global_character_index"])
            if g not in best:
                best[g] = row
        merged = [best[k] for k in sorted(best)]
        merged.sort(key=lambda x: float(x.get("selected_start_sec") or 0))
        by_line: dict[int, list[dict]] = {}
        for row in merged:
            by_line.setdefault(int(row.get("line_index", 0)), []).append(row)
        lines = [{"line_index": li,
                  "display_text": "".join(x.get("display_text") or x.get("character") or ""
                                          for x in sorted(rs, key=lambda y: int(y.get("index_in_line", 0)))),
                  "character_start": min((int(x.get("global_character_index", -1)) for x in rs), default=0),
                  "character_end": max((int(x.get("global_character_index", -1)) + 1 for x in rs), default=0)}
                 for li, rs in sorted(by_line.items())]
        dur = max((float(x.get("selected_end_sec") or 0) for x in merged), default=0.0)
        out_dir = args.out_root / song / "alignments/r2/vocal/windowed"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "testdemo_shortline_serial_v1",
            "identity": {"request_mode": "full_slot", "decoder_view": "official",
                         "window_plan": "shortline_pad3",
                         "transition": "serial_commit", "runner": "run_testdemo_shortline_serial.py"},
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
    raise SystemExit(main())
