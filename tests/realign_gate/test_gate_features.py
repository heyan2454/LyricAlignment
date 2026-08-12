"""Tests for realign_gate.gate_features (03_gate pure functions).

Lightweight fixtures only; no models/GPU/real files. Fixtures are materialized
through tmp_path to keep them serializable/pure.
"""

from __future__ import annotations

import json

import pytest

from lyricalign.realign_gate.gate_features import (
    NEUTRAL_EPS_MS,
    analyze,
    extract_no_gt_features,
    pair_gt,
)
from lyricalign.research_v7.detector_v2_evidence import (
    FORBIDDEN_FEATURE_FIELDS,
    assert_no_label_leak,
)


@pytest.fixture
def real_gt(tmp_path):
    data = {
        f"song{i}": {
            cid: {"start_sec": float(cid), "end_sec": float(cid) + 0.5, "text": f"c{cid}"}
            for cid in (2 * i - 1, 2 * i)
        }
        for i in range(1, 7)
    }
    (tmp_path / "real_gt.json").write_text(json.dumps(data), encoding="utf-8")
    return json.loads((tmp_path / "real_gt.json").read_text(encoding="utf-8"))


def _new_row(case, song, cid, new_start, new_end, *, variant="R-A"):
    return {
        "case_id": case,
        "variant": variant,
        "canonical_unit_id": cid,
        "song_id": song,
        "start_sec": new_start,
        "end_sec": new_end,
    }


def _old_row(case, cid, old_start, old_end, *, variant="R-A"):
    return {
        "case_id": case,
        "variant": variant,
        "canonical_unit_id": cid,
        "start_sec": old_start,
        "end_sec": old_end,
    }


@pytest.fixture
def new_rows():
    rows = []
    # harm: new far, old near -> positive delta (6 songs, one each)
    for i in range(1, 7):
        cid = 2 * i - 1
        rows.append(_new_row(f"c_harm{i - 1}", f"song{i}", cid, cid + 1.3, cid + 1.8))
    # improve: new near, old far -> negative delta
    for i in range(1, 7):
        cid = 2 * i
        rows.append(_new_row(f"c_imp{i - 1}", f"song{i}", cid, cid + 0.02, cid + 0.52))
    # neutral: |delta| < 10ms
    rows.append(_new_row("c_neu0", "song1", 2, 3.095, 3.595))
    # boundaries: b100 (50ms), b200 (150ms), b500 (300ms); GT = [cid, cid+0.5]
    rows.append(_new_row("c_b100", "song3", 5, 5.05, 5.55))
    rows.append(_new_row("c_b200", "song4", 7, 7.15, 7.65))
    rows.append(_new_row("c_b500", "song5", 9, 9.3, 9.8))
    # time-IoU fallback: cid absent, overlaps song1 unit2 [1.0, 1.5]
    rows.append(_new_row("c_iou0", "song1", 999, 0.98, 1.48))
    # unmatchable: cid absent, no overlap in song1
    rows.append(_new_row("c_null0", "song1", 998, 10.0, 10.5))
    # miss: harmful but gate signal absent (n_big=0)
    rows.append(_new_row("c_miss0", "song6", 12, 12.3, 12.8))
    return rows


@pytest.fixture
def old_rows():
    rows = []
    for i in range(1, 7):
        cid = 2 * i - 1
        rows.append(_old_row(f"c_harm{i - 1}", cid, cid + 1.05, cid + 1.55))
    for i in range(1, 7):
        cid = 2 * i
        rows.append(_old_row(f"c_imp{i - 1}", cid, cid - 1.0, cid - 0.5))
    rows.append(_old_row("c_neu0", 2, 3.1, 3.6))
    rows.append(_old_row("c_b100", 5, 5.05, 5.55))
    rows.append(_old_row("c_b200", 7, 7.15, 7.65))
    rows.append(_old_row("c_b500", 9, 9.3, 9.8))
    rows.append(_old_row("c_iou0", 999, 1.02, 1.52))
    rows.append(_old_row("c_miss0", 12, 12.05, 12.55))
    return rows


