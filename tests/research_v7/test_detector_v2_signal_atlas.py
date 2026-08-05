"""Tests for scripts/research_v7/analyze_detector_v2_signal_atlas.py.

Covers: AUC ranking on a synthetic strong-signal fixture, blocked hidden (H)
handling, dual raw/official target separation, and grey/ambiguous/gt_unavailable
label exclusion.
"""
import importlib.util
import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "research_v7" / "analyze_detector_v2_signal_atlas.py"

_spec = importlib.util.spec_from_file_location("analyze_detector_v2_signal_atlas", SCRIPT_PATH)
atlas_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(atlas_mod)

N_REQUESTS = 20
N_UNITS = 10


def make_row(rid, cid, view, start_entropy, end_entropy, ro_start_shift, ro_end_shift, hidden_available):
    if hidden_available:
        hidden = {"available": True, "schema": "h", "start": {"v": 0.5}, "end": {"v": 0.9}}
    else:
        hidden = {"available": False, "schema": None, "start": {}, "end": {}}
    return {
        "request_identity": rid,
        "view_id": view,
        "canonical_unit_id": cid,
        "raw": {
            "start_sec": 0.0,
            "end_sec": 1.0,
            "start_entropy": start_entropy,
            "end_entropy": end_entropy,
            "start_margin": 0.4,
            "end_margin": 0.4,
            "topk": [[[0, 0.8], [1, 0.2]]],
        },
        "official": {
            "start_sec": 0.0 + ro_start_shift,
            "end_sec": 1.0 + ro_end_shift,
            "repair_start_shift_sec": 0.0,
            "repair_end_shift_sec": 0.0,
        },
        "hidden": hidden,
        "cross_view": {},
    }


def build_fixture(tmp_path, seed=7):
    rng = random.Random(seed)
    evidence_dir = tmp_path / "evidence_v2"
    evidence_dir.mkdir()
    labels = []
    for ri in range(N_REQUESTS):
        rid = f"req-{ri:03d}"
        rows = []
        for ci in range(N_UNITS):
            cid = ri * N_UNITS + ci
            raw_label = "unsafe" if ci % 2 == 1 else "safe"
            off_label = "unsafe" if (ri + ci) % 3 == 0 else "safe"
            excluded = {7: "grey", 8: "ambiguous", 9: "gt_unavailable"}
            raw_final = excluded.get(ci, raw_label)
            off_final = excluded.get(ci, off_label)
            end_entropy = (
                3.6 + rng.uniform(-0.2, 0.2) if raw_label == "unsafe" else 1.1 + rng.uniform(-0.2, 0.2)
            )
            start_entropy = 2.0 + rng.uniform(-0.2, 0.2)
            if off_label == "unsafe":
                ro_start_shift = 0.7 + rng.uniform(-0.1, 0.1)
                ro_end_shift = 1.4 + rng.uniform(-0.1, 0.1)
            else:
                ro_start_shift = -0.6 + rng.uniform(-0.1, 0.1)
                ro_end_shift = 0.1 + rng.uniform(-0.1, 0.1)
            rows.append(
                make_row(rid, cid, "full", start_entropy, end_entropy, ro_start_shift, ro_end_shift, ri % 4 != 0)
            )
            labels.append(
                {"request_identity": rid, "view_id": "full", "canonical_unit_id": cid,
                 "target": "raw", "label": raw_final}
            )
            labels.append(
                {"request_identity": rid, "view_id": "full", "canonical_unit_id": cid,
                 "target": "official", "label": off_final}
            )
        (evidence_dir / f"sha256:{rid}.jsonl").write_text(json.dumps(rows))
    (tmp_path / "LABELS.jsonl").write_text("\n".join(json.dumps(r) for r in labels))
    return evidence_dir, tmp_path / "LABELS.jsonl"


@pytest.fixture()
def atlas(tmp_path):
    evidence_dir, labels_path = build_fixture(tmp_path)
    return atlas_mod.build_signal_atlas(evidence_dir, labels_path)


def test_raw_target_top_feature_and_ranking(atlas):
    raw = atlas["targets"]["raw"]
    assert raw["top"] == "raw_end_entropy"
    assert raw["ranking"][0] == "raw_end_entropy"
    entry = raw["features"]["raw_end_entropy"]
    assert entry["auc"] > 0.9
    assert entry["n_pos"] == 60
    assert entry["n_neg"] == 80
    assert raw["labeled_units"] == 140
    noise = raw["features"]["raw_start_entropy"]
    assert noise["auc"] is None or noise["auc"] < raw["features"]["raw_end_entropy"]["auc"]


def test_dual_target_separation(atlas):
    raw = atlas["targets"]["raw"]
    official = atlas["targets"]["official"]
    assert raw["top"] == "raw_end_entropy"
    assert official["top"] in {"ro_end_shift_sec", "ro_start_shift_sec"}
    shift = official["features"]["ro_end_shift_sec"]
    assert shift["auc"] > 0.9
    # official unsafe = ci 满足 (ri+ci)%3==0 且 ci∉{7,8,9} → 每请求 4 个中 3 个计入 → 47
    assert shift["n_pos"] == 47
    assert shift["n_neg"] == 93
    assert official["labeled_units"] == 140
    assert official["features"]["raw_end_entropy"]["auc"] < 0.75


def test_excluded_labels(atlas):
    counts = atlas["counts"]
    assert counts["rows"] == N_REQUESTS * N_UNITS
    assert counts["excluded_by_label"] == {"grey": 40, "ambiguous": 40, "gt_unavailable": 40}
    for target in ("raw", "official"):
        entry = atlas["targets"][target]["features"]["raw_end_entropy"]
        assert entry["n_pos"] + entry["n_neg"] == 140


def test_blocked_hidden(atlas):
    counts = atlas["counts"]
    assert counts["blocked_hidden_rows"] == 50
    raw = atlas["targets"]["raw"]["features"]
    for key in atlas_mod.H_FEATURE_KEYS:
        entry = raw[key]
        assert entry["blocked"] == 35
        assert entry["n_pos"] + entry["n_neg"] == 105
    assert raw["hidden_start_norm"]["auc"] is not None
    assert raw["hidden_end_norm"]["auc"] is not None
