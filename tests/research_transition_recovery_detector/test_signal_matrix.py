"""09 §3 P4：detector 信号族特征与 SIGNAL_COMPLETION_MATRIX 测试。

覆盖：各信号族 fixture 提取正确、无 GT 泄漏、H 族 not_available、SIGNAL_GROUPS
覆盖 FEATURE_NAMES 全集、matrix 行状态语义。
"""

import importlib.util
import json
from pathlib import Path

import pytest

from lyricalign.research_transition_recovery_detector.detector_features import (
    FEATURE_NAMES,
    SIGNAL_GROUPS,
    cross_window_features,
    extract_context_features,
    extract_hidden_features,
    extract_official_geometry,
    extract_posterior_competition,
    extract_propagation_risk,
    extract_raw_geometry,
    extract_raw_official_interaction,
    extract_signal_features,
    extract_trajectory,
    extract_unit_features,
)

REPO_ROOT = Path(__file__).parents[2]
_SCRIPT = REPO_ROOT / "scripts/research_transition_recovery_detector/build_signal_matrix.py"
_spec = importlib.util.spec_from_file_location("build_signal_matrix", _SCRIPT)
bsm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bsm)


def make_row(**overrides):
    base = {
        "global_character_index": 0,
        "character": "A",
        "fixed_global_start_sec": 10.0,
        "fixed_global_end_sec": 10.5,
        "raw_start_entropy": 0.5,
        "raw_end_entropy": 0.6,
        "raw_start_margin": 0.3,
        "raw_end_margin": 0.2,
        "raw_start_top1_probability": 0.7,
        "raw_end_top1_probability": 0.65,
        "official_fixed_global_start_sec": 10.2,
        "official_fixed_global_end_sec": 10.6,
        "raw_start_topk_probabilities": [0.7, 0.2, 0.1],
        "raw_end_topk_probabilities": [0.65, 0.2, 0.15],
        "raw_start_topk_classes": [3, 4],
    }
    base.update(overrides)
    return base


def test_r_raw_geometry_values_and_interval_diff():
    rows = [make_row(), make_row(global_character_index=1, fixed_global_start_sec=10.5, fixed_global_end_sec=10.6)]
    r = extract_raw_geometry(rows)
    assert r[0]["raw_start_entropy"] == pytest.approx(0.5)
    assert r[0]["raw_start_interval_gap_sec"] is None
    assert r[1]["raw_start_interval_gap_sec"] == pytest.approx(0.5)
    assert r[1]["raw_end_interval_gap_sec"] == pytest.approx(0.1)


def test_o_official_geometry_repair_shift_and_run():
    rows = [
        make_row(global_character_index=0, fixed_global_start_sec=10.0, official_fixed_global_start_sec=10.2),
        make_row(global_character_index=1, fixed_global_start_sec=11.0, official_fixed_global_start_sec=11.2),
        make_row(global_character_index=2, fixed_global_start_sec=12.0, official_fixed_global_start_sec=11.95),
    ]
    o = extract_official_geometry(rows)
    assert o[0]["repair_shift_sec"] == pytest.approx(0.2)
    assert o[0]["repair_shift_abs_sec"] == pytest.approx(0.2)
    assert o[0]["official_start_sec"] == pytest.approx(10.2)
    assert o[0]["repair_shift_run_len"] == 1.0
    assert o[1]["repair_shift_run_len"] == 2.0
    assert o[2]["repair_shift_run_len"] == 1.0  # 符号翻转 → run 重置
    assert o[1]["repair_shift_delta_sec"] == pytest.approx(0.0)


def test_ro_interaction_bucket_and_sign():
    rows = [make_row(global_character_index=0, fixed_global_start_sec=10.0, official_fixed_global_start_sec=10.35)]
    ro = extract_raw_official_interaction(rows)[0]
    assert ro["raw_official_start_diff_sec"] == pytest.approx(0.35)
    assert ro["raw_official_start_diff_bucket"] == 1.0  # 0.1 <= diff < 0.5
    assert ro["raw_official_start_diff_sign"] == 1.0  # raw 晚于 official
    rows2 = [make_row(global_character_index=0, fixed_global_start_sec=10.0, official_fixed_global_start_sec=10.0)]
    ro2 = extract_raw_official_interaction(rows2)[0]
    assert ro2["raw_official_start_diff_bucket"] == 0.0
    assert ro2["raw_official_start_diff_sign"] == 0.0


