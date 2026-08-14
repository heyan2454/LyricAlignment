#!/usr/bin/env python3
"""Run the test-demo full-slot (silence-aware Base) requests with the real
executor (official decoder) and merge per-window official rows into one
full-song alignment.json per song.

Output: <out-root>/<song>/alignments/r2/vocal/windowed/alignment.json
(schema testdemo_fullslot_silenceaware_v1), plus a per-song merge summary.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_testdemo_slot_align.py \
      --manifest <manifest.jsonl> --out-root <dir> \
      --model-dir <snapshot> --revision <rev> --checkpoint-path <ckpt> [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from lyricalign.research_v7.real_executor import RealAligner  # noqa: E402
from lyricalign.research_v7.requests import AlignmentRequest  # noqa: E402


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

    aligner = RealAligner(model_dir=args.model_dir, revision=args.revision,
                          checkpoint=args.checkpoint_path, device="cuda")
    by_song: dict[str, list[dict]] = {}
    order: list[str] = []
    done = 0
    for r in ok_rows:
        song = r["song_id"]
        req = AlignmentRequest(
            request_id=r["request_id"], item_id=r["item_id"],
            parent_request_id=r.get("parent_request_id"),
            audio_source=r["audio_source"],
            audio_start_sec=float(r["audio_start_sec"]),
            audio_end_sec=float(r["audio_end_sec"]),
            text_source=r.get("text_source", "testdemo_timeline"),
            text_start_index=int(r["text_start_index"]),
            text_end_index=int(r["text_end_index"]),
            text_units=tuple(r["text_units"]),
            timestamp_slot_indices=tuple(r["timestamp_slot_indices"]) if r.get("timestamp_slot_indices") is not None else None,
            workflow_mode=r.get("workflow_mode", "long_slot_60s"),
            mutation_type=r.get("mutation_type", "baseline"),
            mutation_parameters=r.get("mutation_parameters", {}),
            model_id=r.get("model_id", "Qwen3-ForcedAligner-0.6B-hf"),
            checkpoint_id=r.get("checkpoint_id", "r2-step-000750"),
            input_variant=r.get("input_variant", "text_mutation"),
            canonical_text_start=r.get("canonical_text_start"),
            canonical_text_end=r.get("canonical_text_end"),
            canonical_to_local=r.get("canonical_to_local"),
            canonical_ids=r.get("canonical_ids"),
            canonical_timeline_file_sha=r.get("canonical_timeline_file_sha"),
            canonical_adapter_version=r.get("canonical_adapter_version"),
            source_window_sec=tuple(r["source_window_sec"]) if r.get("source_window_sec") else None,
            metadata={"language": r.get("language"), "window_index": r.get("window_index"),
                      "core_start_sec": r.get("core_start_sec"), "core_end_sec": r.get("core_end_sec"),
                      "is_final_core": r.get("is_final_core"), "status": "ok"},
        )
        try:
            rows_out = aligner.align_request(req)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {r['request_id']}: {e}", flush=True)
            continue
        # RealAligner returns request-local global_character_index (0..n-1);
        # remap to the canonical id via canonical_ids (local i -> canonical i).
        cids = r.get("canonical_ids") or []
        for row in rows_out:
            li = int(row.get("global_character_index", -1))
            if 0 <= li < len(cids):
                row["global_character_index"] = cids[li]
        if song not in by_song:
            by_song[song] = []
            order.append(song)
        by_song[song].extend(rows_out)
        done += 1
        if done % 10 == 0:
            print(f"progress {done}/{len(ok_rows)}", flush=True)

    # Merge per song into a full-song alignment.json
    summary = {}
    for song in order:
        rows_out = by_song[song]
        # Normalize RealAligner rows (official geometry) into the alignment
        # schema used by renderers: selected_start_sec/selected_end_sec and
        # start_sec/end_sec mirror official_fixed_global_*.
        def _norm(row: dict) -> dict:
            s = float(row.get("official_fixed_global_start_sec")
                      if row.get("official_fixed_global_start_sec") is not None
                      else row.get("fixed_global_start_sec") or row.get("raw_global_start_sec") or 0.0)
            e = float(row.get("official_fixed_global_end_sec")
                      if row.get("official_fixed_global_end_sec") is not None
                      else row.get("fixed_global_end_sec") or row.get("raw_global_end_sec") or s)
            out = dict(row)
            out["start_sec"] = s
            out["end_sec"] = e
            out["selected_start_sec"] = s
            out["selected_end_sec"] = e
            out["decoder_kind"] = "official"
            return out
        rows_out = [_norm(r) for r in rows_out]
        # dedupe by global_character_index, keep the one with the later (more
        # committed) owner window
        best: dict[int, dict] = {}
        for row in rows_out:
            g = int(row.get("global_character_index", -1))
            if g < 0:
                continue
            if g not in best:
                best[g] = row
            else:
                # prefer row with a non-zero duration
                def dur(r):
                    return float(r.get("selected_end_sec") or 0) - float(
                        r.get("selected_start_sec") or 0)
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
                         "manifest": str(args.manifest)},
            "summary": {"audio_duration_sec": None, "characters": len(merged)},
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
