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
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo"))

from types import SimpleNamespace  # noqa: E402

import align_qwen_fa_serial_demo as SERIAL  # noqa: E402
from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
from lyricalign.demo.window_planning import map_compressed_time_to_original  # noqa: E402
from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa: E402


def _remap_compressed_rows(
    rows: list[dict], traces: list[dict], mapping: dict,
) -> tuple[list[dict], list[dict]]:
    """Map compressed-timeline outputs back to the original song clock
    (same key sets and splice-side conventions as the serial demo)."""
    start_time_keys = {
        "start_sec", "raw_global_start_sec", "official_fixed_global_start_sec",
        "fixed_global_start_sec", "selected_start_sec", "core_start_sec",
        "input_start_sec", "effective_input_start_sec",
        "nominal_input_start_sec", "next_input_boundary_sec",
        "lookahead_start_sec", "startup_vocal_onset_sec",
        "first_sustained_activity_sec",
    }
    end_time_keys = {
        "end_sec", "raw_global_end_sec", "official_fixed_global_end_sec",
        "fixed_global_end_sec", "selected_end_sec", "core_end_sec",
        "input_end_sec", "effective_input_end_sec", "lookahead_end_sec",
        "last_sustained_activity_sec",
    }

    # end-key -> start-key pair (same base name); used to detect collapsed
    # splice coordinates (compressed start == compressed end) so the end maps
    # on the SAME side as the start instead of splitting across the splice
    # (which produced start > end, P0-B).
    def _start_pair(key: str) -> str | None:
        if key == "end_sec":
            return "start_sec"
        if key.endswith("_end_sec"):
            base = key[: -len("_end_sec")]
            return f"{base}_start_sec"
        return None

    def convert(value):
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        compressed_starts: dict[str, float] = {}
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                result[key] = convert(child)
                continue
            if key in start_time_keys and isinstance(child, (int, float)) and math.isfinite(float(child)):
                result[f"compressed_{key}"] = float(child)
                result[key] = map_compressed_time_to_original(
                    float(child), mapping, boundary_side="right")
                compressed_starts[key] = float(child)
                continue
            if key in end_time_keys and isinstance(child, (int, float)) and math.isfinite(float(child)):
                result[f"compressed_{key}"] = float(child)
                pair = _start_pair(key)
                if pair is not None and pair in compressed_starts \
                        and abs(compressed_starts[pair] - float(child)) < 1e-9:
                    result[key] = map_compressed_time_to_original(
                        float(child), mapping, boundary_side="right")
                else:
                    result[key] = map_compressed_time_to_original(
                        float(child), mapping, boundary_side="left")
                continue
            result[key] = child
        result["silence_compressed_diagnostic"] = True
        return result

    return convert(rows), convert(traces)


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

    # group requests by song; each song shares one document (full lyric text)
    by_song: dict[str, list[dict]] = {}
    order: list[str] = []
    song_variant: dict[str, str] = {}
    song_slots: dict[str, set[int]] = {}
    # document per song: from the first request's canonical full text
    doc_cache: dict[str, object] = {}
    audio_cache: dict[str, object] = {}
    mapping_cache: dict[str, object] = {}
    done = 0
    for r in ok_rows:
        song = r["song_id"]
        lang = r["language"]
        song_variant.setdefault(song, str(r.get("variant") or "base"))
        if song not in doc_cache:
            # Plan A document = B4-identical line-text parse.  The manifest
            # carries the timeline alignment path; parse its line texts exactly
            # like B4 did (341 units for 乙女), so unit space == B4 == text_units.
            # audio-short manifests instead carry lyrics_path (raw lyric text,
            # no alignment timestamps involved).
            tpath = r.get("timeline_align_path")
            lpath = r.get("lyrics_path")
            if lpath and Path(lpath).is_file():
                line_text = Path(lpath).read_text(encoding="utf-8")
            elif tpath and Path(tpath).is_file():
                b4d = json.loads(Path(tpath).read_text(encoding="utf-8"))
                line_text = "\n".join(l.get("display_text", "") for l in (b4d.get("lines") or []))
            else:
                print(f"FAIL {song}: no timeline_align_path/lyrics_path for document", flush=True)
                continue
            doc = parse_lyrics_text(line_text, language=lang)
            if len(doc.characters) != len(r["text_units"]):
                print(f"  WARN {song}: doc chars {len(doc.characters)} != text_units "
                      f"{len(r['text_units'])}; document takes precedence "
                      f"(slot indices are over document space)", flush=True)
            doc_cache[song] = doc
            # optional compressed-clock remap (C3/C4 variants)
            mpath = r.get("compressed_mapping_path")
            if mpath and Path(mpath).is_file():
                mapping_cache[song] = json.loads(Path(mpath).read_text(encoding="utf-8"))
            elif mpath:
                print(f"FAIL {song}: compressed_mapping_path missing {mpath}", flush=True)
                continue
        doc = doc_cache[song]
        mapping = mapping_cache.get(song)
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
        # timestamp slots: true full-slot = query ALL units in the window.
        # window_unit_ids = canonical ids of this window's units (contiguous in
        # the full-song doc, since doc covers the full song).  Pass
        # character_start/end = window range and timestamp_slot_indices =
        # range(len(window units)) → no pruning → genuine full-slot.
        # textmode3 rows carry an explicit text span (history..lookahead) with
        # slot indices local to that span (sparse → retain_timestamp_slots).
        if "slot_character_start" in r:
            wstart = int(r["history_character_start"])
            wend = int(r["lookahead_character_end"])
            slot_indices = list(r["timestamp_slot_indices"])
        else:
            wids = r.get("window_unit_ids") or []
            if not wids:
                print(f"FAIL {r['request_id']}: no window_unit_ids", flush=True)
                continue
            wstart = min(wids)
            wend = max(wids) + 1
            wids_set = set(int(x) for x in wids)
            # window_unit_ids may contain lookahead gaps; only the window's
            # own units are full-slot queried (P1-2)
            slot_indices = [i for i in range(wend - wstart) if (wstart + i) in wids_set]
        n_win = wend - wstart
        try:
            rows_out, audit = SERIAL.infer_slice(
                processor=processor,
                model=model,
                audio=audio[start:end],
                document=doc,
                character_start=wstart,
                character_end=wend,
                global_audio_offset_sec=inp_s,
                args=infer_args,
                timestamp_slot_indices=slot_indices,
            )
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {r['request_id']}: {e}", flush=True)
            continue
        if mapping is not None:
            rows_out, audit = _remap_compressed_rows(rows_out, audit, mapping)
        # rows are request-local (0..N-1) over the FULL document; canonical id ==
        # local index because document covers the full song.
        if song not in by_song:
            by_song[song] = []
            order.append(song)
        if "slot_unit_ids" in r:
            slot_ids = set(int(x) for x in r["slot_unit_ids"])
            song_slots[song] = song_slots.get(song, set()) | slot_ids
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
        slot_filter = song_slots.get(song)
        for row in rows_out:
            g = int(row.get("global_character_index", -1))
            if g < 0:
                continue
            if slot_filter is not None and g not in slot_filter:
                continue  # textmode: history/lookahead rows are context only
            if g not in best:
                best[g] = row
            else:
                def dur(r):
                    return float(r.get("selected_end_sec") or 0) - float(r.get("selected_start_sec") or 0)
                if dur(row) > dur(best[g]):
                    best[g] = row
        merged = [best[k] for k in sorted(best)]
        merged.sort(key=lambda r: float(r.get("selected_start_sec") or 0))
        # ---- global monotonic fix (cross-window) ----
        # official's _fix_timestamps guarantees monotonicity ONLY inside one
        # forward.  Short-window runs merge independent forwards, so adjacent
        # characters from neighbouring windows can overlap (e.g. g146 ends
        # 94.08 while g147 from the next window starts 93.60) and render as
        # stacked subtitles.  Extend the official snap semantics to the whole
        # song: walk in global-character order and push each row's span to be
        # >= the previous row's end.
        merged.sort(key=lambda r: int(r.get("global_character_index", -1)))
        mono_fixed = 0
        last_end = float("-inf")
        for row in merged:
            s = float(row.get("selected_start_sec") or 0.0)
            e = float(row.get("selected_end_sec") or s)
            if s < last_end:
                s = last_end
                e = max(e, s)
                row["selected_start_sec"] = s
                row["selected_end_sec"] = e
                row["start_sec"] = s
                row["end_sec"] = e
                mono_fixed += 1
            last_end = max(last_end, e)
        merged.sort(key=lambda r: float(r.get("selected_start_sec") or 0))
        # rebuild lines + summary for renderer compatibility
        by_line: dict[int, list[dict]] = {}
        for row in merged:
            by_line.setdefault(int(row.get("line_index", 0)), []).append(row)
        lines = [{"line_index": li,
                  "display_text": "".join(r.get("display_text") or r.get("character") or ""
                                          for r in sorted(rows, key=lambda x: int(x.get("index_in_line", 0)))),
                  "character_start": min((int(r.get("global_character_index", -1)) for r in rows), default=0),
                  "character_end": max((int(r.get("global_character_index", -1)) + 1 for r in rows), default=0)}
                 for li, rows in sorted(by_line.items())]
        dur = max((float(r.get("selected_end_sec") or 0) for r in merged), default=0.0)
        out_dir = args.out_root / song / "alignments/r2/vocal/windowed"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "testdemo_fullslot_silenceaware_v1",
            "identity": {"request_mode": "full_slot", "decoder_view": "official",
                         "window_plan": "silence_aware_60s_10_10_skip_silent",
                         "runner": "run_testdemo_slot_infer.py (Plan A, direct infer_slice)",
                         "monotonic_fix": "cross_window_global_snap",
                         "monotonic_fixed_rows": mono_fixed},
            "summary": {"audio_duration_sec": round(dur, 4), "characters": len(merged)},
            "lines": lines, "characters": merged, "window_trace": [],
            "artifact_stage": "real",
        }
        variant = song_variant.get(song, "base")
        if mapping_cache.get(song) is not None:
            payload["identity"]["window_plan"] = "compressed_clock_remapped_to_original"
        elif variant == "strict":
            payload["identity"]["window_plan"] = "strict_per_region_soft_60s_10_10"
        payload["identity"]["variant"] = variant
        if mapping_cache.get(song) is not None:
            payload["silence_compression_mapping"] = mapping_cache[song]
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
