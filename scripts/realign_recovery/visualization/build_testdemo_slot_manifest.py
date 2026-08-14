#!/usr/bin/env python3
"""Build long-slot (full-slot) requests for test-demo songs using the frozen
20260806 Base windowing, **reusing the B4 alignment's own window_trace** so the
comparison is perfectly controlled:

- same silence-aware 60s/10s/10s windows as B4 (skip-silent applied already),
- same canonical unit space as B4 (parse_lyrics_text over the full lyric text),
- same official decoder (RealAligner default),
- difference is purely full-slot query semantics vs pre-slot serial.

For each B4 window: text_units = characters whose start falls in
[input_start_sec, input_end_sec) (plus the next line for lookahead),
timestamp_slot_indices = all (full-slot).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_testdemo_slot_manifest.py \
      --songs "song=lang=b4_alignment.json=vocals.wav" ... --out <manifest.jsonl>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", action="append", default=[],
                    help="song=lang=b4_alignment.json=vocals.wav")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    rows = []
    for spec in args.songs:
        song, lang, align_path, vocal_path = spec.split("=")
        d = json.loads(Path(align_path).read_text(encoding="utf-8"))
        b4_chars = d["characters"]
        by_gidx = {int(c["global_character_index"]): c for c in b4_chars}
        # Plan A: the runner passes an explicit document (B4 line-text parse),
        # so no re-tokenization happens.  text_units = B4's own characters
        # (they ARE the line-text nagisa parse: same unit space, same gidx).
        units = []
        for c in b4_chars:
            units.append({
                "canonical_unit_id": int(c["global_character_index"]),
                "text": str(c.get("display_text") or c.get("character") or ""),
                "line_index": int(c.get("line_index", 0)),
                "index_in_line": int(c.get("index_in_line", 0)),
            })
        # time per canonical unit from the B4 alignment (selected geometry)
        for u in units:
            g = u["canonical_unit_id"]
            if g in by_gidx:
                bc = by_gidx[g]
                u["start_sec"] = float(bc.get("selected_start_sec") or bc.get("start_sec") or 0.0)
                u["end_sec"] = float(bc.get("selected_end_sec") or bc.get("end_sec") or u["start_sec"])
            else:
                u["start_sec"] = u["end_sec"] = 0.0
        # reuse the B4 window_trace (silence-aware 60/10/10 + skip-silent)
        windows = d.get("window_trace") or []
        audio_sha = _sha(Path(vocal_path))
        seen_req = set()
        for w in windows:
            if not isinstance(w, dict):
                continue
            wi = int(w.get("window_index", -1))
            inp_s = float(w.get("input_start_sec") or w.get("core_start_sec") or 0.0)
            inp_e = float(w.get("input_end_sec") or w.get("core_end_sec") or inp_s + 60.0)
            core_s = float(w.get("core_start_sec") or 0.0)
            core_e = float(w.get("core_end_sec") or inp_e)
            # units whose start falls in the input span
            in_units = [u for u in units if inp_s <= u["start_sec"] < inp_e]
            if not in_units:
                in_units = [u for u in units if u["start_sec"] < inp_e and u["end_sec"] > inp_s]
            if not in_units:
                rows.append({
                    "schema_version": "testdemo_slot_manifest_v1",
                    "song_id": song, "lang": lang,
                    "window_index": wi, "status": "no_units_in_window",
                    "core_start_sec": core_s, "core_end_sec": core_e,
                })
                continue
            in_units.sort(key=lambda u: u["canonical_unit_id"])
            cids = [u["canonical_unit_id"] for u in in_units]
            # next line units for lookahead (units right after the input span)
            cid_set = set(cids)
            max_cid = max(cids)
            lookahead = [u for u in units
                         if u["canonical_unit_id"] > max_cid
                         and u["line_index"] <= in_units[-1]["line_index"] + 1
                         and u["canonical_unit_id"] not in cid_set]
            lookahead.sort(key=lambda u: u["canonical_unit_id"])
            window_cids = cids + [u["canonical_unit_id"] for u in lookahead]
            # Past approach (realign_gate_demo): send the FULL lyric text as
            # text_units (parse-stable, exactly matches parse_lyrics_text over
            # the whole song, incl. word-level ja/en units) and select the
            # window's units via timestamp_slot_indices (local indices into the
            # full text).  audio is the window crop.
            all_cids = [u["canonical_unit_id"] for u in units]
            texts = [u["text"] for u in units]
            slot_set = set(window_cids)
            slot_local = [i for i, cid in enumerate(all_cids) if cid in slot_set]
            cids_window = window_cids
            local = {cid: i for i, cid in enumerate(window_cids)}
            rid = f"{song}:w{wi}:full"
            if rid in seen_req:
                continue
            seen_req.add(rid)
            rows.append({
                "schema_version": "testdemo_slot_manifest_v1",
                "request_id": rid,
                "item_id": rid,
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
                "window_unit_ids": cids_window,
                "canonical_timeline_file_sha": "sha256:" + _sha(Path(align_path)),
                "timeline_align_path": str(Path(align_path).resolve()),
                "canonical_adapter_version": "testdemo_timeline_v1",
                "source_window_sec": [round(inp_s, 4), round(inp_e, 4)],
                "slot_plan_id": f"full:{wi}",
                "comparison_group_id": f"{song}:w{wi}",
                "phase": "full",
                "audio_sha256": "sha256:" + audio_sha,
                "status": "ok",
                "core_start_sec": core_s, "core_end_sec": core_e,
                "window_index": wi,
                "is_final_core": bool(w.get("is_final_core", wi == len(windows) - 1)),
            })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"wrote {len(rows)} rows ({ok} ok) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
