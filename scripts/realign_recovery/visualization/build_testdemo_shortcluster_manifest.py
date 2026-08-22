#!/usr/bin/env python3
"""Build SHORT-WINDOW full-slot manifests by TIME CLUSTERING.

v1 (line-level windows) failed when B4 timestamps split one lyric line
across two repeated occurrences (e.g. 祈愿花开 L14: g105-107 @ 62s,
g108-110 @ 73.6s): the line-span audio crop then covered BOTH occurrences
while the prompt carried only one copy of the text -> the model picked an
ambiguous spot (59.58s drift, MAE 8.9s).

v2 fixes this by clustering characters on their B4 start times:

  - sort characters by start_sec
  - split a new cluster when the time gap to the previous char exceeds
    --gap-sec (default 2.0)
  - require the cluster's global ids to be contiguous
    (max_gidx - min_gidx + 1 == len(cluster)); otherwise the cluster is
    further split on id gaps so each window's document slice contains
    exactly the queried units (no foreign occurrences as context)
  - cap cluster size at --max-units (default 8, unit-realign regime)
  - audio crop = [cluster first start - pad, cluster last end + pad],
    clamped to the song, floored to --min-audio-sec
  - full-slot: every cluster unit is queried

This reproduces the 20260813 unit-realign short-window regime (audio crop
~8.9s, 0-5 text units) on the 3 Chinese test-demo songs.

Output rows are consumable by run_testdemo_slot_infer.py unchanged.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_testdemo_shortcluster_manifest.py \
      --songs "song=lang=b4_alignment.json=vocals.wav" ... \
      --out <manifest.jsonl> [--gap-sec 2.0] [--pad-sec 3.0] \
      [--max-units 8] [--min-audio-sec 6.0]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cluster_units(units: list[dict], gap_sec: float, max_units: int) -> list[list[dict]]:
    """Cluster by GLOBAL ID order with time-continuity guards.

    B4 timestamps can split one lyric line across two repeated occurrences
    (祈愿花开 L14: g105-107 @ 62s, g108-110 @ 73.6s, with other lines' chars
    in between), so time-only clustering merges both occurrences into one
    window.  Instead we walk units in canonical id order and cut a cluster
    when:

      - ids are not contiguous, or
      - start_sec jumps BACKWARD by more than 0.5s (a later id landing in an
        earlier occurrence => occurrence switch), or
      - start_sec jumps FORWARD by more than gap_sec from the PREVIOUS unit
        (a real gap between sung characters => new occurrence)

    NOTE: the forward gap must be measured against the previous unit, NOT
    against the cluster head.  A cluster-head comparison cuts every ~2s of
    continuous singing (g6@16.16 vs g7@16.96 ended up in different windows),
    and because each window is an independent forward, official's per-forward
    monotonic timestamps are no longer guaranteed across the merge -> stacked
    subtitle overlaps.

    Each cluster is then a contiguous id range whose times stay inside one
    occurrence (unit-realign regime), and is capped at max_units.
    """
    by_id = sorted(units, key=lambda u: u["canonical_unit_id"])
    clusters: list[list[dict]] = []
    cur: list[dict] = []
    for u in by_id:
        if cur:
            prev = cur[-1]
            back = prev["start_sec"] - u["start_sec"]
            fwd = u["start_sec"] - prev["start_sec"]
            if (u["canonical_unit_id"] != prev["canonical_unit_id"] + 1
                    or back > 0.5 or fwd > gap_sec):
                clusters.append(cur)
                cur = []
        cur.append(u)
    if cur:
        clusters.append(cur)
    # cap size (keeps id contiguity)
    capped: list[list[dict]] = []
    for cl in clusters:
        for i in range(0, len(cl), max_units):
            capped.append(cl[i:i + max_units])
    return [c for c in capped if c]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", action="append", default=[],
                    help="song=lang=b4_alignment.json=vocals.wav")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--gap-sec", type=float, default=2.0)
    ap.add_argument("--pad-sec", type=float, default=3.0)
    ap.add_argument("--max-units", type=int, default=8)
    ap.add_argument("--min-audio-sec", type=float, default=6.0)
    args = ap.parse_args()

    rows = []
    for spec in args.songs:
        song, lang, align_path, vocal_path = spec.split("=")
        d = json.loads(Path(align_path).read_text(encoding="utf-8"))
        b4_chars = d["characters"]
        duration = max((float(c.get("selected_end_sec") or c.get("end_sec") or 0.0)
                        for c in b4_chars), default=0.0)
        units = []
        for c in b4_chars:
            units.append({
                "canonical_unit_id": int(c["global_character_index"]),
                "text": str(c.get("display_text") or c.get("character") or ""),
                "line_index": int(c.get("line_index", 0)),
                "index_in_line": int(c.get("index_in_line", 0)),
                "start_sec": float(c.get("selected_start_sec") or c.get("start_sec") or 0.0),
                "end_sec": float(c.get("selected_end_sec") or c.get("end_sec")
                                 or c.get("start_sec") or 0.0),
            })
        clusters = cluster_units(units, args.gap_sec, args.max_units)
        all_cids = [u["canonical_unit_id"] for u in units]
        texts = [u["text"] for u in units]
        audio_sha = _sha(Path(vocal_path))
        align_sha = _sha(Path(align_path))
        for ci, cl in enumerate(clusters):
            cl = sorted(cl, key=lambda u: u["canonical_unit_id"])
            cids = [u["canonical_unit_id"] for u in cl]
            # contiguous by construction
            wstart = min(cids)
            wend = max(cids) + 1
            assert wend - wstart == len(cids), (song, ci, cids)
            # audio crop = cluster start-span + pad, clamped, floored to min
            # length.  Use START times only: B4 end_sec values can be
            # contaminated by a later occurrence of the same line
            # (g107 end=73.62 while its start=62.82), which would widen the
            # crop back across both occurrences.
            line_start = min(u["start_sec"] for u in cl)
            line_end = max(u["start_sec"] for u in cl) + 0.8
            audio_s = max(0.0, line_start - args.pad_sec)
            audio_e = min(duration, line_end + args.pad_sec)
            if audio_e - audio_s < args.min_audio_sec:
                mid = (audio_s + audio_e) / 2.0
                half = args.min_audio_sec / 2.0
                audio_s = max(0.0, mid - half)
                audio_e = min(duration, mid + half)
            if audio_e <= audio_s:
                print(f"FAIL {song} C{ci}: empty audio crop", flush=True)
                continue
            slot_local = list(range(wend - wstart))
            local = {cid: i for i, cid in enumerate(cids)}
            row = {
                "schema_version": "testdemo_shortcluster_manifest_v1",
                "request_id": f"{song}:C{ci}:shortcluster",
                "item_id": f"{song}:C{ci}:shortcluster",
                "song_id": song,
                "parent_request_id": None,
                "audio_source": str(Path(vocal_path).resolve()),
                "audio_start_sec": round(audio_s, 4),
                "audio_end_sec": round(audio_e, 4),
                "duration_sec": round(audio_e - audio_s, 4),
                "text_source": "testdemo_timeline",
                "text_start_index": 0,
                "text_end_index": len(texts),
                "text_units": texts,
                "timestamp_slot_indices": slot_local,
                "workflow_mode": "short_cluster_slot",
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
                "window_unit_ids": cids,
                "canonical_timeline_file_sha": "sha256:" + align_sha,
                "timeline_align_path": str(Path(align_path).resolve()),
                "canonical_adapter_version": "testdemo_timeline_v1",
                "source_window_sec": [round(audio_s, 4), round(audio_e, 4)],
                "slot_plan_id": f"shortcluster:C{ci}",
                "comparison_group_id": f"{song}:C{ci}:shortcluster",
                "phase": "full",
                "audio_sha256": "sha256:" + audio_sha,
                "status": "ok",
                "core_start_sec": round(line_start, 4),
                "core_end_sec": round(line_end, 4),
                "window_index": ci,
                "is_final_core": ci == len(clusters) - 1,
                "variant": "shortcluster",
                "window_plan_policy": f"timecluster_gap{args.gap_sec}_pad{args.pad_sec}",
                "cluster_index": ci,
                "cluster_unit_count": len(cids),
            }
            rows.append(row)
        print(f"{song}: {len(clusters)} clusters over {duration:.1f}s", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
