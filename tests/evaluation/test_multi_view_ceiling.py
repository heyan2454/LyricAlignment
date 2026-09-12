"""Tests for the multi-decode headroom statistics (tiny hand-computable cases)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import multi_view_ceiling as M


def _long() -> pd.DataFrame:
    # unit A: v1 right, v2 wrong (decorrelated, selector has room)
    # unit B: both wrong (hard ceiling)
    # unit C: both right
    return pd.DataFrame({
        "unit": ["A", "A", "B", "B", "C", "C"],
        "view": ["v1", "v2", "v1", "v2", "v1", "v2"],
        "both_err": [0.02, 0.5, 0.9, 0.8, 0.01, 0.03],
    })


def test_correctness_matrix_and_union():
    m, units = M.correctness_matrix(_long(), unit_key=["unit"], view_col="view")
    assert units == [("A",), ("B",), ("C",)]      # keys are tuples of the unit_key columns
    assert m.tolist() == [[True, False], [False, False], [True, True]]


def test_stats_separate_selection_room_from_hard_ceiling():
    long = _long()
    out = M.ceiling_by_stratum(long, unit_key=["unit"], view_col="view",
                              strata={"all_units": np.ones(len(long), dtype=bool)},
                              production_view="v1")["strata"]["all_units"]
    assert out["units"] == 3 and out["views"] == 2
    assert out["production_view_hit"] == pytest.approx(2 / 3, abs=1e-4)
    assert out["best_single_view_hit"] == pytest.approx(2 / 3, abs=1e-4)     # v1 == v2 individually here
    assert out["union_oracle_hit"] == pytest.approx(2 / 3, abs=1e-4)         # unit B is unreachable
    assert out["no_view_correct_share"] == pytest.approx(1 / 3, abs=1e-4)
    assert out["hard_ceiling_units"] == 1
    assert out["correct_count_histogram"] == {"0": 1, "1": 1, "2": 1}
    # v2 is wrong exactly where v1 is right and vice versa on unit A -> partial decorrelation
    assert out["regret_recoverable_by_selection_pp"] == pytest.approx(0.0)


def test_regret_counts_units_the_production_view_missed_but_some_view_hit():
    long = pd.DataFrame({"unit": ["A", "A", "B", "B"],
                         "view": ["v1", "v2", "v1", "v2"],
                         "both_err": [0.5, 0.02, 0.9, 0.8]})
    out = M.ceiling_by_stratum(long, unit_key=["unit"], view_col="view",
                              strata={"all": np.ones(4, dtype=bool)}, production_view="v1")
    st = out["strata"]["all"]
    assert st["production_view_hit"] == 0.0
    assert st["union_oracle_hit"] == 0.5
    assert st["regret_recoverable_by_selection_pp"] == pytest.approx(50.0, abs=1e-3)
    assert st["hard_ceiling_units"] == 1


def test_tolerance_sensitivity_is_reported():
    long = _long()
    out = M.ceiling_by_stratum(long, unit_key=["unit"], view_col="view",
                              strata={"all": np.ones(len(long), dtype=bool)})
    sens = out["tolerance_sensitivity"]
    assert set(sens) == {"50ms", "100ms", "200ms"}
    assert sens["50ms"]["union_oracle_hit"] <= sens["100ms"]["union_oracle_hit"] <= \
        sens["200ms"]["union_oracle_hit"]


def test_build_long_from_wide_computes_canonical_error():
    wide = pd.DataFrame({"view": ["a", "a"], "pred_start_sec": [0.0, 1.0],
                         "pred_end_sec": [1.0, 2.0], "gt_start_sec": [0.0, 1.05],
                         "gt_end_sec": [1.0, 2.0]})
    d = M.build_long_from_wide(wide, view_prefix_col="view", unit_key=["pred_start_sec"],
                               gt_start="gt_start_sec", gt_end="gt_end_sec")
    assert d["both_err"].tolist()[1] == pytest.approx(0.05)
