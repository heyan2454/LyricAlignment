"""Tests for the GTSinger multi-view selection machinery (synthetic panels)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import gtsinger_multiview as M


def _panel() -> pd.DataFrame:
    """4 units x 12 views; r2 views are near-identical (the observed degeneracy), r0 is bad.

    Units: every unit's GT boundary is t..t+0.4; r2 predicts exactly, r1 with a small shift,
    r0 with a large shift, so a consensus over all views must be *worse* than r2 alone.
    """
    # shifts are > tolerance for r1/r0 so that averaging the weaker views demonstrably drags the
    # consensus below the best single view (the round-10 finding); jitter depends only on the unit,
    # never on audio/mode, which is what the observed factor degeneracy looks like.
    rows = []
    for unit in range(4):
        gt_s = unit * 1.0
        for model, shift in (("r2", 0.0), ("r1", 0.14), ("r0", 0.50)):
            for audio in ("mix", "vocal"):
                for mode in ("full", "windowed"):
                    jitter = 0.0 if model == "r2" else 0.02 * unit
                    rows.append({"pipeline": "official", "item": "it1", "unit_index": unit,
                                 "model": model, "audio_input": audio, "mode": mode,
                                 "gt_start_sec": gt_s, "gt_end_sec": gt_s + 0.4,
                                 "pred_start_sec": gt_s + shift + jitter,
                                 "pred_end_sec": gt_s + 0.4 + shift + jitter,
                                 "raw_entropy_start": 0.2 if model == "r2" else 4.0,
                                 "raw_entropy_end": 0.2 if model == "r2" else 4.0})
    return pd.DataFrame(rows)


def test_build_view_frame_and_view_quality():
    d = M.build_view_frame(_panel(), pipeline="official")
    assert len(d) == 4 * 12
    q = M.view_quality(d)
    assert q["units"] == 4 and len(q["views"]) == 12
    prod = q["views"]["r2|vocal|windowed"]
    assert prod["hit100"] == 1.0 and prod["is_production_view"]
    # degeneracy: all four r2 cells are equally good
    assert {v["hit100"] for k, v in q["views"].items() if k.startswith("r2|")} == {1.0}
    assert q["views"]["r0|mix|full"]["hit100"] == 0.0
    fac = q["factor_decomposition"]["audio_input (other factors held fixed)"]
    assert fac["start_diff_median_sec"] == 0.0            # identical outputs -> zero spread
    assert fac["matched_cells"] > 0
    assert q["factor_decomposition"]["model (other factors held fixed)"]["start_diff_median_sec"] > 0.1
    assert q["cross_view_disagreement"]["share_gt_100ms"] > 0.0


def test_consensus_loses_to_the_best_view_when_views_are_unequal():
    """The negative result of round 10 must be reproducible on a fixture."""
    d = M.build_view_frame(_panel(), pipeline="official")
    res, rows, cons = M.selection_experiment(d)
    prod = res["per_view_baseline"]["production_view"]
    gc = res["gap_closed"]
    assert prod["name"] == "r2|vocal|windowed"
    assert prod["hit100"] == 1.0
    cons = gc["R1_consensus_median_boundaries"]
    assert cons["delta_pp_vs_production"] < 0.0, "consensus must lose when views are unequal"
    # no label-free selector beats the best single view in this regime (ties allowed)
    for k, v in gc.items():
        assert v["delta_pp_vs_production"] <= 0.0, k
    assert res["oracle_gap_pp"] == 0.0                    # r0/r1 never beat r2 here
    assert len(rows) == len(d)


def test_selector_picks_exist_and_output_shapes():
    d = M.build_view_frame(_panel(), pipeline="official")
    res, rows, cons = M.selection_experiment(d)
    assert {"view", "both_err", "support_100ms", "dev_consensus", "ent_max_view"} <= set(rows.columns)
    assert len(cons) == 4
    assert set(["c_s", "c_e", "gt_s", "gt_e", "err_best_view", "err_worst_view"]) <= set(cons.columns)
    # worst view per unit must be no better than the best
    assert (cons["err_worst_view"] >= cons["err_best_view"] - 1e-9).all()
    assert set(res["results"]) >= {"R0_mean_of_views", "R1_consensus_median_boundaries",
                                   "U_oracle_best_view", "U_worst_view"}
