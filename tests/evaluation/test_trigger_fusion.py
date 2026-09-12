"""Tests for the fused reference-free trigger and the re-decode queue."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import trigger_fusion as TF


def _frame(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    gt_end = np.arange(n) * 1.0 + 0.5
    pred_end = gt_end + rng.normal(0, 0.05, n)
    bad = np.arange(20)                       # a block of clearly wrong units
    pred_end[bad] = gt_end[bad] - 0.4         # truncated by 400 ms
    return pd.DataFrame({
        "song": ["a"] * (n // 2) + ["b"] * (n - n // 2),
        "unit_index": np.arange(n),
        "raw_start_sec": pred_end - 0.4,
        "raw_end_sec": np.where(np.arange(n) % 37 == 0, pred_end - 0.9, pred_end - 0.4),
        "raw_entropy_end": np.where(np.arange(n) < 20, 2.0, 0.3),
        "gap_over_core": np.where(np.arange(n) < 20, 1.1, 0.1),
        "pred_start_sec": pred_end - 0.4, "pred_end_sec": pred_end,
        "gt_start_sec": gt_end - 0.4, "gt_end_sec": gt_end,
        "gt_dur_sec": np.full(n, 0.4)})


def test_build_features_flags_each_signal_independently():
    d = TF.build_features(_frame())
    assert d["flag_inversion"].sum() > 0
    assert d["flag_gap_residual"].mean() > 0
    assert d["flag_high_entropy_end"].mean() <= 0.35   # rank-based, never the whole batch
    assert d["fused_mean_rank"].notna().any()
    assert "flag_low_conf_end" not in d.columns       # top-1 probabilities absent here, not invented


def test_entropy_flag_is_rank_based_not_absolute():
    """An absolute entropy threshold does not transfer between batches; the quantile does."""
    d = TF.build_features(_frame())
    share = float(d["flag_high_entropy_end"].mean())
    low = _frame().assign(raw_entropy_end=lambda x: x["raw_entropy_end"] * 10)   # globally louder entropy
    d2 = TF.build_features(low)
    assert abs(share - float(d2["flag_high_entropy_end"].mean())) < 0.02


def test_evaluate_triggers_reports_auc_and_budgeted_recall():
    d = TF.build_features(_frame())
    out = TF.evaluate_triggers(d)
    blk = out["triggers"]["end_error_gt_100ms"]
    assert blk["n"] > 0 and blk["prevalence"] > 0
    for name in ("gap_residual", "high_entropy_end", "fused_mean_rank"):
        e = blk[name]
        assert e["auc"] > 0.8, (name, e["auc"])
        assert e["recall_at_20pct_budget"] > e["recall_at_5pct_budget"]
        assert e["recall_within_scored_at_20pct_budget"] >= e["recall_at_20pct_budget"]
        assert 0.0 <= e["precision_at_20pct_budget"] <= 1.0


def test_redecode_queue_ranks_songs_and_handles_single_group_column():
    d = TF.build_features(_frame())
    q = TF.redecode_queue(d, group_cols=["song"], review_budget=0.15)
    assert list(q["song"]) == ["a", "b"] or set(q["song"]) == {"a", "b"}
    assert (q["flagged_share"].iloc[0] >= q["flagged_share"].iloc[-1])
    assert {"units", "inversion_units", "gap_residual_units", "median_fused_score"} <= set(q.columns)


def test_any_flag_is_false_when_no_signals_present():
    d = pd.DataFrame({"pred_start_sec": [0.0], "pred_end_sec": [1.0],
                      "gt_start_sec": [0.0], "gt_end_sec": [1.0]})
    feats = TF.build_features(d)
    assert bool(TF.any_flag(feats).iloc[0]) == pytest.approx(0.0)