@pytest.fixture
def gt_rows(new_rows, old_rows, real_gt):
    out = []
    for song in sorted(real_gt):
        rows = [r for r in new_rows if r["song_id"] == song]
        out.extend(pair_gt(rows, real_gt, song_id=song, old_rows=old_rows))
    return out


def _ev_row(case, song, cid, new_start, new_end, old_start, old_end, p_after):
    return {
        "request_identity": f"req_{case}",
        "case_id": case,
        "variant": "R-A",
        "canonical_unit_id": cid,
        "song_id": song,
        "start_sec": new_start,
        "end_sec": new_end,
        "old_start_sec": old_start,
        "old_end_sec": old_end,
        "p_bad_before": 0.1,
        "p_bad_after": p_after,
        "entropy_before": 1.0,
        "entropy_after": 2.0,
        "margin_before": 1.0,
        "margin_after": 0.2,
        "text": f"c{cid}",
        "old_text": f"c{cid}",
        "in_request": True,
        "inversion": False,
    }


@pytest.fixture
def ev_rows(new_rows, old_rows):
    rows = []
    for i in range(1, 7):
        cid = 2 * i - 1
        nr = _new_row(f"c_harm{i - 1}", f"song{i}", cid, cid + 1.3, cid + 1.8)
        o = _old_row(f"c_harm{i - 1}", cid, cid + 1.05, cid + 1.55)
        rows.append(_ev_row(nr["case_id"], nr["song_id"], cid, nr["start_sec"], nr["end_sec"],
                            o["start_sec"], o["end_sec"], 0.9))
    for i in range(1, 7):
        cid = 2 * i
        nr = _new_row(f"c_imp{i - 1}", f"song{i}", cid, cid + 0.02, cid + 0.52)
        o = _old_row(f"c_imp{i - 1}", cid, cid - 1.0, cid - 0.5)
        rows.append(_ev_row(nr["case_id"], nr["song_id"], cid, nr["start_sec"], nr["end_sec"],
                            o["start_sec"], o["end_sec"], 0.05))
    for case, song, cid, ns, ne, os_, oe, pa in [
        ("c_neu0", "song1", 2, 3.095, 3.595, 3.1, 3.6, 0.1),
        ("c_b100", "song3", 5, 5.05, 5.55, 5.05, 5.55, 0.1),
        ("c_b200", "song4", 7, 7.15, 7.65, 7.15, 7.65, 0.1),
        ("c_b500", "song5", 9, 9.3, 9.8, 9.3, 9.8, 0.1),
        ("c_iou0", "song1", 999, 0.98, 1.48, 1.02, 1.52, 0.1),
        ("c_miss0", "song6", 12, 12.3, 12.8, 12.05, 12.55, 0.05),
    ]:
        rows.append(_ev_row(case, song, cid, ns, ne, os_, oe, pa))
    return rows


@pytest.fixture
def old_shadow():
    return {"units": {}, "unsafe_intervals": []}


@pytest.fixture
def no_gt_rows(ev_rows, old_shadow):
    return extract_no_gt_features(ev_rows, old_shadow)


@pytest.fixture
def paired_by_case(gt_rows):
    return {r["case_id"]: r for r in gt_rows}


# ---------- GT pairing ----------


def test_canonical_pairing_priority(paired_by_case):
    row = paired_by_case["c_harm0"]
    assert row["pairing"] == "canonical"
    assert row["canonical_unit_id"] == 1


def test_non_canonical_is_extra_prediction(paired_by_case):
    row = paired_by_case["c_iou0"]
    assert row["pairing"] is None
    assert row["extra_prediction"] is True
    assert row["label"] is None


def test_unmatchable_is_null(paired_by_case):
    row = paired_by_case["c_null0"]
    assert row["pairing"] is None
    assert row["extra_prediction"] is True
    assert row["old_error_ms"] is None
    assert row["new_error_ms"] is None
    assert row["delta_error_ms"] is None
    assert row["label"] is None


def test_target_missing_recorded_as_new_missing(real_gt, old_rows):
    rows = [_new_row("c1", "song1", 1, 0.0, 0.5)]
    paired = pair_gt(rows, real_gt, song_id="song1", old_rows=old_rows, target_cids=[1, 2])
    by_cid = {r["canonical_unit_id"]: r for r in paired}
    assert by_cid[1]["pairing"] == "canonical"
    assert by_cid[1]["new_missing"] is False
    assert by_cid[2]["pairing"] == "canonical"
    assert by_cid[2]["new_missing"] is True
    assert by_cid[2]["new_error_ms"] is None


