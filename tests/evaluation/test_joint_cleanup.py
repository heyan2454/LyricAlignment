"""Tests for the joint constrained cleanup solver (regression guards for two real bugs found)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import joint_cleanup as J


def test_feasible_target_is_reproduced_exactly():
    """If the raw sequence already satisfies every constraint, the solve must be a no-op.

    Regression guard: an early version charged cost to S/E themselves (not only to the deviation
    variables), which silently pulled the whole sequence towards t=0.
    """
    s = np.array([0.0, 1.0, 2.0, 3.0])
    e = np.array([0.8, 1.9, 2.7, 3.6])
    S, E, rep = J.solve_block(s, e, audio_dur=5.0, alpha=0.0)
    assert rep.status == "ok"
    assert np.allclose(S, s, atol=1e-6) and np.allclose(E, e, atol=1e-6)
    assert rep.cost == pytest.approx(0.0, abs=1e-6)
    assert rep.moved == 0.0


def test_constraints_are_enforced_on_pathological_input():
    """Negative durations, overshoots, overlaps and start regressions must all be repaired."""
    cases = {
        "regression+overlap": ([0.0, 1.0, 0.5, 3.0], [0.8, 2.5, 1.2, 3.6]),
        "negative_duration": ([0.0, 5.0], [0.9, 1.0]),
        "overshoot": ([0.0, 4.0], [30.0, 4.5]),
    }
    for name, (s, e) in cases.items():
        S, E, rep = J.solve_block(np.array(s), np.array(e), audio_dur=40.0, alpha=0.0)
        dur = E - S
        assert np.all(dur >= J.MIN_DUR_SEC - 1e-6), name
        assert np.all(dur <= J.MAX_DUR_SEC + 1e-6), name
        assert np.all(np.diff(S) >= -1e-6), name
        assert np.all(E[:-1] <= S[1:] + 1e-6), name
        st = J.structure_metrics(S, E, np.array(["a"] * len(s)))
        assert st["degenerate_share"] == 0.0, name
        assert st["overlap_share"] == 0.0, name
        assert st["start_regression_share"] == 0.0, name


def test_confidence_weight_protects_low_entropy_boundaries():
    """With a forced conflict the *unsure* boundaries must be the ones that move.

    Unit 0's end is confident (lowest entropy) while the later starts are unsure, so the solver
    should push the later starts forward instead of trimming the confident tail back.
    """
    s = np.array([0.0, 1.0, 2.0])
    e = np.array([2.5, 2.6, 3.2])              # unit 0 overlaps both later units
    ents_start = np.array([0.0, 9.0, 9.0])     # later starts: unsure
    ents_end = np.array([0.0, 9.0, 9.0])       # unit 0 end: confident
    S, E, _ = J.solve_block(s, e, ent_start=ents_start, ent_end=ents_end,
                            audio_dur=6.0, alpha=8.0)
    assert E[0] > 2.0, (S, E)                  # confident tail barely moves
    assert S[1] > 1.5, (S, E)                  # the unsure start absorbs the conflict instead
    # unweighted solve has no reason to protect the confident tail
    Su, Eu, _ = J.solve_block(s, e, audio_dur=6.0, alpha=0.0)
    assert Eu[0] <= Su[1] + 1e-6 and Eu[0] < E[0]


def test_weights_are_rank_based_and_bounded():
    ent = np.array([0.0, 1.0, 2.0, 3.0])
    w = J._weights(ent, alpha=4.0)
    assert w[0] > w[-1]                          # confident (low entropy) costs more
    assert w.max() <= 1.0 + 4.0 + 1e-9 and w.min() >= 1.0
    assert np.all(J._weights(np.full(5, np.nan), 4.0) == 1.0)
    assert np.all(J._weights(np.array([1.0, 2.0]), 4.0) == 1.0)   # too few to rank


def test_ground_truth_metrics_and_iou():
    S = np.array([0.0, 1.0]); E = np.array([1.0, 2.0])
    out = J.evaluate_against_ground_truth(S, E, S.copy(), E.copy())
    assert out["hit100"] == 1.0 and out["mean_iou"] == 1.0 and out["mae_both_sec"] == 0.0
    off = J.evaluate_against_ground_truth(S + 0.15, E + 0.15, S, E)
    assert off["hit100"] == 0.0 and off["hit250"] == 1.0
    # overlap 1 s over union 3 s
    assert J._iou(np.array([0.0]), np.array([2.0]), np.array([1.0]), np.array([3.0]))[0] == pytest.approx(1 / 3)


def test_empty_and_single_inputs():
    S, E, rep = J.solve_block(np.array([]), np.array([]))
    assert S.size == 0 and rep.status == "empty"
    S, E, rep = J.solve_block(np.array([1.0]), np.array([0.5]), audio_dur=9.0)   # negative
    assert E[0] - S[0] >= J.MIN_DUR_SEC - 1e-6
    assert rep.status == "ok"
