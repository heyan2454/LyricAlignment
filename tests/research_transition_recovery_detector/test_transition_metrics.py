import pytest

from lyricalign.research_transition_recovery_detector.transition_metrics import (
    cost_summary,
    coverage_stats,
    cursor_time_drift,
    first_error_window,
    missing_duplicate_committed,
    occurrence_jump_rate,
    unit_accuracy,
)

TOL = 0.32

GT = {
    0: {"start_sec": 0.0, "end_sec": 1.0},
    1: {"start_sec": 1.0, "end_sec": 2.0},
    2: {"start_sec": 2.0, "end_sec": 3.0},
    3: {"start_sec": 3.0, "end_sec": 4.0},
}


def _row(i, start, end=1.0, occurrence="a"):
    return {"global_character_index": i, "start_sec": start, "end_sec": start + end,
            "occurrence": occurrence}


def _record(i, committed_rows, committed_end=None, gt=None):
    state = {"committed_end_exclusive": committed_end if committed_end is not None
             else (committed_rows[-1]["global_character_index"] + 1 if committed_rows else 0)}
    return {
        "window_index": i,
        "state_after": state,
        "state_before": {"committed_end_exclusive": 0},
        "evidence_summary": {"committed_rows": committed_rows,
                             "gt": gt or {r["global_character_index"]: r for r in committed_rows}},
    }


class TestUnitAccuracy:
    def test_correct(self):
        rows = [_row(0, 0.1), _row(1, 1.05)]
        acc = unit_accuracy(rows, GT)
        assert acc == {"correct": 2, "wrong": 0, "total": 2,
                       "correct_rate": 1.0, "wrong_rate": 0.0}

    def test_wrong_beyond_tolerance(self):
        rows = [_row(0, 0.1), _row(1, 2.0)]
        acc = unit_accuracy(rows, GT, tolerance_sec=TOL)
        assert acc["wrong"] == 1 and acc["correct"] == 1 and acc["total"] == 2

    def test_boundary_exact_tolerance_is_correct(self):
        acc = unit_accuracy([_row(0, TOL)], GT)
        assert acc["correct"] == 1 and acc["wrong"] == 0

    def test_empty(self):
        acc = unit_accuracy([], GT)
        assert acc == {"correct": 0, "wrong": 0, "total": 0,
                       "correct_rate": 0.0, "wrong_rate": 0.0}


class TestCoverage:
    def test_half(self):
        assert coverage_stats(4, 2) == {"total_units": 4, "committed": 2,
                                        "uncommitted": 2, "coverage_rate": 0.5}

    def test_full_and_empty(self):
        assert coverage_stats(4, 4)["coverage_rate"] == 1.0
        assert coverage_stats(4, 0)["committed"] == 0
        assert coverage_stats(0, 0)["coverage_rate"] == 0.0


class TestCursorTimeDrift:
    def test_known_fixture(self):
        gt_all = {0: {"start_sec": 0.0}, 1: {"start_sec": 1.0},
                  2: {"start_sec": 2.0}, 3: {"start_sec": 3.0}}
        records = [
            _record(0, [_row(0, 0.05)], committed_end=1, gt=gt_all),
            _record(1, [_row(0, 0.05), _row(1, 0.8)], committed_end=2, gt=gt_all),
            _record(2, [_row(0, 0.05), _row(1, 0.8), _row(2, 2.7)], committed_end=3, gt=gt_all),
        ]
        drift = cursor_time_drift(records, gt_all)
        # 半开 cursor：每窗期望 = GT[end-1]（最后已提交行）
        assert drift["window_drifts_sec"] == pytest.approx([0.05, 0.2, 0.7])
        assert drift["max_drift_sec"] == pytest.approx(0.7)
        assert drift["final_drift_sec"] == pytest.approx(0.7)

    def test_half_open_cursor_compares_last_committed_row(self):
        # 已提交 0..2（cursor=3）：期望 = GT[2]（最后已提交行），而非 GT[3]（未提交行）
        gt_all = {0: {"start_sec": 0.0}, 1: {"start_sec": 1.0}, 2: {"start_sec": 2.0},
                  3: {"start_sec": 3.0}}
        records = [
            _record(0, [_row(0, 0.05), _row(1, 1.1), _row(2, 2.05)], committed_end=3, gt=gt_all),
        ]
        drift = cursor_time_drift(records, gt_all)
        assert drift["window_drifts_sec"] == pytest.approx([0.05])  # |2.05 - GT[2]=2.0|
        assert drift["missing_last_row_windows"] == 0

    def test_missing_last_row_reports_contract_diagnostic(self):
        # 已提交 0..2（cursor=3），但 evidence 缺最后一行（只有 0..1）→ 合同缺失诊断
        gt_all = {0: {"start_sec": 0.0}, 1: {"start_sec": 1.0}, 2: {"start_sec": 2.0}}
        records = [
            _record(0, [_row(0, 0.05), _row(1, 1.1)], committed_end=3, gt=gt_all),
        ]
        drift = cursor_time_drift(records, gt_all)
        assert drift["window_drifts_sec"] == []
        assert drift["missing_last_row_windows"] == 1

    def test_empty_records(self):
        drift = cursor_time_drift([])
        assert drift == {"window_drifts_sec": [], "max_drift_sec": 0.0, "final_drift_sec": 0.0,
                         "missing_last_row_windows": 0}


