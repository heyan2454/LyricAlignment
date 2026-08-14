"""Tests for E1 multi-realign dynamics (07 plan WP3)."""
from __future__ import annotations

from lyricalign.unit_realign.multi_iteration import (
    build_chain,
    extract_trajectory,
    make_smoke_executor,
    rows_to_units,
    validate_rows,
)


def _region(ids=(0, 1, 2, 3, 4)):
    return {
        "song_id": "s", "region_id": "r0",
        "units": [
            {"canonical_unit_id": i, "text": str(i), "start_sec": i * 0.5, "end_sec": i * 0.5 + 0.4}
            for i in ids
        ],
    }


def _identity_context():
    return {
        "audio_path": "a",
        "audio_sha256": "a" * 64, "model_identity": "m", "checkpoint_identity": "c",
        "decoder_identity": "d", "code_identity": "g", "text_adapter_identity": "t",
        "mapping_schema": "unit_realign_local_v2",
    }


def test_chain_constructs_all_iterations_with_chained_identity():
    region = _region()
    steps = build_chain(region, target_unit_ids=[1], iterations=(1, 2, 3, 5),
                        identity_context=_identity_context(), executor=make_smoke_executor())
    # build_chain emits iter0 (baseline) plus one step per requested iteration.
    iters = {s["iteration"]: s for s in steps}
    assert sorted(iters) == [0, 1, 2, 3, 5]
    assert all(s["constructible"] for s in steps)
    # iter0 has no parent; later steps carry a parent_request_identity.
    assert iters[0]["parent_request_identity"] is None
    for it in (1, 2, 3, 5):
        assert iters[it]["parent_request_identity"] is not None


def test_chain_baseline_inherits_chained_candidate():
    region = _region()
    steps = build_chain(region, target_unit_ids=[1], iterations=(1, 2),
                        identity_context=_identity_context(), executor=make_smoke_executor())
    iters = {s["iteration"]: s for s in steps}
    s0 = iters[1]  # first real iteration (after iter0 baseline)
    s1 = iters[2]
    s0_rows = {r["canonical_unit_id"]: (r["start_sec"], r["end_sec"]) for r in s0["candidate_rows"]}
    s1_baseline = {r["canonical_unit_id"]: (r["start_sec"], r["end_sec"]) for r in s1["baseline_rows"]}
    # iter2 baseline should reflect iter1 candidate (same canonical ids, times carried).
    assert set(s0_rows) == set(s1_baseline)


def test_validate_rows_rejects_non_monotonic_and_negative():
    ok = [{"canonical_unit_id": 0, "start_sec": 0.0, "end_sec": 0.4},
          {"canonical_unit_id": 1, "start_sec": 0.5, "end_sec": 0.9}]
    assert validate_rows(ok) is None
    bad_overlap = [{"canonical_unit_id": 0, "start_sec": 0.3, "end_sec": 0.6},
                   {"canonical_unit_id": 1, "start_sec": 0.0, "end_sec": 0.4}]
    assert validate_rows(bad_overlap) is not None
    bad_neg = [{"canonical_unit_id": 0, "start_sec": 0.0, "end_sec": 0.3},
               {"canonical_unit_id": 1, "start_sec": 0.3, "end_sec": -0.1}]
    assert validate_rows(bad_neg) is not None


def test_chain_not_constructible_on_bad_baseline_source():
    region = _region()
    # Without an executor, iter0 is constructed but cannot run -> not_constructible,
    # and the chain stops there (never silently rotating / no dead-baseline forward).
    steps = build_chain(region, target_unit_ids=[1], iterations=(1, 2),
                        identity_context=_identity_context(), executor=None)
    assert steps and steps[0]["iteration"] == 0
    assert any(s["constructible"] is False for s in steps)


def test_extract_trajectory_has_region_and_unit_rows():
    region = _region()
    steps = build_chain(region, target_unit_ids=[1], iterations=(1, 2, 3, 5),
                        identity_context=_identity_context(), executor=make_smoke_executor())
    rows = extract_trajectory(steps, region)
    kinds = {}
    for r in rows:
        kinds[r["row_kind"]] = kinds.get(r["row_kind"], 0) + 1
    assert kinds.get("region") == 1
    assert kinds.get("unit", 0) >= 1
    # target vs fixed-context displacement stay separated at the region level.
    reg = next(r for r in rows if r["row_kind"] == "region")
    assert "target_displacement_ms" in reg and "fixed_context_displacement_ms" in reg
    # P0-1 fix + schema completeness: per-unit carries first-hit buckets and the
    # region aggregate carries collateral_harm / catastrophic_regression.
    unit = next(r for r in rows if r["row_kind"] == "unit")
    assert "first_hit_ms_iteration_100" in unit
    assert "oscillation_or_divergence" in unit
    assert "collateral_harm" in reg and "catastrophic_regression" in reg


def test_classify_unit_dynamics_p0_signed_oscillation():
    """O-review P0-1: pure improvement must not be oscillation; true osc must be."""
    from lyricalign.unit_realign.multi_iteration import classify_unit_dynamics
    # Pure monotonic improvement in |err| -> NOT oscillation.
    imp = classify_unit_dynamics([500.0, 300.0, 100.0], [0, 0, 0])
    assert imp["oscillation_or_divergence"] is False
    assert imp["monotonic_improvement_ratio"] == 1.0
    # True oscillation (signed) -> IS oscillation.
    osc = classify_unit_dynamics([500.0, 100.0, 500.0], [0, 0, 0])
    assert osc["oscillation_or_divergence"] is True
    # Monotonic divergence -> oscillation_or_divergence True (strict divergence).
    div = classify_unit_dynamics([100.0, 300.0, 500.0], [0, 0, 0])
    assert div["oscillation_or_divergence"] is True
    # Fixed point when candidate stops moving (near-zero deltas).
    fp = classify_unit_dynamics([500.0, 500.0], [0.0, 0.0])
    assert fp["fixed_point_iteration"] is True

