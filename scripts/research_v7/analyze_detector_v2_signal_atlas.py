#!/usr/bin/env python3
"""Detector V2 signal atlas: per-feature discriminative power (AUC, unsafe vs safe).

Reads research_v7 evidence_v2 (per-request sha256:*.jsonl, rows as JSON lines of
EvidenceRow lists) joined with LABELS.jsonl (per request_identity/view_id/
canonical_unit_id and target raw/official).  Excludes grey / ambiguous /
gt_unavailable labels, separates the raw and official label targets, and reports
rank-based AUC per feature per target.  Hidden (H) features whose rows have
hidden.available=false are counted as "blocked" and excluded from AUC.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import Counter
from pathlib import Path

R_FEATURE_KEYS = (
    "raw_start_entropy",
    "raw_end_entropy",
    "raw_start_margin",
    "raw_end_margin",
    "raw_duration_sec",
    "raw_zero_duration",
    "raw_inverted",
    "raw_gap_to_prev_sec",
    "raw_gap_to_next_sec",
    "raw_top1_top2_margin",
    "raw_topk_span",
    "raw_topk_variance",
)
O_FEATURE_KEYS = (
    "official_duration_sec",
    "ro_start_shift_sec",
    "ro_end_shift_sec",
    "repair_start_shift_sec",
    "repair_end_shift_sec",
    "repair_run_length",
    "has_repair",
)
H_FEATURE_KEYS = (
    "hidden_start_norm",
    "hidden_start_variance",
    "hidden_start_end_cosine",
    "hidden_start_end_l2",
    "hidden_end_norm",
    "hidden_end_variance",
)
CV_FEATURE_KEYS = (
    "cv_start_diff_sec",
    "cv_end_diff_sec",
    "cv_posterior_distance",
    "cv_n_views",
)
FEATURE_GROUPS = {
    "R": R_FEATURE_KEYS,
    "O": O_FEATURE_KEYS,
    "H": H_FEATURE_KEYS,
    "cross_view": CV_FEATURE_KEYS,
}
ALL_FEATURE_KEYS = tuple(R_FEATURE_KEYS + O_FEATURE_KEYS + H_FEATURE_KEYS + CV_FEATURE_KEYS)
TARGETS = ("raw", "official")
EXCLUDED_LABELS = ("grey", "ambiguous", "gt_unavailable")


def _fnum(value):
    return value if isinstance(value, (int, float)) else None


def _rstart(row):
    raw = row.get("raw") or {}
    return _fnum(raw.get("start_sec"))


def load_labels(path):
    """(request_identity, view_id, canonical_unit_id) -> {target: label}."""
    labels = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = (row.get("request_identity"), row.get("view_id"), row.get("canonical_unit_id"))
            labels.setdefault(key, {})[row.get("target")] = row.get("label")
    return labels


def _last_frame_probs(raw):
    topk = raw.get("topk")
    if not isinstance(topk, list) or not topk:
        return []
    last = topk[-1]
    if isinstance(last, dict):
        return [v for v in last.values() if isinstance(v, (int, float))]
    if isinstance(last, (list, tuple)):
        return [p for _, p in last if isinstance(p, (int, float))]
    return []


def _hidden_vectors(hid):
    def _vec(value):
        if isinstance(value, dict):
            return [v for v in value.values() if isinstance(v, (int, float))]
        if isinstance(value, (list, tuple)):
            return [v for v in value if isinstance(v, (int, float))]
        return []

    return _vec(hid.get("start")), _vec(hid.get("end"))


def row_features(row, prev_row, next_row):
    """Feature dict (ALL_FEATURE_KEYS) plus (features, blocked_hidden) flag."""
    raw = row.get("raw") or {}
    off = row.get("official") or {}
    hid = row.get("hidden") or {}
    cvo = row.get("cross_view") or {}
    feats = {}

    start_sec = _fnum(raw.get("start_sec"))
    end_sec = _fnum(raw.get("end_sec"))
    feats["raw_start_entropy"] = _fnum(raw.get("start_entropy"))
    feats["raw_end_entropy"] = _fnum(raw.get("end_entropy"))
    feats["raw_start_margin"] = _fnum(raw.get("start_margin"))
    feats["raw_end_margin"] = _fnum(raw.get("end_margin"))
    dur = (end_sec - start_sec) if (start_sec is not None and end_sec is not None) else None
    feats["raw_duration_sec"] = dur
    feats["raw_zero_duration"] = 1 if dur == 0 else 0
    feats["raw_inverted"] = 1 if (start_sec is not None and end_sec is not None and end_sec < start_sec) else 0

    prev_end = _fnum((prev_row.get("raw") or {}).get("end_sec")) if prev_row else None
    next_start = _rstart(next_row) if next_row else None
    feats["raw_gap_to_prev_sec"] = (start_sec - prev_end) if (start_sec is not None and prev_end is not None) else None
    feats["raw_gap_to_next_sec"] = (next_start - end_sec) if (next_start is not None and end_sec is not None) else None

    probs = _last_frame_probs(raw)
    if probs:
        p1 = probs[0]
        p2 = probs[1] if len(probs) > 1 else 0.0
        feats["raw_top1_top2_margin"] = p1 - p2
        feats["raw_topk_span"] = max(probs) - min(probs)
        if len(probs) >= 2:
            feats["raw_topk_variance"] = statistics.pvariance(probs)
        else:
            feats["raw_topk_variance"] = 0.0
    else:
        feats["raw_top1_top2_margin"] = None
        feats["raw_topk_span"] = None
        feats["raw_topk_variance"] = None

    o_start = _fnum(off.get("start_sec"))
    o_end = _fnum(off.get("end_sec"))
    feats["official_duration_sec"] = (o_end - o_start) if (o_start is not None and o_end is not None) else None
    feats["ro_start_shift_sec"] = (o_start - start_sec) if (o_start is not None and start_sec is not None) else None
    feats["ro_end_shift_sec"] = (o_end - end_sec) if (o_end is not None and end_sec is not None) else None
    rs = _fnum(off.get("repair_start_shift_sec"))
    re_ = _fnum(off.get("repair_end_shift_sec"))
    feats["repair_start_shift_sec"] = rs
    feats["repair_end_shift_sec"] = re_
    feats["repair_run_length"] = _fnum(off.get("repair_run_length"))
    feats["has_repair"] = 1 if (rs or re_) else 0

    blocked = not (hid.get("available") is True and hid.get("schema"))
    sv, ev = _hidden_vectors(hid)
    if blocked or not sv:
        h_start_norm = h_start_var = h_end_norm = h_end_var = h_cos = h_l2 = None
    else:
        h_start_norm = math.sqrt(sum(v * v for v in sv))
        h_start_var = statistics.pvariance(sv) if len(sv) >= 2 else 0.0
        h_end_norm = math.sqrt(sum(v * v for v in ev)) if ev else 0.0
        h_end_var = statistics.pvariance(ev) if len(ev) >= 2 else 0.0
        h_cos = 0.0
        if sv and ev and h_start_norm > 0 and h_end_norm > 0:
            dot = sum(a * b for a, b in zip(sv, ev))
            h_cos = dot / (h_start_norm * h_end_norm)
        h_l2 = math.sqrt(sum((a - b) ** 2 for a, b in zip(sv, ev))) if (sv and ev and len(sv) == len(ev)) else None
    feats["hidden_start_norm"] = h_start_norm
    feats["hidden_start_variance"] = h_start_var
    feats["hidden_start_end_cosine"] = h_cos
    feats["hidden_start_end_l2"] = h_l2
    feats["hidden_end_norm"] = h_end_norm
    feats["hidden_end_variance"] = h_end_var

    if isinstance(cvo, dict) and cvo:
        feats["cv_n_views"] = len(cvo.get("views") or []) if isinstance(cvo.get("views"), list) else len(cvo)
        feats["cv_start_diff_sec"] = _fnum(cvo.get("start_diff_sec"))
        feats["cv_end_diff_sec"] = _fnum(cvo.get("end_diff_sec"))
        feats["cv_posterior_distance"] = _fnum(cvo.get("posterior_distance"))
    else:
        feats["cv_n_views"] = None
        feats["cv_start_diff_sec"] = None
        feats["cv_end_diff_sec"] = None
        feats["cv_posterior_distance"] = None

    return feats, blocked


def _auc(pos, neg):
    n_pos, n_neg = len(pos), len(neg)
    if n_pos < 2 or n_neg < 2:
        return None
    combined = [(v, True) for v in pos] + [(v, False) for v in neg]
    combined.sort(key=lambda item: item[0])
    total_rank = 0.0
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            if combined[k][1]:
                total_rank += avg_rank
        i = j + 1
    u = total_rank - n_pos * (n_pos + 1) / 2.0
    return u / (n_pos * n_neg)


def build_signal_atlas(evidence_dir, labels_path, limit_requests=None):
    labels = load_labels(labels_path)
    per_target = {
        target: {key: {"values": [], "y": [], "blocked": 0} for key in ALL_FEATURE_KEYS}
        for target in TARGETS
    }
    counts = {"requests": 0, "rows": 0, "excluded_by_label": Counter(), "blocked_hidden_rows": 0}
    seen_requests = set()

    files = [p for p in sorted(os.listdir(evidence_dir)) if p.startswith("sha256:")]
    if limit_requests:
        files = files[:limit_requests]
    for fn in files:
        with open(os.path.join(evidence_dir, fn)) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                rows = obj if isinstance(obj, list) else [obj]
                rows.sort(key=lambda r: (_rstart(r) if _rstart(r) is not None else math.inf))
                for i, row in enumerate(rows):
                    counts["rows"] += 1
                    rid = row.get("request_identity")
                    if rid is not None and rid not in seen_requests:
                        seen_requests.add(rid)
                        counts["requests"] += 1
                    key = (rid, row.get("view_id"), row.get("canonical_unit_id"))
                    lmap = labels.get(key, {})
                    feats, blocked = row_features(row, rows[i - 1] if i else None, rows[i + 1] if i + 1 < len(rows) else None)
                    if blocked:
                        counts["blocked_hidden_rows"] += 1
                    for target in TARGETS:
                        lab = lmap.get(target)
                        if lab is None or lab in EXCLUDED_LABELS:
                            counts["excluded_by_label"][lab if lab is not None else "unlabeled"] += 1
                            continue
                        y = 1 if lab == "unsafe" else 0
                        for key_name, value in feats.items():
                            store = per_target[target][key_name]
                            if key_name in H_FEATURE_KEYS and blocked:
                                store["blocked"] += 1
                            elif isinstance(value, (int, float)) and math.isfinite(value):
                                store["values"].append(value)
                                store["y"].append(y)

    targets_out = {}
    for target in TARGETS:
        features_out = {}
        ranking = []
        anchor = per_target[target]["raw_end_entropy"]
        labeled_units = len(anchor["values"]) + anchor["blocked"]
        for key_name, store in per_target[target].items():
            pos = [v for v, y in zip(store["values"], store["y"]) if y == 1]
            neg = [v for v, y in zip(store["values"], store["y"]) if y == 0]
            entry = {
                "auc": None,
                "n_pos": len(pos),
                "n_neg": len(neg),
                "pos_mean": statistics.fmean(pos) if pos else None,
                "neg_mean": statistics.fmean(neg) if neg else None,
                "blocked": store["blocked"],
            }
            auc = _auc(pos, neg)
            if auc is not None:
                entry["auc"] = round(auc, 6)
                ranking.append(key_name)
            features_out[key_name] = entry
        ranking.sort(key=lambda k: features_out[k]["auc"], reverse=True)
        targets_out[target] = {
            "features": features_out,
            "ranking": ranking,
            "top": ranking[0] if ranking else None,
            "labeled_units": labeled_units,
        }

    return {
        "schema_version": "detector_v2_signal_atlas_v1",
        "inputs": {
            "evidence_v2_dir": str(evidence_dir),
            "labels": str(labels_path),
            "limit_requests": limit_requests,
        },
        "counts": {
            "requests": counts["requests"],
            "rows": counts["rows"],
            "blocked_hidden_rows": counts["blocked_hidden_rows"],
            "excluded_by_label": dict(counts["excluded_by_label"]),
        },
        "targets": targets_out,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Detector V2 signal atlas (per-feature AUC per label target).")
    parser.add_argument("--evidence-v2-dir", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit-requests", type=int, default=None)
    args = parser.parse_args(argv)

    atlas = build_signal_atlas(args.evidence_v2_dir, args.labels, args.limit_requests)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "SIGNAL_ATLAS.json"
    out_path.write_text(json.dumps(atlas, indent=2))

    print(f"rows={atlas['counts']['rows']} requests={atlas['counts']['requests']} "
          f"blocked_hidden={atlas['counts']['blocked_hidden_rows']}")
    for target, out in atlas["targets"].items():
        print(f"[{target}] top features:")
        for key_name in out["ranking"][:8]:
            entry = out["features"][key_name]
            print(f"  {key_name:28s} AUC={entry['auc']:.4f}  pos={entry['n_pos']} "
                  f"neg={entry['n_neg']} blocked={entry['blocked']}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
