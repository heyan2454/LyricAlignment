"""Fast (L1) tests for the post-processing policy-replay module.

Synthetic frames only; no external data directory access.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import postprocess_replay as pr


def _toy_units() -> tuple[np.ndarray, np.ndarray]:
    # unit 0's raw tail (0.8) overlaps unit 1's raw onset (0.5); unit 2 is clean
    return np.array([0.0, 0.5, 1.5]), np.array([0.8, 1.2, 2.0])


def test_rule_end_trim_only_moves_earlier_tail():
    s, e = _toy_units()
    S, E = pr.rule_end_trim(s, e, {})
    assert np.allclose(S, [0.0, 0.5, 1.5])           # onsets untouched
    assert np.allclose(E, [0.5, 1.2, 2.0])           # overlap resolved from the left unit


def test_rule_start_push_only_moves_later_onset():
    s, e = _toy_units()
    S, E = pr.rule_start_push(s, e, {})
    assert np.allclose(S, [0.0, 0.8, 1.5])
    assert np.allclose(E, [0.8, 1.2, 2.0])


def test_rule_half_split_is_symmetric():
    s, e = _toy_units()
    S, E = pr.rule_half_split(s, e, {})
    assert np.isclose(E[0], S[1]) and np.isclose(E[0], 0.65)


def test_confidence_split_lets_the_less_confident_side_move_more():
    s, e = _toy_units()
    ex = {"conf_start": np.array([0.9, 0.9, 0.9]),   # unit 1 onset is confident
          "conf_end": np.array([0.1, 0.9, 0.9])}     # unit 0 tail is not
    S, E = pr.rule_conf_split(s, e, ex)
    assert E[0] - s[1] > 0 and E[0] < 0.8 and S[1] > 0.5
    assert (0.8 - E[0]) > (S[1] - 0.5)               # the low-confidence tail moved further
    # symmetric case collapses to the midpoint
    ex2 = {"conf_start": np.array([0.9, 0.5, 0.9]), "conf_end": np.array([0.5, 0.9, 0.9])}
    S2, E2 = pr.rule_conf_split(s, e, ex2)
    assert np.isclose(E2[0], S2[1]) and np.isclose(E2[0], 0.65)


def test_min_duration_guard_avoids_zero_length_units():
    s, e = np.array([0.0, 0.0]), np.array([0.9, 0.6])      # identical onsets: pure trim collapses u0
    plain_S, plain_E = pr.rule_end_trim(s, e, {})
    assert (plain_E - plain_S <= 1e-9).any()
    gS, gE = pr._end_trim_with_min_duration(0.05)(s, e, {})
    assert np.all(gE - gS >= 0.05 - 1e-9)
    hS, hE = pr._half_split_with_min_duration(0.05)(s, e, {})
    assert np.all(hE - hS >= 0.05 - 1e-9)


def test_thresholded_rule_leaves_large_overlap_alone():
    s, e = _toy_units()
    rule = pr._thresholded_resolver("end", 0.10)      # overlap here is 0.30 > 0.10
    S, E = rule(s, e, {})
    assert np.allclose(E, e) and np.allclose(S, s)
    rule2 = pr._thresholded_resolver("end", 0.50)
    S2, E2 = rule2(s, e, {})
    assert np.isclose(E2[0], 0.5)


def test_oracle_pick_uses_ground_truth_to_choose():
    s, e = _toy_units()
    ex = {"gt_start": np.array([0.0, 0.8, 1.5]), "gt_end": np.array([0.8, 1.2, 2.0]),
          "conf_start": np.ones(3), "conf_end": np.ones(3)}
    S, E = pr.rule_oracle_pick(s, e, ex)
    assert np.isclose(E[0], 0.8) and np.isclose(S[1], 0.8)   # start push matches GT here


def _frame() -> pd.DataFrame:
    """Crafted frame: the raw *tail* overshoots while the raw *onset* is nearly right.

    gt      u0 [0.00,0.55]  u1 [0.60,1.20]  u2 [1.50,2.00]
    raw     u0 [0.00,0.80]  u1 [0.50,1.20]  u2 [1.50,2.00]   (0.30 s overlap u0/u1)
    shipped official resolves it by pushing u1's onset to u0's tail (0.80) -> both u0 and u1 fail
    an end-trim-only rule pulls u0's tail to 0.50 -> everything passes
    the raw pipeline also applies a small end clamp on u0 (0.80 -> 0.75) -> stage-definition delta
    """
    rows = []
    for pipeline in ("official", "raw"):
        for item in ("A", "B"):
            for i in range(3):
                raw_s = [0.0, 0.5, 1.5][i]
                raw_e = [0.8, 1.2, 2.0][i]
                sel_s = [0.0, 0.8, 1.5][i] if pipeline == "official" else raw_s
                sel_e = [0.8, 1.2, 2.0][i] if pipeline == "official" else [0.75, 1.2, 2.0][i]
                rows.append({
                    "pipeline": pipeline, "item": item, "model": "r2", "audio_input": "vocal",
                    "mode": "windowed", "unit_index": i, "group": "Control_Group",
                    "singer": "ZH-Tenor-1", "raw_start_sec": raw_s, "raw_end_sec": raw_e,
                    "pred_start_sec": sel_s, "pred_end_sec": sel_e,
                    "gt_start_sec": [0.0, 0.6, 1.5][i], "gt_end_sec": [0.55, 1.2, 2.0][i],
                    "gt_dur_sec": [0.55, 0.6, 0.5][i], "gt_is_multi_phoneme": [1, 0, 1][i],
                    "raw_top1_start": 0.7, "raw_top1_end": 0.6,
                })
    return pd.DataFrame(rows)


def test_replay_and_compare_end_to_end():
    scored = pr.score(pr.replay_all(pr.prepare(_frame())))
    assert set(scored["rule"]) == set(pr.RULES)
    agg = pr.compare(scored)
    rules = agg["rules"]
    assert rules["V2_end_trim_only"]["hit100_micro"] > rules["V0_shipped_official"]["hit100_micro"]
    assert rules["V2_end_trim_only"]["hit100_micro"] > rules["V1_raw_none"]["hit100_micro"]
    assert rules["V99_oracle_pick_uses_gt"]["hit100_micro"] >= rules["V2_end_trim_only"]["hit100_micro"]
    paired = rules["V2_end_trim_only"]["paired_vs_reference"]
    assert paired["sequences_better"] == 2 and paired["sequences_worse"] == 0
    assert rules["V2_end_trim_only"]["uses_gt"] is False
    assert rules["V99_oracle_pick_uses_gt"]["uses_gt"] is True
    assert agg["strata"]["V2_end_trim_only"]["first_unit_n"] == 2
    assert agg["strata"]["V0_shipped_official"]["onsetless_hit100"] is not None


def test_reconstruct_shipped_rule_counts_outcomes():
    recon = pr.reconstruct_shipped_rule(pr.prepare(_frame()))
    assert recon["overlap_rate"] == pytest.approx(2 / 6, abs=1e-3)
    assert recon["overlap_outcome"]["start_pushed_only"] == 2
    assert recon["overlap_outcome"]["end_trimmed_only"] == 0
    assert recon["overlap_and_start_moved"]["share_pinned_to_prev_raw_end"] == pytest.approx(1.0)
    assert recon["zero_duration"]["final_rate"] >= recon["zero_duration"]["raw_rate"]


def test_stage_consistency_reports_perfect_forward_determinism():
    out = pr.stage_consistency(_frame())
    assert out["available"] is True
    # identical audio/text/model => identical raw stage across the two pipelines
    assert out["forward_determinism"]["n_differing_gt_1ms"] == 0
    assert out["raw_pipeline_self_adjustment"]["n_adjusted"] == 2
    assert out["official_pipeline_adjustment"]["n_adjusted"] == 2
    assert out["cross_pipeline_selected_vs_raw"]["n_differing"] == 2
    assert out["cross_pipeline_selected_vs_raw"]["share_end_only"] == 1.0
