#!/usr/bin/env python3
"""Build an R-CF (coarse_fine) REGION manifest for test-demo songs.

Uses each song's corrected Current full-song alignment (units = whole-song
characters) to snap realign windows: for every R-U/R-S evidence request of the
item, the request's audio window selects characters whose selected interval
overlaps the window's unsafe/target span; those become the region's target
units.  audio_path = the vocals/mix wav used for the Current alignment.

Output: jsonl with fields consumed by run_coarse_fine.py --regions, matching
the E1 screening manifest shape (region_id, song_id, window_index,
detector_state=UNSAFE, seed_kind=unsafe_region, target_unit_ids, units,
audio_path).

Usage:
  PYTHONPATH=src python scripts/unit_realign/build_demo_rcf_regions.py \
     --plan <TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl> \
     --evidence-dir <test_demo>/forward/evidence \
     --current-align <song>:<alignment.json> [...] \
     --audio <song>:<wav> [...] --out <manifest.jsonl>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/realign_recovery/visualization"))


def _overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def _local_context(all_chars, win_chars, context_neighbors: int = 3, gap_sec: float | None = None):
    """Window chars + up to `context_neighbors` chars on each side (by index),
    so len(units) > len(targets).  Returns the ordered subset from all_chars.

    Silence-aware: if ``gap_sec`` is set, units separated from the window's
    time cluster by a gap > ``gap_sec`` are dropped (acoustically separated
    segments never share a region).  ``gap_sec=None`` keeps legacy pure-id
    behaviour.
    """
    from region_silence import context_units_silence_aware
    ids = {int(c["global_character_index"]) for c in win_chars}
    lo = min(ids); hi = max(ids)
    window = [c for c in all_chars if lo - context_neighbors <= int(c["global_character_index"]) <= hi + context_neighbors]
    if gap_sec is None or float(gap_sec) <= 0:
        return window
    return context_units_silence_aware(
        all_chars, sorted(ids), gap_sec, context_neighbors=context_neighbors)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, type=Path)
    ap.add_argument("--evidence-dir", required=True, type=Path, default=None)
    ap.add_argument("--current-align", action="append", default=[],
                    help="SONG=path to the corrected full-song alignment.json")
    ap.add_argument("--audio", action="append", default=[],
                    help="SONG=path to the wav used for alignment")
    ap.add_argument("--identity-template", default=None,
                    help="path to an E1-style screening manifest jsonl; its first "
                         "region's identity_context is reused (model/decoder/code/mapping "
                         "identity constants) for the demo regions so coarse_fine can "
                         "assign a request identity; only audio_sha256 is refreshed.")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--item", action="append", default=[],
                    help="only these item ids (else all with current-align)")
    ap.add_argument("--context-gap-sec", type=float, default=1.5,
                    help="max time gap (s) between neighbouring units allowed inside one "
                         "region's context; 0 disables (legacy pure-id context). "
                         "default 1.5 (= strong_silence_anchor_sec, shared with Current/B4)")
    args = ap.parse_args()

    ident_template = None
    if args.identity_template:
        first = json.loads(Path(args.identity_template).read_text(encoding="utf-8").splitlines()[0])
        ident_template = dict(first.get("identity_context") or {})

    align = {}
    for spec in args.current_align:
        s = spec.split("=", 1)
        if len(s) == 2:
            align[s[0]] = json.loads(Path(s[1]).read_text(encoding="utf-8"))
    audio = {}
    for spec in args.audio:
        s = spec.split("=", 1)
        if len(s) == 2:
            audio[s[0]] = s[1]

    from visualization_controller import load_evidence_index, evidence_payloads_for_family
    idx = load_evidence_index(args.evidence_dir) if args.evidence_dir else {}
    plan = [json.loads(l) for l in args.plan.read_text(encoding="utf-8").splitlines() if l.strip()]

    rows = []
    for item in align:
        if args.item and item not in args.item:
            continue
        adata = align[item]
        a_audio = audio.get(item)
        byidx = {c["global_character_index"]: c for c in adata["characters"]}
        chars = sorted(byidx.values(), key=lambda c: (c.get("selected_start_sec") or 0))
        # group target candidates per request window from evidence
        rids = [str(r["request_id"]) for r in plan if r.get("item") == item]
        seen = set()
        win = 0
        for fam in ("R-U", "R-S"):
            payloads = evidence_payloads_for_family(idx, rids, family=fam) if args.evidence_dir else (
                [p for p in idx.values()
                 if ((p.get("attempt") or {}).get("request") or {}).get("item_id") == item
                 and ((p.get("attempt") or {}).get("request") or {}).get("mutation_parameters", {})
                 .get("proposal_method") == fam]
            )
            for p in payloads:
                rq = (p.get("attempt") or {}).get("request") or {}
                a0 = rq.get("audio_start_sec"); a1 = rq.get("audio_end_sec")
                if a0 is None or a1 is None:
                    continue
                key = (round(float(a0), 3), round(float(a1), 3))
                if key in seen:
                    continue
                seen.add(key)
                # region characters whose interval overlaps the window
                win_chars = [c for c in chars
                             if _overlap(float(c.get("selected_end_sec") or 0),
                                         float(c.get("selected_start_sec") or 0),
                                         float(a0), float(a1))]
                # strictly the interval overlap check: char within window
                win_chars = [c for c in chars
                             if _overlap(float(c.get("selected_start_sec") or 0),
                                         float(c.get("selected_end_sec") or 0),
                                         float(a0), float(a1))]
                if not win_chars:
                    continue
                # build local units = window chars + surrounding context so
                # len(units) > len(targets) (avoid whole_item_pseudo_local).
                local_sel = _local_context(chars, win_chars, context_neighbors=3,
                                           gap_sec=args.context_gap_sec)
                units = [{
                    "canonical_unit_id": int(c["global_character_index"]),
                    "start_sec": c.get("selected_start_sec") or c.get("start_sec"),
                    "end_sec": c.get("selected_end_sec") or c.get("end_sec"),
                    "text": c.get("display_text"),
                } for c in local_sel]
                # R-CF coarse stage-A is *geometrically R-U*: it requires a sparse
                # contiguous target of <=3 units.  Pick the middle min(3,len)
                # contiguous window chars as the coarse->fine target.
                mid = len(win_chars) // 2
                lo_idx = max(0, mid - 1)
                tgt = win_chars[lo_idx:lo_idx + 3][:3]
                targets = [int(c["global_character_index"]) for c in tgt][:3]
                idctx = None
                if ident_template is not None and a_audio:
                    import hashlib
                    try:
                        sha = hashlib.sha256(Path(a_audio).read_bytes()).hexdigest()
                    except OSError:
                        sha = "missing_audio"
                    idctx = dict(ident_template)
                    idctx["audio_sha256"] = sha
                    idctx["context_gap_sec"] = args.context_gap_sec
                rid = str(rq.get("region_id") or rq.get("request_id") or f"test-demo-{item}:{win}")
                rows.append({
                    "region_id": rid,
                    "song_id": item,
                    "window_index": win,
                    "language": adata.get("summary", {}).get("language"),
                    "detector_state": "UNSAFE",
                    "seed_kind": "unsafe_region",
                    "baseline_available": True,
                    "target_unit_ids": targets,
                    "audio_path": a_audio,
                    "units": units,
                    **({"identity_context": idctx} if idctx else {}),
                })
                win += 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} regions -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