# ---------- delta / label / boundaries ----------


def test_delta_label_improve_harm_neutral(paired_by_case):
    imp = paired_by_case["c_imp0"]
    assert imp["delta_error_ms"] < 0
    assert imp["label"] == "improve"

    harm = paired_by_case["c_harm0"]
    assert harm["delta_error_ms"] > 0
    assert harm["label"] == "harm"

    neu = paired_by_case["c_neu0"]
    assert abs(neu["delta_error_ms"]) < NEUTRAL_EPS_MS
    assert neu["label"] == "neutral"


def test_catastrophic_harm(paired_by_case):
    harm = paired_by_case["c_harm0"]
    assert harm["delta_error_ms"] > 200.0
    assert harm["catastrophic_harm"] is True


def test_boundaries_100_200_500(paired_by_case):
    b100 = paired_by_case["c_b100"]
    assert b100["new_error_ms"] <= 100.0
    assert b100["boundaries_100"] and b100["boundaries_200"] and b100["boundaries_500"]

    b200 = paired_by_case["c_b200"]
    assert 100.0 < b200["new_error_ms"] <= 200.0
    assert not b200["boundaries_100"]
    assert b200["boundaries_200"] and b200["boundaries_500"]

    b500 = paired_by_case["c_b500"]
    assert 200.0 < b500["new_error_ms"] <= 500.0
    assert not b500["boundaries_100"] and not b500["boundaries_200"]
    assert b500["boundaries_500"]


# ---------- no-GT features ----------


def test_no_gt_rows_pass_leak_check(no_gt_rows):
    assert no_gt_rows
    for row in no_gt_rows:
        assert row["feature_valid"] is True
        assert_no_label_leak(row)


def test_no_gt_rows_have_no_gt_keys(no_gt_rows):
    for row in no_gt_rows:
        assert not (set(row) & FORBIDDEN_FEATURE_FIELDS)


def test_no_gt_feature_values(no_gt_rows):
    by_case = {r["case_id"]: r for r in no_gt_rows}
    harm = by_case["c_harm0"]
    assert harm["n_big"] == 1
    assert harm["p_bad_delta"] == pytest.approx(0.8)
    assert harm["entropy_delta"] == pytest.approx(1.0)
    assert harm["margin_delta"] == pytest.approx(-0.8)
    assert harm["text_identity"] == 1
    assert harm["inversion"] == 0
    imp = by_case["c_imp0"]
    assert imp["n_big"] == 0


# ---------- analysis ----------


def test_song_split_disjoint_and_complete(gt_rows, no_gt_rows, tmp_path):
    res = analyze(gt_rows, no_gt_rows, out_dir=tmp_path)
    splits = res["splits"]
    n_unique_songs = len({r["song_id"] for r in gt_rows if r.get("song_id")})
    assert splits["n_dev_songs"] + splits["n_holdout_songs"] == n_unique_songs
    n_labeled = sum(1 for r in gt_rows if r["label"] is not None)
    assert splits["n_dev_rows"] + splits["n_holdout_rows"] == n_labeled


def test_auroc_computable(gt_rows, no_gt_rows):
    res = analyze(gt_rows, no_gt_rows)
    dev = res["metrics"]["dev"]
    assert dev["n"] > 0
    assert dev["auroc_delta"] is not None
    assert dev["auroc_delta"] > 0.5
    assert dev["auroc_nbig"] is not None


def test_analysis_outputs_written(gt_rows, no_gt_rows, tmp_path):
    analyze(gt_rows, no_gt_rows, out_dir=tmp_path)
    assert (tmp_path / "ANALYSIS.json").exists()
    assert (tmp_path / "COUNTEREXAMPLES.jsonl").exists()


def test_counterexamples_output(gt_rows, no_gt_rows, tmp_path):
    res = analyze(gt_rows, no_gt_rows, out_dir=tmp_path)
    assert res["n_counterexamples"] >= 1
    assert res["n_ambiguous"] >= 1
    lines = [json.loads(l) for l in (tmp_path / "COUNTEREXAMPLES.jsonl").read_text().splitlines() if l.strip()]
    assert any(c["reason"] == "counterexample" for c in lines)
    assert any(c["reason"] == "ambiguous" for c in lines)