class TestFirstErrorWindow:
    def test_found(self):
        records = [
            _record(0, [_row(0, 0.1)], gt=GT),
            _record(1, [_row(1, 2.0)], gt=GT),
        ]
        assert first_error_window(records, GT) == 1

    def test_not_found(self):
        records = [_record(0, [_row(0, 0.1)], gt=GT),
                   _record(1, [_row(1, 1.0)], gt=GT)]
        assert first_error_window(records, GT) is None

    def test_empty(self):
        assert first_error_window([], GT) is None


class TestMissingDuplicate:
    def test_normal_contiguous(self):
        rows = [_row(0, 0.1), _row(1, 1.1), _row(2, 2.1)]
        out = missing_duplicate_committed(rows, GT)
        assert out == {"missing_count": 0, "duplicate_count": 0, "missing_ids": []}

    def test_gap(self):
        rows = [_row(0, 0.1), _row(2, 2.1)]
        out = missing_duplicate_committed(rows, GT)
        assert out["missing_count"] == 1 and out["missing_ids"] == [1]
        assert out["duplicate_count"] == 0

    def test_duplicate(self):
        rows = [_row(0, 0.1), _row(0, 0.2), _row(1, 1.1)]
        out = missing_duplicate_committed(rows, GT)
        assert out["duplicate_count"] == 1 and out["missing_ids"] == []

    def test_empty(self):
        assert missing_duplicate_committed([], GT)["missing_count"] == 0


class TestOccurrenceJump:
    def test_jumps_detected(self):
        rows = [_row(0, 0.1, occurrence="a"), _row(1, 1.1, occurrence="b"),
                _row(2, 2.1, occurrence="a")]
        occ = {0: "a", 1: "c", 2: "a"}
        out = occurrence_jump_rate(rows, occ)
        assert out == {"jumps": 1, "total": 3, "jump_rate": 1 / 3}

    def test_gt_without_occurrence_counts_as_no_jump(self):
        rows = [_row(0, 0.1, occurrence="a"), _row(1, 1.1, occurrence="b")]
        out = occurrence_jump_rate(rows, {})
        assert out["jumps"] == 0 and out["total"] == 0 and out["jump_rate"] == 0.0


class TestCostSummary:
    def test_known(self):
        records = [
            {"request": {"model_bounds": (0.0, 0.0, 30.0, 60.0)}},
            {"request": {"model_bounds": (30.0, 30.0, 45.0, 60.0)}},
        ]
        out = cost_summary(records, forward_wall_sec=12.5)
        assert out == {"windows": 2, "forward_count": 2,
                       "audio_seconds": pytest.approx(90.0), "wall_sec": 12.5}

    def test_empty(self):
        out = cost_summary([], forward_wall_sec=None)
        assert out == {"windows": 0, "forward_count": 0,
                       "audio_seconds": 0.0, "wall_sec": None}


class TestEmptySafety:
    def test_all_functions_safe_on_empty(self):
        assert unit_accuracy([], {})["total"] == 0
        assert coverage_stats(0, 0)["coverage_rate"] == 0.0
        assert cursor_time_drift([])["final_drift_sec"] == 0.0
        assert first_error_window([], {}) is None
        assert missing_duplicate_committed([], {})["missing_count"] == 0
        assert occurrence_jump_rate([], {})["jump_rate"] == 0.0
        assert cost_summary([], None)["windows"] == 0


class TestMultiTolerance:
    def test_multi_tolerance_curve(self):
        from lyricalign.research_transition_recovery_detector.transition_metrics import (
            FORMAL_TOLERANCES_MS,
            multi_tolerance_accuracy,
        )

        rows = [_row(i, i * 1.0) for i in range(10)]  # start == id 秒
        gt = {i: {"start_sec": i * 1.0 + 0.05} for i in range(10)}  # 恒定 +50ms 偏差
        out = multi_tolerance_accuracy(rows, gt)
        assert out["correct_rate_100ms"] == 1.0   # 50ms <= 100ms
        assert out["correct_rate_250ms"] == 1.0
        assert out["correct_rate_500ms"] == 1.0
        assert out["correct_rate_1000ms"] == 1.0
        assert "legacy_320ms" in out
        assert len(FORMAL_TOLERANCES_MS) == 4

    def test_error_distribution(self):
        from lyricalign.research_transition_recovery_detector.transition_metrics import error_distribution

        rows = [_row(i, i * 1.0) for i in range(4)]
        gt = {i: {"start_sec": i * 1.0} for i in range(4)}
        d = error_distribution(rows, gt)
        assert d["n"] == 4
        assert d["median_sec"] == 0.0
        assert d["max_sec"] == 0.0
