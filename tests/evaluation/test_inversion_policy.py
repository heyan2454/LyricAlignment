"""Tests for the inversion-policy brief (analytic fixtures; no real panels touched)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import inversion_policy as P


def test_policies_behave_as_documented_on_one_inverted_unit():
    s = np.array([5.0])
    e = np.array([2.0])                       # inverted by 3 s
    assert P.policy_clamp_zero(s, e) == (pytest.approx([5.0]), pytest.approx([5.0]))
    sw = P.policy_swap(s, e)
    assert (sw[0][0], sw[1][0]) == (2.0, 5.0)
    mid = P.policy_midpoint(s, e)
    assert mid[0][0] == pytest.approx(3.5) and mid[1][0] == pytest.approx(3.5)
    floor = P.policy_min_dur(s, e)
    assert floor[0][0] == pytest.approx(2.0)
    assert floor[1][0] == pytest.approx(2.0 + P.MIN_DUR_SEC)


def test_policies_leave_legal_intervals_alone():
    s = np.array([0.0, 2.0])
    e = np.array([0.8, 3.0])
    for fn in (P.policy_clamp_zero, P.policy_swap, P.policy_min_dur):
        ns, ne = fn(s, e)
        assert np.allclose(ns, s) and np.allclose(ne, e) or fn is P.policy_min_dur


def test_evaluate_policies_scores_only_inverted_units_and_reports_trigger_cost():
    frame = pd.DataFrame({
        "raw_start_sec": [0.0, 1.0, 5.0, 7.0],
        "raw_end_sec": [0.5, 1.5, 2.0, 8.0],          # unit 2 inverted
        "gt_start_sec": [0.0, 1.0, 3.0, 7.0],
        "gt_end_sec": [0.5, 1.5, 3.4, 8.0],
    })
    res = P.evaluate_policies(frame)
    assert res["units"] == 4 and res["inverted_units"] == 1
    assert res["policies"]["P1_swap_endpoints"]["inverted_units_only"]["n"] == 1
    # swap puts it at (2.0,5.0) -> end err 1.6 s; clamp puts (5,5) -> end err 1.6 s; both miss
    assert res["policies"]["P0_shipped_clamp_to_zero"]["inverted_units_only"]["zero_length_share"] == 1.0
    assert res["policies"]["P1_swap_endpoints"]["inverted_units_only"]["zero_length_share"] == 0.0
    assert res["policies"]["P1_swap_endpoints"]["trigger"]["flagged_units"] == 1
    assert res["policies"]["P1_swap_endpoints"]["all_units"]["n"] == 4


def test_decision_summary_ranks_and_gives_gain():
    # GT for the inverted unit is the swapped interval itself: swap lands exactly,
    # while clamping to (5,5) misses the start by 3 s
    frame = pd.DataFrame({
        "raw_start_sec": [0.0, 5.0], "raw_end_sec": [0.5, 2.0],
        "gt_start_sec": [0.0, 2.0], "gt_end_sec": [0.5, 5.0]})
    res = P.evaluate_policies(frame)
    d = P.decision_summary(res)
    assert d["available"] is True
    assert d["best_policy"] == "P1_swap_endpoints"
    assert d["gain_vs_shipped_pp"] > 0.0
    assert d["ranking"][0]["hit_at_tol"] >= d["ranking"][-1]["hit_at_tol"]


def test_evaluate_policies_rebases_filtered_frames():
    frame = pd.DataFrame({"raw_start_sec": [0.0, 5.0, 1.0],
                          "raw_end_sec": [0.5, 2.0, 1.5],
                          "gt_start_sec": [0.0, 4.9, 1.0],
                          "gt_end_sec": [0.5, 5.1, 1.5],
                          "item": ["a", "a", "b"]})
    sub = frame[frame["item"] == "a"]                    # non-zero-based index
    res = P.evaluate_policies(sub, seq_col="item")       # must not raise IndexError
    assert res["inverted_units"] == 1


def test_structural_consequence_flags_swap_as_worse(tmp_path: Path):
    """A swapped long interval swallows its neighbours: the measurement must see the trade-off.

    The fixture mirrors what the shipped pipeline produces: an ordered timeline where the inverted
    unit (raw 9.0 -> 1.0) was clamped to a zero-length interval at its own start.
    """
    from lyricalign.analysis import inversion_policy as IP

    rows = [{"song": "s", "unit_index": 0, "start_sec": 0.0, "end_sec": 0.5,
             "raw_s": 0.0, "raw_e": 0.5},
            {"song": "s", "unit_index": 1, "start_sec": 1.0, "end_sec": 1.0,        # clamped
             "raw_s": 9.0, "raw_e": 1.0},                                           # inverted
            {"song": "s", "unit_index": 2, "start_sec": 2.0, "end_sec": 2.5, "raw_s": 2.0, "raw_e": 2.5},
            {"song": "s", "unit_index": 3, "start_sec": 3.0, "end_sec": 3.5, "raw_s": 3.0, "raw_e": 3.5},
            {"song": "s", "unit_index": 4, "start_sec": 9.5, "end_sec": 10.0, "raw_s": 9.5, "raw_e": 10.0}]
    frame = pd.DataFrame(rows)
    frame["audio_duration_sec"] = 20.0
    res = IP.structural_consequence(frame)
    assert res["inverted_units"] == 1
    assert res["policies"]["P0_shipped"]["degenerate_share"] > 0.0
    assert res["policies"]["P0_shipped"]["overlap_share"] == 0.0
    # swapping clears the zero-length unit but its 8 s interval now covers units 2 and 3
    assert res["policies"]["P1_swap"]["degenerate_share"] == 0.0
    assert res["policies"]["P1_swap"]["overlap_share"] > 0.0, res["policies"]["P1_swap"]
    solve = res["policies"]["P1_swap_then_joint_solve"]
    assert solve["illegal_share"] <= 0.05, solve
    assert solve["degenerate_share"] == 0.0 and solve["overlap_share"] == 0.0