def test_three_state_suggestion_in_range(gt_rows, no_gt_rows):
    res = analyze(gt_rows, no_gt_rows)
    assert res["suggestion"] in {
        "ACCEPT_WRITEBACK", "UNCERTAIN_KEEP_OR_RETRY", "REJECT_KEEP_ORIGINAL",
    }


def test_run_stage_canonical_wiring(tmp_path, monkeypatch):
    """Production wiring through run_stage: REQUESTS + CANDIDATE_INDEX + nested
    decoder_outputs.raw.rows evidence + CASES(old_units) + frozen scorer p_bad
    injection + real-GT pairing. Covers the two P1 review fixes: old_by_key
    (case_id, cid) matching and per-unit p_bad injection from score_units."""
    from lyricalign.realign_gate import gate_features, identity

    real_gt_data = {
        "s1": {0: {"start_sec": 0.0, "end_sec": 0.5},
               1: {"start_sec": 0.5, "end_sec": 1.0}},
    }

    def fake_score_units(scorer, rows):
        return {
            "units": [
                {"canonical_unit_id": 0, "start_sec": 0.1, "end_sec": 0.45,
                 "p_bad": 0.9, "state": "reject"},
                {"canonical_unit_id": 1, "start_sec": 0.55, "end_sec": 1.05,
                 "p_bad": 0.9, "state": "reject"},
            ],
            "n_units": 2,
            "decision": "reject",
        }

    monkeypatch.setattr(
        gate_features, "build_frozen_scorer_from_artifacts", lambda *a, **k: object())
    monkeypatch.setattr(gate_features, "score_units", fake_score_units)
    monkeypatch.setattr(
        gate_features, "load_real_gt_with_audit",
        lambda annotations, manifest: (real_gt_data, {}))

    run_root = tmp_path / "run"
    (run_root / "00_meta").mkdir(parents=True)
    (run_root / "02_behavior").mkdir(parents=True)
    (run_root / "00_meta" / "CONFIG.json").write_text(json.dumps({
        "inputs": {
            "frozen_op": {
                "T_accept": identity.RAW_T_ACCEPT,
                "T_reject": identity.RAW_T_REJECT,
                "model_id": "Qwen3-ForcedAligner-0.6B-hf",
                "checkpoint_id": "r2-step-000750",
            },
            "real_gt_annotations": str(tmp_path / "annotations.jsonl"),
            "cohort_manifests": [str(tmp_path / "manifest.json")],
        }
    }), encoding="utf-8")

    request_row = {
        "request_id": "s1:0",
        "source_song_id": "s1",
        "audio_path": "runs/song/s1/s1.wav",
        "audio_start_sec": 0.0,
        "audio_end_sec": 10.0,
        "text_units": ["a", "b"],
        "text_start_index": 0,
        "text_end_index": 2,
        "provenance": {"source_window_id": "s1:w0", "text_unit_start": 0, "text_unit_end": 2},
        "canonical_unit_ids": [0, 1],
    }
    (run_root / "02_behavior" / "REQUESTS.jsonl").write_text(
        json.dumps(request_row) + "\n", encoding="utf-8")

    ev_payload = {
        "content_identity": "sha256:abc",
        "attempt": {
            "request": {"request_id": "s1:0"},
            "decoder_outputs": {"raw": {"rows": [
                {"global_character_index": 0, "raw_global_start_sec": 0.1,
                 "raw_global_end_sec": 0.45},
                {"global_character_index": 1, "raw_global_start_sec": 0.55,
                 "raw_global_end_sec": 1.05},
            ]}},
        },
    }
    ev_path = tmp_path / "ev1.json"
    ev_path.write_text(json.dumps(ev_payload), encoding="utf-8")

    cand = {
        "case_id": "c1",
        "request_id": "s1:0",
        "variant": "R-A_unsafe_old_range",
        "evidence_path": str(ev_path),
    }
    (run_root / "02_behavior" / "CANDIDATE_INDEX.jsonl").write_text(
        json.dumps(cand) + "\n", encoding="utf-8")

    case = {
        "case_id": "c1",
        "song_id": "s1",
        "target_unit_ids": [0, 1],
        "detector_shadow": {"decision": "reject", "unsafe_intervals": [[0.0, 1.0]]},
        "old_units": [
            {"canonical_unit_id": 0, "start_sec": 0.2, "end_sec": 0.6,
             "p_bad": 0.3, "state": "accept"},
            {"canonical_unit_id": 1, "start_sec": 0.4, "end_sec": 0.8,
             "p_bad": 0.3, "state": "accept"},
        ],
    }
    (run_root / "02_behavior" / "CASES.jsonl").write_text(
        json.dumps(case) + "\n", encoding="utf-8")

    summary = gate_features.run_stage(run_root)

    assert summary["result_status"] == "ok"
    assert summary["n_candidate_rows"] == 2
    assert summary["n_paired"] == 2
    assert summary["n_no_gt"] == 2

    gt = [json.loads(l) for l in
          (run_root / "03_gate/GT_PAIR_METRICS.jsonl").read_text().splitlines() if l.strip()]
    by_cid = {r["canonical_unit_id"]: r for r in gt}
    assert by_cid[0]["pairing"] == "canonical"
    assert by_cid[0]["old_missing"] is False
    assert by_cid[0]["old_error_ms"] == pytest.approx(200.0)
    assert by_cid[0]["new_missing"] is False
    assert by_cid[0]["new_error_ms"] == pytest.approx(100.0)
    assert by_cid[0]["delta_error_ms"] == pytest.approx(-100.0)
    assert by_cid[0]["label"] == "improve"

    ng = [json.loads(l) for l in
          (run_root / "03_gate/NO_GT_FEATURES.jsonl").read_text().splitlines() if l.strip()]
    ng_by_cid = {r["canonical_unit_id"]: r for r in ng}
    assert ng_by_cid[0]["p_bad_before"] == pytest.approx(0.3)
    assert ng_by_cid[0]["p_bad_after"] == pytest.approx(0.9)
    assert ng_by_cid[0]["p_bad_delta"] == pytest.approx(0.6)
    assert ng_by_cid[0]["n_big"] == 2  # candidate-level: both units |delta|>0.05


