#!/usr/bin/env python3
"""B-group detector: score the 33 C1 (full-slot) alignments with the Detector V2
frozen family (official view, best_combo O = official features + official
neighborhood), then aggregate rejected/uncertain units into hard regions.

Pipeline:
  1. Train a standardized logistic on the corrected run2 evidence (target=
     official labels, O features) — Logistic is convex from zero init so the
     frozen family is reproducible; the FROZEN operating thresholds are used
     verbatim (T_accept/T_reject ~0.1107, official view).
  2. Score every unit of every C1 alignment (raw entropy/margin/topk and
     official geometry are already stored in the C1 output).
  3. Tri-state -> consecutive reject/uncertain runs -> one region per run
     (E1 manifest shape: region_id, song_id, window_index, detector_state,
     seed_kind=unsafe_region, target_unit_ids, units, audio_path,
     identity_context).

Usage:
  PYTHONPATH=src python scripts/unit_realign/build_bgroup_regions.py \
      --c1-root /home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4/align \
      --out <REGIONS.jsonl> [--min-run 1] [--context 4] [--b4-root ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from lyricalign.research_v7.detector_v2_evidence import (  # noqa: E402
    EvidenceRow, RawView, OfficialView,
)
from lyricalign.research_v7.detector_v2_features import (  # noqa: E402
    O_FEATURE_KEYS, NEIGHBORHOOD_FEATURE_KEYS, build_neighbors, unit_feature_row,
)
from lyricalign.research_v7.region_assessor import LogisticAssessor  # noqa: E402

RUN2 = "/home/hyan/Data/lyricalign/runs/research_v7_detector_v2/run2"
FROZEN = "/home/hyan/Data/lyricalign/runs/research_v7_detector_v2/phaseB_final/FROZEN_OPERATING_POINTS.json"
E1_TEMPLATE = "/home/hyan/Data/lyricalign/runs/20260814_E1_screening_manifest.jsonl"

O_KEYS = list(O_FEATURE_KEYS) + [k for k in NEIGHBORHOOD_FEATURE_KEYS if k.startswith("official")]


def load_evidence_and_labels() -> tuple[list[EvidenceRow], dict]:
    """Load run2 evidence rows + official-target labels (safe=0/unsafe=1)."""
    rows: list[EvidenceRow] = []
    labels: dict[tuple[str, int], str] = {}
    for line in Path(RUN2, "LABELS.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("target") != "official":
            continue
        labels[(r["request_identity"], int(r["canonical_unit_id"]))] = r["label"]
    ev_dir = Path(RUN2, "evidence_v2")
    for p in sorted(ev_dir.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            entries = payload if isinstance(payload, list) else [payload]
            for r in entries:
                raw = r.get("raw") or {}
                off = r.get("official") or {}
                rows.append(EvidenceRow(
                    request_identity=str(r["request_identity"]),
                    view_id=str(r.get("view_id", "full")),
                    canonical_unit_id=int(r["canonical_unit_id"]),
                    raw=RawView(
                        start_sec=raw.get("start_sec"), end_sec=raw.get("end_sec"),
                        start_entropy=raw.get("start_entropy"), end_entropy=raw.get("end_entropy"),
                        start_margin=raw.get("start_margin"), end_margin=raw.get("end_margin"),
                        topk=tuple(raw.get("topk") or ()),
                    ),
                    official=OfficialView(
                        start_sec=off.get("start_sec"), end_sec=off.get("end_sec"),
                        repair_start_shift_sec=off.get("repair_start_shift_sec"),
                        repair_end_shift_sec=off.get("repair_end_shift_sec"),
                    ),
                ))
    return rows, labels


def feature_vector(row: EvidenceRow, rows_sorted: list[EvidenceRow]) -> np.ndarray:
    idx = rows_sorted.index(row)
    neighbors = build_neighbors(rows_sorted, idx)
    fr = unit_feature_row(row, neighbors=neighbors)
    return np.array([fr.get(k) if fr.get(k) is not None else 0.0 for k in O_KEYS], dtype=np.float64)


def train() -> tuple[LogisticAssessor, list[str]]:
    rows, labels = load_evidence_and_labels()
    by_request: dict[str, list[EvidenceRow]] = {}
    for r in rows:
        by_request.setdefault(r.request_identity, []).append(r)
    X, y = [], []
    for req_rows in by_request.values():
        req_rows.sort(key=lambda r: r.canonical_unit_id)
        for r in req_rows:
            lab = labels.get((r.request_identity, r.canonical_unit_id))
            if lab not in ("safe", "unsafe"):
                continue
            X.append(feature_vector(r, req_rows))
            y.append(1.0 if lab == "unsafe" else 0.0)
    X = np.array(X, dtype=np.float64)
    y = np.array(y, dtype=np.float64)
    print(f"train: n={len(y)} unsafe={int(y.sum())} ({y.mean():.3f})", flush=True)
    m = LogisticAssessor().fit(X, y)
    return m, O_KEYS


def c1_rows_to_evidence(chars: list[dict]) -> list[EvidenceRow]:
    rows = []
    for c in sorted(chars, key=lambda x: int(x["global_character_index"])):
        rows.append(EvidenceRow(
            request_identity="c1", view_id="full",
            canonical_unit_id=int(c["global_character_index"]),
            raw=RawView(
                start_sec=c.get("raw_global_start_sec"), end_sec=c.get("raw_global_end_sec"),
                start_entropy=c.get("raw_start_entropy"), end_entropy=c.get("raw_end_entropy"),
                start_margin=c.get("raw_start_margin"), end_margin=c.get("raw_end_margin"),
                topk=tuple(c.get("raw_start_topk_probabilities") or ()),
            ),
            official=OfficialView(
                start_sec=c.get("official_fixed_global_start_sec"),
                end_sec=c.get("official_fixed_global_end_sec"),
                repair_start_shift_sec=0.0, repair_end_shift_sec=0.0,
            ),
        ))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--c1-root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--min-run", type=int, default=1)
    ap.add_argument("--merge-gap", type=int, default=2,
                    help="merge reject/uncertain runs separated by <= this many units")
    ap.add_argument("--context", type=int, default=4,
                    help="context units on each side of a hard run (in units)")
    ap.add_argument("--b4-root", action="append", default=[],
                    help="B4 alignment root to resolve owner_window_index (repeatable)")
    ap.add_argument("--audio-map", default=None,
                    help="json mapping song -> vocals wav path (else resolve vocally)")
    args = ap.parse_args()

    m, keys = train()
    frozen = json.loads(Path(FROZEN).read_text(encoding="utf-8"))
    op = frozen["official"]["standardized_logistic"]["operating_points"]
    t_accept = float(op["T_accept"])
    t_reject = float(op["T_reject"])
    print(f"frozen thresholds: accept>={t_accept:.6f} reject<{t_reject:.6f}", flush=True)

    template = json.loads(Path(E1_TEMPLATE).read_text(encoding="utf-8").splitlines()[0])
    ident_base = dict(template["identity_context"])
    ident_base["decoder_identity"] = "official"

    audio_map = {}
    if args.audio_map:
        audio_map = json.loads(Path(args.audio_map).read_text(encoding="utf-8"))

    owner_map: dict[str, dict[int, int]] = {}
    b4_roots = [Path(x) for x in args.b4_root]
    for song_dir in sorted(args.c1_root.iterdir()):
        if not song_dir.is_dir():
            continue
        song = song_dir.name
        owner = {}
        for root in b4_roots:
            for cand in (root / song / "alignments/r2/vocal/windowed/alignment.json",
                         root / song.replace(" ", "_") / "alignments/r2/vocal/windowed/alignment.json"):
                if cand.is_file():
                    b4d = json.loads(cand.read_text(encoding="utf-8"))
                    for c in b4d.get("characters") or []:
                        owner[int(c["global_character_index"])] = int(c.get("owner_window_index", -1))
                    break
            if owner:
                break
        owner_map[song] = owner

    regions = []
    n_reject = n_uncertain = n_accept = 0
    for song_dir in sorted(args.c1_root.iterdir()):
        if not song_dir.is_dir():
            continue
        song = song_dir.name
        apath = song_dir / "alignments/r2/vocal/windowed/alignment.json"
        if not apath.is_file():
            continue
        d = json.loads(apath.read_text(encoding="utf-8"))
        chars = d["characters"]
        rows = c1_rows_to_evidence(chars)
        rows.sort(key=lambda r: r.canonical_unit_id)
        X = np.array([feature_vector(r, rows) for r in rows], dtype=np.float64)
        proba = m.predict_proba(X)
        states: dict[int, str] = {}
        for r, p in zip(rows, proba):
            if p >= t_accept:
                states[r.canonical_unit_id] = "accept"
            elif p < t_reject:
                states[r.canonical_unit_id] = "reject"
            else:
                states[r.canonical_unit_id] = "uncertain"
        n_accept += sum(1 for v in states.values() if v == "accept")
        n_reject += sum(1 for v in states.values() if v == "reject")
        n_uncertain += sum(1 for v in states.values() if v == "uncertain")

        ids = sorted(states)
        # consecutive runs of reject/uncertain
        raw_runs: list[list[int]] = []
        cur: list[int] = []
        for g in ids:
            if states[g] in ("reject", "uncertain"):
                cur.append(g)
            else:
                if len(cur) >= args.min_run:
                    raw_runs.append(cur)
                cur = []
        if len(cur) >= args.min_run:
            raw_runs.append(cur)
        # merge runs separated by <= merge_gap units (spread rejects collapse
        # into one hard region instead of one region per isolated unit)
        runs: list[list[int]] = []
        for rr in raw_runs:
            if runs and rr[0] - runs[-1][-1] - 1 <= args.merge_gap:
                runs[-1].extend(rr)
            else:
                runs.append(list(rr))

        audio = audio_map.get(song) if audio_map else None
        if audio is None:
            audio = ""
        owner = owner_map.get(song, {})
        for run_index, run in enumerate(runs):
            lo, hi = run[0], run[-1]
            target = list(range(lo, hi + 1))
            unit_ids_all = sorted(r.canonical_unit_id for r in rows)
            ctx_lo = max(0, lo - args.context)
            ctx_hi = min(len(unit_ids_all) - 1, hi + args.context)
            unit_ids = list(range(unit_ids_all[ctx_lo], unit_ids_all[ctx_hi] + 1))
            units = []
            for g in unit_ids:
                c = next((x for x in chars if int(x["global_character_index"]) == g), None)
                if c is None:
                    continue
                units.append({
                    "canonical_unit_id": int(c["global_character_index"]),
                    "text": str(c.get("display_text") or c.get("character") or ""),
                    "start_sec": float(c.get("selected_start_sec") or 0.0),
                    "end_sec": float(c.get("selected_end_sec") or 0.0),
                    "reference_start_sec": float(c.get("raw_global_start_sec") or 0.0),
                    "reference_end_sec": float(c.get("raw_global_end_sec") or 0.0),
                })
            win = owner.get(lo, -1)
            ident = dict(ident_base)
            if audio:
                import hashlib
                ident["audio_sha256"] = "sha256:" + hashlib.sha256(Path(audio).read_bytes()).hexdigest()
            regions.append({
                "region_id": f"{song}:w{win}:unsafe:{len(target)}",
                "song_id": song,
                "window_index": win,
                "detector_state": "UNSAFE",
                "seed_kind": "unsafe_region",
                "target_unit_ids": target,
                "units": units,
                "audio_path": audio,
                "language": None,
                "baseline_available": True,
                "overlap_interval_sec": None,
                "left_anchor_candidates": [],
                "right_anchor_candidates": [],
                "identity_context": ident,
            })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in regions:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({
        "regions": len(regions), "accept": n_accept, "reject": n_reject,
        "uncertain": n_uncertain, "out": str(args.out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
