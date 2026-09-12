"""Tests for the measurement-validity helpers (clamp detection and contamination bounds)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from lyricalign.analysis import measurement_validity as V


def _frame() -> pd.DataFrame:
    """5 units: 3 clean-and-correct, 1 inverted upstream (clamped to zero downstream, wrong),
    1 zero upstream that stays zero and is wrong against a real GT span."""
    return pd.DataFrame({
        "raw_start_sec": [0.0, 1.0, 5.0, 2.0, 3.0],
        "raw_end_sec":   [0.5, 1.5, 4.0, 2.0, 3.5],      # u2 inverted, u3 zero
        "pred_start_sec":[0.0, 1.0, 5.0, 2.0, 3.0],
        "pred_end_sec":  [0.5, 1.5, 5.0, 2.0, 3.5],      # clamp: u2 becomes (5.0,5.0)
        "gt_start_sec":  [0.0, 1.0, 4.9, 2.0, 3.0],
        "gt_end_sec":    [0.5, 1.5, 5.4, 2.6, 3.5],
    })


def test_stage_shape_counts_negative_and_zero():
    f = _frame()
    up = V.stage_shape(f, "raw_start_sec", "raw_end_sec")
    down = V.stage_shape(f, "pred_start_sec", "pred_end_sec")
    assert up["negative_units"] == 1 and up["zero_units"] == 1
    assert down["negative_units"] == 0 and down["zero_units"] == 2   # inversion became zero-length


def test_clamp_signature_detects_silent_conversion():
    sig = V.clamp_signature(_frame(), ("raw_start_sec", "raw_end_sec"),
                            ("pred_start_sec", "pred_end_sec"))
    assert sig["available"] is True
    assert sig["clamp_present"] is True
    assert sig["extra_zero_downstream_units"] == 1


def test_clamp_signature_absent_when_negatives_survive():
    f = _frame()
    f["pred_end_sec"] = [0.5, 1.5, 4.0, 2.0, 3.5]     # downstream keeps the u2 inversion
    sig = V.clamp_signature(f, ("raw_start_sec", "raw_end_sec"),
                            ("pred_start_sec", "pred_end_sec"))
    assert sig["clamp_present"] is False


def test_metric_impact_bounds_the_contamination():
    out = V.metric_impact(_frame(), pred_start="pred_start_sec", pred_end="pred_end_sec",
                          gt_start="gt_start_sec", gt_end="gt_end_sec", tol_sec=0.25)
    assert out["available"] is True and out["n"] == 5
    assert out["degenerate_units"] == 2 and out["degenerate_share"] == 0.4
    # 3 of the clean units hit, both degenerate ones miss -> 0.6 reported
    assert out["hit_at_tol"] == 0.6
    # ...and the metric is perfect once degenerate units are excluded: the whole 40pp gap is the
    # clamp/degeneracy, not boundary accuracy
    assert out["hit_at_tol_excluding_degenerate"] == 1.0
    assert out["contamination_bound_pp"] == 40.0
    # `inverted_*` is measured on the shipped stage: after a clamp nothing is inverted there, which
    # is exactly why the raw stage has to be inspected separately (clamp_signature above)
    assert "inverted_units" not in out
    no_clamp = V.metric_impact(f := _frame().assign(pred_end_sec=[0.5, 1.5, 4.0, 2.0, 3.5]),
                               pred_start="pred_start_sec", pred_end="pred_end_sec",
                               gt_start="gt_start_sec", gt_end="gt_end_sec", tol_sec=0.25)
    assert no_clamp["inverted_units"] == 1 and no_clamp["inverted_hit_at_tol"] == 0.0


def test_missing_columns_report_unavailable():
    f = _frame().drop(columns=["gt_end_sec"])
    assert V.stage_shape(f, "nope_start_sec", "nope_end_sec")["available"] is False
    assert V.metric_impact(f, pred_start="pred_start_sec", pred_end="pred_end_sec",
                           gt_start="gt_start_sec", gt_end="gt_end_sec")["available"] is False