def test_p_posterior_competition():
    row = make_row(
        raw_start_topk_probabilities=[0.7, 0.2, 0.1],
        raw_start_topk_classes=[3, 4],
        raw_end_topk_probabilities=[0.4, 0.35],
    )
    p = extract_posterior_competition([row])[0]
    assert p["start_top2_gap_sec"] == pytest.approx(0.5)
    assert p["start_second_peak_ratio"] == pytest.approx(0.2 / 0.7)
    assert p["start_second_peak_adjacent"] == 1.0  # classes 3/4 相邻
    assert p["end_top2_gap_sec"] == pytest.approx(0.05)


def test_p_second_peak_adjacency_nonadjacent():
    row = make_row(raw_start_topk_classes=[3, 7])
    p = extract_posterior_competition([row])[0]
    assert p["start_second_peak_adjacent"] == 0.0


def test_s_trajectory_velocity_acceleration_and_runs():
    rows = [
        make_row(global_character_index=0, fixed_global_start_sec=10.0, fixed_global_end_sec=10.5),
        make_row(global_character_index=1, fixed_global_start_sec=10.5, fixed_global_end_sec=11.0),
        make_row(global_character_index=2, fixed_global_start_sec=11.0, fixed_global_end_sec=11.5),
        make_row(global_character_index=3, fixed_global_start_sec=11.7, fixed_global_end_sec=12.0),
    ]
    s = extract_trajectory(rows)
    assert s[0]["start_velocity_sec"] is None
    assert s[0]["start_acceleration_sec"] is None
    assert s[0]["gap_overlap_sec"] is None
    assert s[1]["start_velocity_sec"] is None  # 无前序间隔
    assert s[1]["start_acceleration_sec"] is None
    assert s[1]["gap_overlap_sec"] == pytest.approx(0.0)  # prev_end == start
    assert s[1]["zero_duration_run_len"] == 0.0
    assert s[2]["start_velocity_sec"] == pytest.approx(0.0)  # 0.5 - 0.5
    assert s[2]["start_acceleration_sec"] is None
    assert s[3]["start_velocity_sec"] == pytest.approx(0.2)  # 0.7 - 0.5
    assert s[3]["start_acceleration_sec"] == pytest.approx(0.2)
    row = make_row(fixed_global_start_sec=10.0, fixed_global_end_sec=10.0)
    assert extract_signal_features([row])[0]["raw_zero_duration_flag"] == 1.0


def test_v_cross_window_displacement_and_std():
    obs = {
        0: [
            make_row(global_character_index=0, fixed_global_start_sec=10.0, raw_start_top1_probability=0.7),
            make_row(global_character_index=0, fixed_global_start_sec=10.3, raw_start_top1_probability=0.6),
        ]
    }
    v = cross_window_features(obs)
    assert v[0]["v_n_observations"] == 2.0
    assert v[0]["v_start_displacement_sec"] == pytest.approx(0.3)
    assert v[0]["v_start_std_sec"] == pytest.approx(0.15)
    assert v[0]["v_start_top1_std"] == pytest.approx(0.05)
    single = cross_window_features({1: [make_row()]})
    assert single[1]["v_start_std_sec"] is None


def test_h_not_available_without_hidden_and_available_with():
    rows = [make_row()]
    h = extract_hidden_features(rows)[0]
    assert h["status"] == "not_available"
    assert h["reason"] is not None
    assert all(v is None for v in h["features"].values())
    unit = extract_unit_features(rows[0])
    assert unit["h_hidden_available"] is None
    rows2 = [make_row(hidden_last_layer_l2_norm=1.5, hidden_early_layer_l2_norm=0.8)]
    h2 = extract_hidden_features(rows2)[0]
    assert h2["status"] == "available"
    assert h2["features"]["h_last_layer_l2_norm"] == pytest.approx(1.5)
    assert h2["features"]["h_early_layer_l2_norm"] == pytest.approx(0.8)


def test_pr_gate_required_and_no_label_read():
    row = make_row(
        fixed_global_start_sec=10.0,
        official_fixed_global_start_sec=10.4,
        gt_leak_start_sec=999.0,
        gt_safe=1,
    )
    pr = extract_propagation_risk([row])[0]
    assert pr["status"] == "gate_p_required"
    assert pr["reason"] is not None
    feats = pr["features"]
    assert feats["pr_shift_abs_sec"] == pytest.approx(0.4)
    assert feats["pr_entropy_max"] == pytest.approx(0.6)
    assert 999.0 not in feats.values()
    assert 1.0 not in feats.values()


