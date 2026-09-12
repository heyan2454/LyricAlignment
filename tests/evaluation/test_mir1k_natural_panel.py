"""Fast (L1) tests for the natural-Mandarin MIR-1K panel (reference join, position axes, AUC).

Synthetic files only: the module paths are monkeypatched, so nothing touches the data disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import mir1k_natural_panel as M


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


@pytest.fixture()
def tiny_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path
    gt = [{"item_id": "songA", "character_index": i, "normalized_character": ch,
           "start_sec": 1.0 + 0.5 * i, "end_sec": 1.0 + 0.5 * i + 0.4}
          for i, ch in enumerate("abcd")]
    gt += [{"item_id": "songB", "character_index": i, "normalized_character": ch,
            "start_sec": 2.0 + 0.5 * i, "end_sec": 2.0 + 0.5 * i + 0.4}
           for i, ch in enumerate("ef")]
    _write_jsonl(root / "gt_characters.jsonl", gt)
    _write_jsonl(root / "gt_manifest.jsonl",
                 [{"item_id": "songA", "duration_sec": 4.0},      # NOTE: no character_count field
                  {"item_id": "songB", "duration_sec": 3.0}])
    dur_by_item = {"songA": 4.0, "songB": 3.0}
    preds = []
    for row in gt:
        shift = 0.02 if row["item_id"] == "songA" else 0.6      # songB is wrong
        preds.append({"item_id": row["item_id"], "character_index": row["character_index"],
                      "normalized_character": row["normalized_character"],
                      "start_sec": round(row["start_sec"] + shift, 4),
                      "end_sec": round(row["end_sec"] + shift, 4),
                      # fields the production pipeline injects (audio contract + probe metadata)
                      "vocal_source": "official_vocal_channel",
                      "item_duration_sec": dur_by_item[row["item_id"]]})
    p1 = root / "runs/pred_a/predictions.jsonl"
    p2 = root / "runs/pred_b/predictions.jsonl"
    _write_jsonl(p1, preds)
    _write_jsonl(p2, [{**r, "start_sec": r["start_sec"] + 0.05} for r in preds])
    monkeypatch.setattr(M, "GT_CHARS", root / "gt_characters.jsonl")
    monkeypatch.setattr(M, "GT_MANIFEST", root / "gt_manifest.jsonl")
    monkeypatch.setattr(M, "PRED_RUNS", {"pred_a": p1, "pred_b": p2})
    return root


def test_char_counts_come_from_the_reference_not_the_manifest(tiny_dataset: Path):
    """Regression guard: manifest has no `character_count`; reading it as 0 destroyed the
    position analysis in the first version of this panel."""
    df, audit = M.build_panel()
    assert set(df["item_id"]) == {"songA", "songB"}
    assert int(df[df["item_id"] == "songA"]["item_chars"].iloc[0]) == 4
    assert int(df[df["item_id"] == "songB"]["item_chars"].iloc[0]) == 2
    frac = df[df["item_id"] == "songA"]["frac_pos"]
    assert float(frac.min()) == 0.0 and float(frac.max()) == 1.0
    assert df[df["item_id"] == "songA"]["is_last_char"].sum() == 2   # one per predictor
    assert audit["predictors"]["pred_a"]["matched_to_reference"] == 6
    assert audit["predictors"]["pred_a"]["unmatched_rows"] == 0
    assert audit["predictors"]["pred_a"]["character_mismatches"] == 0


def test_position_buckets_split_first_middle_last(tiny_dataset: Path):
    """Position axes must be populated from real character counts (the earlier bug left only two
    buckets because the manifest lacked `character_count`)."""
    df, audit = M.build_panel()
    out = M.analyse(df, audit)
    prof = {r["bucket"]: r for r in out["position_effects"]["pred_a"]["by_position"]}
    assert {"first char", "middle", "last char"} <= set(prof)
    assert all(r["n"] > 0 for r in prof.values())
    # songA is accurate (+0.02 s), songB is late by 0.6 s -> the last character of each item is
    # where the wrong item shows up first, so first/last buckets must be worse than middle
    assert prof["middle"]["hit100"] == 1.0
    assert prof["first char"]["hit100"] < 1.0 and prof["last char"]["hit100"] < 1.0
    assert out["by_predictor"]["pred_a"]["hit100"] == pytest.approx(4 / 6, abs=1e-4)
    assert all(r["share_pred_start_at_zero"] == 0.0 for r in prof.values())


def test_disagreement_needs_three_predictors_including_reference(tiny_dataset: Path):
    """With only two systems there is no leave-one-out ensemble: the panel must say so
    instead of reporting a signal computed from a single peer."""
    df, audit = M.build_panel()
    out = M.analyse(df, audit)
    disq = out["disagreement_signal_natural"]
    assert disq["reference_predictor"] == "pred_a"
    assert disq["sets"] == {}


def test_disagreement_reports_auc_with_three_predictors(tiny_dataset: Path,
                                                        monkeypatch: pytest.MonkeyPatch):
    third = tiny_dataset / "runs/pred_c/predictions.jsonl"
    rows = []
    for path in (M.PRED_RUNS["pred_a"],):
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            r["start_sec"] += 0.5 if r["item_id"] == "songB" else 0.0
            rows.append(r)
    third.parent.mkdir(parents=True, exist_ok=True)
    third.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(M, "PRED_RUNS", {**M.PRED_RUNS, "pred_c": third})
    df, audit = M.build_panel()
    out = M.analyse(df, audit)
    disq = out["disagreement_signal_natural"]
    sets = disq["sets"]
    assert sets, "expected a disagreement set once three predictors exist"
    # pred_b/pred_c deviate only slightly from pred_a -> all three are peers, none is weak
    assert disq["membership"]["weak_excluded"] == []
    entry = sets["strong_peers_only"]
    assert entry["n_units"] == 6
    assert 0.0 <= entry["median_spread_sec"] <= 2.0
    assert set(entry["predictors"]) == {"pred_a", "pred_b", "pred_c"}


def test_reconciliation_skips_absent_predictors(tiny_dataset: Path):
    df, audit = M.build_panel()
    out = M.analyse(df, audit)
    assert out["canonical_reconciliation"]["per_predictor"] == {}


def test_defect_counts_match_synthetic_geometry(tiny_dataset: Path):
    df, audit = M.build_panel()
    out = M.analyse(df, audit)
    d = out["structural_defects_by_predictor"]["pred_a"]
    assert d["n"] == 6
    assert d["zero_or_negative_duration_share"] == 0.0
    assert d["negative_duration_share"] == 0.0
    # two songB units start after their own ground-truth end; one exceeds the item duration
    assert d["start_after_gt_end_share"] == pytest.approx(2 / 6, abs=1e-4)
    assert d["out_of_item_range_share"] == pytest.approx(1 / 6, abs=1e-4)
    runs = out["error_runs_natural"]
    assert runs["reference_predictor"] == "pred_a"
    assert runs["run_lengths"] == {"2": 1}
    assert runs["share_bad_in_runs_ge2"] == 1.0


def test_last_character_and_unstable_census(tiny_dataset: Path):
    """Two follow-up analyses added after the first pass: the last-character attribution and the
    cross-predictor instability census must run and expose their guard rails."""
    df, audit = M.build_panel()
    last = M.analyse_last_character(df, "pred_a")
    assert last["available"] is True
    assert last["n_last"] == 2                                  # one per item
    assert set(last["last_signature"]) >= {"hit100", "mae_end", "pred_end_beyond_item_share",
                                           "mean_gt_dur"}
    # songB's late-shifted final note does run past its item duration -> detects truncation risk
    assert last["last_signature"]["pred_end_beyond_item_share"] == pytest.approx(0.5)
    assert last["last_signature"]["gt_end_beyond_item_share"] == 0.0
    assert last["middle_signature"]["hit100"] == 1.0

    uns = M.analyse_unstable_units(df, ["pred_a", "pred_b"])
    assert uns["available"] is True
    assert uns["n_units"] == 6
    assert 0.0 <= uns["unstable_share"] <= 1.0
    assert uns["auc_spread_vs_bad100"] is None or 0.0 <= uns["auc_spread_vs_bad100"] <= 1.0
    # a single peer is enough here, but zero or one predictor must bail out
    assert M.analyse_unstable_units(df, ["pred_a"])["available"] is False


def test_auc_and_ci_helpers():
    y = np.array([0, 0, 1, 1] * 20, dtype=float)
    s = np.array([-1.0, -0.5, 0.5, 1.0] * 20, dtype=float)
    assert M._auc(y, s) == pytest.approx(1.0)
    assert M._auc(y, -s) == pytest.approx(0.0)
    assert M._auc(np.ones(len(s)), s) is None                    # single class
    vals = np.array([1.0, 0.0, 1.0, 0.0] * 5)
    groups = np.array(["a", "a", "b", "b"] * 5)
    point, ci = M._seg_ci(vals, groups)
    assert 0.0 <= ci[0] <= point <= ci[1] <= 1.0
