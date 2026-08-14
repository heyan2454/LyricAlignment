#!/usr/bin/env python3
"""Plan A: run the full-slot (20260806 Base) requests by calling ``infer_slice``
DIRECTLY with a B4-identical document (line-text nagisa parse) — bypassing
RealAligner's re-tokenization (which is unstable for Japanese word units).

For each manifest request (silence-aware window from B4 window_trace):
  - document = parse_lyrics_text(line-joined text)  → same unit space as B4
  - infer_slice(processor, model, audio[input crop], document,
                character_start=0, character_end=N_window_units (full song units
                for slot alignment), global_audio_offset_sec=input_start,
                timestamp_slot_indices=window slot local indices)
  - remap request-local rows to canonical ids via canonical_ids (full song)
  - merge per song, write alignment.json (official geometry)

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_testdemo_slot_infer.py \
      --manifest <manifest.jsonl> --out-root <dir> \
      --model-dir <snap> --revision <rev> --checkpoint-path <ckpt> [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo"))

from types import SimpleNamespace  # noqa: E402

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
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    if args.limit:
        ok_rows = ok_rows[:args.limit]

    infer_args = SimpleNamespace(
        device="cuda", model=args.model_dir, revision=args.revision,
        local_files_only=True, cache_dir=None,
        timestamp_segment_sec=0.08, decoder_kind="official",
        decoder_top_k=8, decoder_beam_size=96,
    )
    processor, model = SERIAL.load_model(infer_args, kind="lora", checkpoint=Path(args.checkpoint_path))

    # group requests by song; each song shares one document (full lyric text)
    by_song: dict[str, list[dict]] = {}
    order: list[str] = []
    # document per song: from the first request's canonical full text
    doc_cache: dict[str, object] = {}
    audio_cache: dict[str, object] = {}
    done = 0
    for r in ok_rows:
        song = r["song_id"]
        lang = r["language"]
        if song not in doc_cache:
            # Plan A document = B4-identical line-text parse.  The manifest
            # carries the timeline alignment path; parse its line texts exactly
            # like B4 did (341 units for 乙女), so unit space == B4 == text_units.
            tpath = r.get("timeline_align_path")
            if not tpath or not Path(tpath).is_file():
                print(f"FAIL {song}: no timeline_align_path for document", flush=True)
                continue
            b4d = json.loads(Path(tpath).read_text(encoding="utf-8"))
            line_text = "\n".join(l.get("display_text", "") for l in (b4d.get("lines") or []))
            doc = parse_lyrics_text(line_text, language=lang)
            if len(doc.characters) != len(r["text_units"]):
                print(f"  WARN {song}: doc chars {len(doc.characters)} != text_units "
                      f"{len(r['text_units'])}; document takes precedence "
                      f"(slot indices are over document space)", flush=True)
            doc_cache[song] = doc
        doc = doc_cache[song]
        audio_key = r["audio_source"]
        if audio_key not in audio_cache:
            audio_cache[audio_key] = decode_audio(str(audio_key))
        audio = audio_cache[audio_key]

        inp_s = float(r["audio_start_sec"])
        inp_e = float(r["audio_end_sec"])
        start = int(round(inp_s * 16000))
        end = int(round(inp_e * 16000))
        end = min(end, len(audio))
        if end <= start:
            print(f"FAIL {r['request_id']}: empty audio crop", flush=True)
            continue
        # timestamp slots: manifest timestamp_slot_indices are local indices into
        # the FULL text_units.  We pass them directly (full-slot = range(N),
        # sparse = subset); the document must have the same unit count.
        slot = tuple(r["timestamp_slot_indices"]) if r.get("timestamp_slot_indices") is not None else None
        try:
            rows_out, audit = SERIAL.infer_slice(
                processor=processor,
                model=model,
                audio=audio[start:end],
                document=doc,
                character_start=0,
                character_end=len(doc.characters),
                global_audio_offset_sec=inp_s,
                args=infer_args,
                timestamp_slot_indices=slot,
            )
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {r['request_id']}: {e}", flush=True)
            continue
        # rows are request-local (0..N-1) over the FULL document; canonical id ==
        # local index because document covers the full song.
        if song not in by_song:
            by_song[song] = []
            order.append(song)
        by_song[song].extend(rows_out)
        done += 1
        if done % 10 == 0:
            print(f"progress {done}/{len(ok_rows)}", flush=True)

    # merge per song
    summary = {}
    for song in order:
        rows_out = by_song[song]
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
        rows_out = [_norm(r) for r in rows_out]
        best: dict[int, dict] = {}
        for row in rows_out:
            g = int(row.get("global_character_index", -1))
            if g < 0:
                continue
            if g not in best:
                best[g] = row
            else:
                def dur(r):
                    return float(r.get("selected_end_sec") or 0) - float(r.get("selected_start_sec") or 0)
                if dur(row) > dur(best[g]):
                    best[g] = row
        merged = [best[k] for k in sorted(best)]
        merged.sort(key=lambda r: float(r.get("selected_start_sec") or 0))
        out_dir = args.out_root / song / "alignments/r2/vocal/windowed"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "testdemo_fullslot_silenceaware_v1",
            "identity": {"request_mode": "full_slot", "decoder_view": "official",
                         "window_plan": "silence_aware_60s_10_10_skip_silent",
                         "runner": "run_testdemo_slot_infer.py (Plan A, direct infer_slice)"},
            "summary": {"characters": len(merged)},
            "lines": [], "characters": merged, "window_trace": [],
            "artifact_stage": "real",
        }
        p = out_dir / "alignment.json"
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary[song] = {"characters": len(merged), "path": str(p)}
        print(f"wrote {p} ({len(merged)} chars)", flush=True)

    (args.out_root / "run_summary.json").write_text(
        json.dumps({"schema": "testdemo_fullslot_silenceaware_v1", "songs": summary,
                    "requests_ok": done, "requests_total": len(ok_rows)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"DONE": done, "of": len(ok_rows), "songs": len(order)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