# ---------- B6: analysis join key must include variant ----------


def test_analyze_variant_join_not_overwriting(tmp_path):
    """Same (case_id, cid) with R-A and R-B must both join and stay distinct."""
    gt_rows = [
        {"case_id": "c", "variant": "R-A", "canonical_unit_id": 5,
         "song_id": "s1", "label": "harm", "delta_error_ms": 100.0},
        {"case_id": "c", "variant": "R-B", "canonical_unit_id": 5,
         "song_id": "s1", "label": "improve", "delta_error_ms": -100.0},
    ]
    no_gt_rows = [
        {"case_id": "c", "variant": "R-A", "canonical_unit_id": 5,
         "feature_valid": True, "n_big": 0, "unsafe_inside_disp_ms": 10.0,
         "changed_ratio": 0.5},
        {"case_id": "c", "variant": "R-B", "canonical_unit_id": 5,
         "feature_valid": True, "n_big": 1, "unsafe_inside_disp_ms": 20.0,
         "changed_ratio": 0.5},
    ]
    res = analyze(gt_rows, no_gt_rows, out_dir=tmp_path)
    lines = [json.loads(l) for l in
             (tmp_path / "COUNTEREXAMPLES.jsonl").read_text().splitlines() if l.strip()]
    variants = {c["variant"] for c in lines}
    assert variants == {"R-A", "R-B"}
    harm_rows = [c for c in lines if c["variant"] == "R-A"]
    imp_rows = [c for c in lines if c["variant"] == "R-B"]
    assert any(c["label"] == "harm" and c["n_big"] == 0 for c in harm_rows)
    assert any(c["label"] == "improve" and c["n_big"] == 1 for c in imp_rows)
    total_rows = res["splits"]["n_dev_rows"] + res["splits"]["n_holdout_rows"]
    assert total_rows == 2


