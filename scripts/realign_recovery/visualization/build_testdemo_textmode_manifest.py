#!/usr/bin/env python3
"""Build the A-group "text-providing mode 3" manifest (13 §4.3 historical-best):

For each B4 window (same windows/audio as C1 full-slot):
  - history text:   [window.committed_character_start, slot_start) as context
                    (NOT queried)
  - slot region:    first 32 units of the window's owner units (queried)
  - future lookahead: next 16 units after the slot region (NOT queried)
  - text span:      [committed_character_start, slot_end + 16)

The request semantics differ from full-slot only in text structure: the
queried unit set is a 32-unit slot region with history+lookahead context.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_testdemo_textmode_manifest.py \
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

SLOT_UNITS = 32
LOOKAHEAD_UNITS = 16


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
        windows = d.get("window_trace") or []
        audio_sha = _sha(Path(vocal_path))
        traces_by_win = {int(w.get("window_index", -1)): w for w in windows}
        seen_req = set()
        for w in windows:
            wi = int(w.get("window_index", -1))
            inp_s = float(w.get("input_start_sec") or w.get("core_start_sec") or 0.0)
            inp_e = float(w.get("input_end_sec") or w.get("core_end_sec") or inp_s + 60.0)
            core_s = float(w.get("core_start_sec") or 0.0)
            core_e = float(w.get("core_end_sec") or inp_e)
            in_units = [u for u in units if u.get("owner_window_index") == wi]
            if not in_units:
                in_units = [u for u in units if core_s <= u["start_sec"] < core_e]
            if not in_units:
                continue
            in_units.sort(key=lambda u: u["canonical_unit_id"])
            slot_units = in_units[:SLOT_UNITS]
            # history start = this window's committed cursor (B4 trace) if
            # present and <= slot start; else document start
            committed_start = traces_by_win.get(wi, {}).get("committed_character_start")
            slot_start = slot_units[0]["canonical_unit_id"]
            hist_start = slot_start
            if committed_start is not None and int(committed_start) <= slot_start:
                hist_start = int(committed_start)
            slot_end = slot_units[-1]["canonical_unit_id"] + 1
            lookahead_end = min(len(units), slot_end + LOOKAHEAD_UNITS)
            text_start, text_end = hist_start, lookahead_end
            all_cids = [u["canonical_unit_id"] for u in units]
            texts = [u["text"] for u in units]
            # local indices of slot units within [text_start, text_end)
            slot_local = [cid - text_start for cid in range(slot_start, slot_end)
                          if text_start <= cid < text_end]
            if not slot_local:
                continue
            rid = f"{song}:w{wi}:textmode"
            if rid in seen_req:
                continue
            seen_req.add(rid)
            local = {cid: i for i, cid in enumerate(range(text_start, text_end))}
            rows.append({
                "schema_version": "testdemo_textmode_manifest_v1",
                "request_id": rid,
                "item_id": rid,
                "song_id": song,
                "parent_request_id": None,
                "audio_source": str(Path(vocal_path).resolve()),
                "audio_start_sec": round(inp_s, 4),
                "audio_end_sec": round(inp_e, 4),
                "duration_sec": round(inp_e - inp_s, 4),
                "text_source": "testdemo_timeline",
                "text_start_index": text_start,
                "text_end_index": text_end,
                "text_units": texts,
                "timestamp_slot_indices": slot_local,
                "workflow_mode": "long_slot_textmode3",
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
                "window_unit_ids": [u["canonical_unit_id"] for u in in_units],
                "slot_unit_ids": [u["canonical_unit_id"] for u in slot_units],
                "canonical_timeline_file_sha": "sha256:" + _sha(Path(align_path)),
                "timeline_align_path": str(Path(align_path).resolve()),
                "canonical_adapter_version": "testdemo_timeline_v1",
                "source_window_sec": [round(inp_s, 4), round(inp_e, 4)],
                "slot_plan_id": f"textmode:{wi}",
                "comparison_group_id": f"{song}:w{wi}:textmode",
                "phase": "full",
                "audio_sha256": "sha256:" + audio_sha,
                "status": "ok",
                "core_start_sec": core_s, "core_end_sec": core_e,
                "window_index": wi,
                "is_final_core": bool(w.get("is_final_core", wi == len(windows) - 1)),
                "variant": "textmode3",
                "slot_character_start": slot_start,
                "slot_character_end": slot_end,
                "history_character_start": hist_start,
                "lookahead_character_end": lookahead_end,
            })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"textmode3 wrote {len(rows)} rows ({ok} ok) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