def test_no_gt_future_mutation_leak_in_any_feature():
    row = make_row(
        gt_start_sec=999.0,
        gt_safe=1.0,
        future_start_sec=888.0,
        mutation_family="replace",
        hidden_last_layer_l2_norm=7.0,
    )
    full = extract_signal_features([row])[0]
    for name in FEATURE_NAMES:
        assert not name.startswith(("gt_", "future_", "mutation_"))
        assert name not in ("gt_start_sec", "gt_safe", "future_start_sec", "mutation_family")
    assert 999.0 not in full.values() and 888.0 not in full.values()
    assert "mutation_family" not in full


def test_signal_groups_cover_feature_names_exactly_and_disjoint():
    names = [n for group in SIGNAL_GROUPS.values() for n in group]
    assert len(names) == len(set(names))  # 组间不相交
    assert set(names) == set(FEATURE_NAMES)
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert list(SIGNAL_GROUPS) == ["R", "O", "RO", "V", "P", "S", "H", "PR"]
    assert FEATURE_NAMES[:8] == (
        "raw_start_entropy",
        "raw_end_entropy",
        "raw_start_margin",
        "raw_end_margin",
        "raw_start_top1_probability",
        "raw_end_top1_probability",
        "raw_official_start_diff_sec",
        "start_top2_gap_sec",
    )


def test_context_features_never_read_future_rows():
    rows = [make_row(global_character_index=i, fixed_global_start_sec=10.0 + i) for i in range(3)]
    ctx = extract_context_features(rows)
    assert ctx[0]["raw_start_interval_gap_sec"] is None
    assert ctx[1]["raw_start_interval_gap_sec"] == pytest.approx(1.0)
    assert ctx[2]["raw_start_interval_gap_sec"] == pytest.approx(1.0)


def test_matrix_default_pending_none_completed():
    m = bsm.build_matrix()
    assert m["schema_version"] == "signal_completion_matrix_v1"
    assert m["n_rows"] == 8
    assert m["n_completed"] == 0
    branch_ids = [r["branch_id"] for r in m["rows"]]
    assert branch_ids == [
        "H",
        "R",
        "O",
        "H+R",
        "H+O",
        "R+O",
        "H+R+O",
        "H+R+O+selected(V/P/S)",
    ]
    for row in m["rows"]:
        assert set(row) == {
            "branch_id",
            "signal_groups",
            "status",
            "input_artifacts",
            "n_train_songs",
            "n_val_songs",
            "n_test_songs",
            "n_units",
            "n_intervals",
            "metrics_artifact",
            "failure_or_block_reason",
        }
        assert row["status"] == "pending"
        assert row["input_artifacts"]


def test_matrix_completed_semantics():
    m = bsm.build_matrix(status="executed")
    assert m["n_completed"] == 8
    m2 = bsm.build_matrix(status="negative")
    assert m2["n_completed"] == 8
    for bad in ("failed", "skipped_budget"):
        m3 = bsm.build_matrix(status=bad)
        assert m3["n_completed"] == 0
        assert m3["completed_rows"] == []


def test_matrix_overrides_and_write(tmp_path):
    session = tmp_path / "session"
    out = session / "06_detector" / "SIGNAL_COMPLETION_MATRIX.json"
    overrides = {"H": {"status": "failed", "failure_or_block_reason": "blocked_api: no hidden hook"}, "R": {"status": "executed", "n_units": 100, "metrics_artifact": "06_detector/wp_R.json"}}
    ov_file = tmp_path / "ov.json"
    ov_file.write_text(json.dumps(overrides), encoding="utf-8")
    rc = bsm.main(["--session-root", str(session), "--status", "executed", "--overrides", str(ov_file)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    h = next(r for r in data["rows"] if r["branch_id"] == "H")
    assert h["status"] == "failed"
    assert h["failure_or_block_reason"].startswith("blocked_api")
    r = next(r for r in data["rows"] if r["branch_id"] == "R")
    assert r["status"] == "executed" and r["n_units"] == 100
    assert data["n_completed"] == 7  # executed 7 行，failed 的 H 不算完成
    assert "H" not in data["completed_rows"]