def test_analyze_reports_duplicate_keys(tmp_path):
    gt_rows = [
        {"case_id": "c", "variant": "R-A", "canonical_unit_id": 5,
         "song_id": "s1", "label": "harm", "delta_error_ms": 100.0},
        {"case_id": "c", "variant": "R-A", "canonical_unit_id": 5,
         "song_id": "s1", "label": "harm", "delta_error_ms": 120.0},
    ]
    no_gt_rows = [
        {"case_id": "c", "variant": "R-A", "canonical_unit_id": 5,
         "feature_valid": True, "n_big": 1, "unsafe_inside_disp_ms": 10.0,
         "changed_ratio": 0.5},
    ]
    res = analyze(gt_rows, no_gt_rows)
    assert res["duplicate_keys"]["gt_pair_metrics"] == 1


# ---------- B7: n_big is candidate-level |p_bad delta| count ----------


def _b7_row(case, cid, p_before, p_after, *, variant="R-A"):
    return {
        "request_identity": f"req_{case}",
        "case_id": case,
        "variant": variant,
        "canonical_unit_id": cid,
        "song_id": "s1",
        "start_sec": 1.0,
        "end_sec": 1.5,
        "old_start_sec": 1.0,
        "old_end_sec": 1.5,
        "p_bad_before": p_before,
        "p_bad_after": p_after,
        "text": f"c{cid}",
        "old_text": f"c{cid}",
        "in_request": True,
        "inversion": False,
    }


def test_nbig_ignores_absolute_risk_and_counts_delta():
    """High p_bad with delta=0 -> n_big 0; low p_bad with big delta -> n_big 1."""
    rows = [
        _b7_row("c_high_no_delta", 1, 0.9, 0.9),
        _b7_row("c_low_big_delta", 2, 0.1, 0.3),
    ]
    out = extract_no_gt_features(rows)
    by_case = {r["case_id"]: r for r in out}
    assert by_case["c_high_no_delta"]["p_bad_before"] == pytest.approx(0.9)
    assert by_case["c_high_no_delta"]["p_bad_after"] == pytest.approx(0.9)
    assert by_case["c_high_no_delta"]["abs_p_bad_delta"] == pytest.approx(0.0)
    assert by_case["c_high_no_delta"]["n_big"] == 0
    assert by_case["c_low_big_delta"]["abs_p_bad_delta"] == pytest.approx(0.2)
    assert by_case["c_low_big_delta"]["n_big"] == 1


def test_nbig_candidate_level_over_multiple_units():
    """Every feature row of a candidate carries the same candidate-level count."""
    rows = [
        _b7_row("c_multi", 1, 0.1, 0.9),
        _b7_row("c_multi", 2, 0.1, 0.9),
        _b7_row("c_multi", 3, 0.1, 0.15),  # |delta|=0.05 not > threshold
    ]
    out = extract_no_gt_features(rows)
    for rec in out:
        assert rec["n_big"] == 2


# ---------- B8: baseline shadow isolated per (song_id, case_id, cid) ----------


def test_shadow_isolated_by_song_and_case():
    """Same cid in different songs/cases must not pollute p_bad_before."""
    shadow = {
        "units": {
            ("s1", "c1", 3): {"start_sec": 1.0, "end_sec": 1.5, "p_bad": 0.1},
            ("s2", "c2", 3): {"start_sec": 5.0, "end_sec": 5.5, "p_bad": 0.9},
        },
        "unsafe_intervals": {
            ("s1", "c1"): [[0.0, 2.0]],
            ("s2", "c2"): [[4.0, 6.0]],
        },
    }
    rows = [
        {"request_identity": "r1", "case_id": "c1", "variant": "R-A",
         "canonical_unit_id": 3, "song_id": "s1",
         "start_sec": 1.2, "end_sec": 1.7, "p_bad_after": 0.9, "in_request": True},
        {"request_identity": "r2", "case_id": "c2", "variant": "R-A",
         "canonical_unit_id": 3, "song_id": "s2",
         "start_sec": 5.2, "end_sec": 5.7, "p_bad_after": 0.1, "in_request": True},
    ]
    out = extract_no_gt_features(rows, shadow)
    by_case = {r["case_id"]: r for r in out}
    assert by_case["c1"]["p_bad_before"] == pytest.approx(0.1)
    assert by_case["c1"]["p_bad_after"] == pytest.approx(0.9)
    assert by_case["c1"]["p_bad_delta"] == pytest.approx(0.8)
    assert by_case["c2"]["p_bad_before"] == pytest.approx(0.9)
    assert by_case["c2"]["p_bad_after"] == pytest.approx(0.1)
    assert by_case["c2"]["p_bad_delta"] == pytest.approx(-0.8)


