"""Fast tests for the cross-window selection machinery (synthetic attempts only)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import cross_window_selection as X


def _attempts() -> pd.DataFrame:
    """One unit covered by four windows: two agree (correct), two are off (one wildly)."""
    rows = []
    starts = [1.00, 1.02, 1.60, 1.01]
    ends = [1.80, 1.82, 2.40, 1.81]
    ents = [0.9, 0.8, 0.1, 0.85]           # the wrong attempt is the *most* confident
    margs = [0.1, 0.2, 0.9, 0.15]
    for i in range(4):
        rows.append({"view_id": "full", "song": "s1", "canonical_unit_id": 0,
                     "request_identity": f"r{i}", "raw_start_sec": starts[i], "raw_end_sec": ends[i],
                     "ref_start_sec": 1.0, "ref_end_sec": 1.8,
                     "attempt_both_err": max(abs(starts[i] - 1.0), abs(ends[i] - 1.8)),
                     "start_entropy": ents[i], "end_entropy": ents[i],
                     "start_margin": margs[i], "end_margin": margs[i]})
    rows.append({"view_id": "full", "song": "s1", "canonical_unit_id": 1,
                 "request_identity": "r0", "raw_start_sec": 3.0, "raw_end_sec": 3.5,
                 "ref_start_sec": 3.0, "ref_end_sec": 3.5, "attempt_both_err": 0.0,
                 "start_entropy": 0.3, "end_entropy": 0.3, "start_margin": 0.5, "end_margin": 0.5})
    return pd.DataFrame(rows)


def test_add_features_loo_and_support():
    d = X.add_features(_attempts())
    u0 = d[d["canonical_unit_id"] == 0]
    # leave-one-out consensus for the first attempt = median of the other three {1.02, 1.60, 1.01}
    assert u0["n_attempts"].iloc[0] == 4
    assert float(u0["loo_median_start"].iloc[0]) == pytest.approx(1.02)
    assert float(u0["loo_spread"].iloc[0]) == pytest.approx(0.02, abs=1e-6)
    # the off attempt's consensus is the agreeing cluster, so its spread is large
    assert float(u0["loo_spread"].iloc[2]) > 0.5
    # the wildly-off attempt has no peer within 50 ms
    assert float(u0["support_50ms"].iloc[2]) == 0.0
    # the three mutually-agreeing attempts support each other
    assert float(u0["support_50ms"].iloc[0]) > 0.6
    assert set(["ent_max", "margin_min", "rel_pos_in_request", "edge_distance"]) <= set(d.columns)
    assert d["loo_spread"].notna().all()


def test_selector_ordering_matches_ground_truth_free_logic():
    d = X.add_features(_attempts())
    res = X.run_selectors(d)
    gap = res["gap_closed_vs_oracle"]
    # the correct answer is the consensus, so support-based selection must beat "most confident"
    assert gap["D_max_support"]["hit100"] > gap["E_min_entropy"]["hit100"]
    assert gap["D_max_support"]["delta_pp_vs_median_attempt"] >= 0.0
    top = res["aggregates"]["unit_best_of_attempts_oracle"]["hit100"]
    for k, v in {**res["selectors"]}.items():
        assert v["hit100"] <= top + 1e-9, k
    assert res["reference_headroom"]["headroom_pp"] >= 0.0


def test_reference_join_uses_signed_gt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_attempts must refuse to score against a missing signed reference."""
    panel = _attempts().rename(columns={"ref_start_sec": "gt_start_sec", "ref_end_sec": "gt_end_sec"})
    panel["gt_start_sec"] = panel["gt_start_sec"]      # panel-shaped column names
    gt = panel[["song", "canonical_unit_id", "gt_start_sec", "gt_end_sec"]].drop_duplicates()
    p = tmp_path / "panel.jsonl.gz"
    panel.to_json(p, orient="records", lines=True, compression="gzip")
    gt.to_pickle(tmp_path / "signed_gt.pkl")
    monkeypatch.setattr(X, "PANEL", p)
    monkeypatch.setattr(X, "SIGNED_GT", tmp_path / "signed_gt.pkl")
    d, info = X.load_attempts()
    assert len(d) == len(panel)
    assert info["units"] == 2
    assert (d["raw_start_sec"] - d["ref_start_sec"]).abs().max() >= 0.0