def test_unsafe_intervals_isolated_by_song_case():
    """Unsafe intervals resolve per (song_id, case_id), not globally (B8)."""
    def run(song, case, intervals, new_start, new_end):
        shadow = {
            "units": {(song, case, 3): {"start_sec": 1.0, "end_sec": 1.5, "p_bad": 0.1}},
            "unsafe_intervals": {(song, case): intervals},
        }
        rows = [{
            "request_identity": f"r_{case}", "case_id": case, "variant": "R-A",
            "canonical_unit_id": 3, "song_id": song,
            "start_sec": new_start, "end_sec": new_end, "p_bad_after": 0.9,
            "in_request": True,
        }]
        return extract_no_gt_features(rows, shadow)[0]

    inside = run("s1", "c1", [[0.0, 2.0]], 1.2, 1.7)
    assert inside["unsafe_inside_disp_ms"] is not None
    outside = run("s2", "c2", [[10.0, 12.0]], 1.2, 1.7)
    assert outside["unsafe_inside_disp_ms"] is None


def test_shadow_resolves_non_string_keys():
    """B8 triple keys normalized: int song/case in rows still hit the shadow."""
    shadow = {
        "units": {(1, 1, 3): {"start_sec": 1.0, "end_sec": 1.5, "p_bad": 0.1}},
        "unsafe_intervals": {(1, 1): [[0.0, 2.0]]},
    }
    rows = [
        {"request_identity": "r1", "case_id": 1, "variant": "R-A",
         "canonical_unit_id": 3, "song_id": 1,
         "start_sec": 1.2, "end_sec": 1.7, "p_bad_after": 0.9, "in_request": True},
        {"request_identity": "r2", "case_id": 2, "variant": "R-A",
         "canonical_unit_id": 3, "song_id": 2,
         "start_sec": 1.2, "end_sec": 1.7, "p_bad_after": 0.9, "in_request": True},
    ]
    out = extract_no_gt_features(rows, shadow)
    by_case = {r["case_id"]: r for r in out}
    assert by_case[1]["p_bad_before"] == pytest.approx(0.1)
    assert by_case[2]["p_bad_before"] is None


def test_target_missing_recorded_per_variant():
    """R-A covers a target, R-B does not: R-B must still emit new_missing (B6)."""
    real_gt = {"song1": {1: {"start_sec": 0.0, "end_sec": 0.5, "text": "c1"},
                         2: {"start_sec": 1.0, "end_sec": 1.5, "text": "c2"}}}
    rows = [
        _new_row("c", "song1", 1, 0.0, 0.5, variant="R-A"),
        _new_row("c", "song1", 1, 0.0, 0.5, variant="R-B"),
    ]
    paired = pair_gt(rows, real_gt, song_id="song1", target_cids=[1, 2])
    keys = {(r["variant"], r["canonical_unit_id"]) for r in paired}
    assert {("R-A", 1), ("R-B", 1), ("R-A", 2), ("R-B", 2)} <= keys
    rb2 = next(r for r in paired if (r["variant"], r["canonical_unit_id"]) == ("R-B", 2))
    assert rb2["new_missing"] is True


def test_nbig_uncomputed_counted_explicitly():
    """Rows with unavailable p_bad_before counted as n_big_uncomputed, not silent."""
    rows = [
        _b7_row("c_ok", 1, 0.1, 0.9),
        _b7_row("c_missing", 2, None, 0.9),
    ]
    out = extract_no_gt_features(rows)
    by_case = {r["case_id"]: r for r in out}
    assert by_case["c_ok"]["n_big"] == 1
    assert by_case["c_ok"]["n_big_uncomputed"] is None
    assert by_case["c_missing"]["n_big"] is None
    assert by_case["c_missing"]["n_big_uncomputed"] == 1
