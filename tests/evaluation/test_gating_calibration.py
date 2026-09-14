from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "gating_calibration_test", ROOT / "scripts" / "evaluation" / "gating_calibration_test.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _row(key: str, song: str, pred_dur: float, entropy: float, defect: bool, gt_dur: float = 1.0):
    return {"key": key, "song": song, "pred_dur": pred_dur, "entropy": entropy,
            "gt_dur": gt_dur, "defect": defect}


def _population() -> list[dict]:
    """风险与熵都随预测时长上升的人群——正是今晚真数据的形状。"""
    rows = []
    for song in ("A#s1", "B#s2", "C#s3", "D#s4"):
        # 桶内：熵越高越可能是缺陷（真实数据就是这个形状）；跨桶：长字符整体更不确信也更常错
        for index in range(50):
            rows.append(_row(f"{song}|short|{index}", song, 0.3, 0.2 + index / 500, defect=index >= 49))
        for index in range(50):
            rows.append(_row(f"{song}|long|{index}", song, 2.4, 1.8 + index / 500, defect=index >= 30))
    return rows


def test_global_threshold_beats_within_bin_normalisation_when_risk_rises_with_duration():
    rows = _population()
    budget = 0.20
    total_defects = sum(1 for row in rows if row["defect"])
    gflags = MODULE.global_flags(rows, training=rows, budget=budget)
    cflags = MODULE.conditional_flags(rows, training=rows, budget=budget)
    g_capture = MODULE._summarise(rows, gflags, total_defects=total_defects)["capture_share"]
    c_capture = MODULE._summarise(rows, cflags, total_defects=total_defects)["capture_share"]
    assert g_capture > c_capture, (g_capture, c_capture)   # 今晚的负结果，作为性质固定下来


def test_conditional_flags_never_look_at_ground_truth_duration():
    rows = _population()
    shuffled_gt = [_row(row["key"], row["song"], row["pred_dur"], row["entropy"], row["defect"],
                        gt_dur=9.9 - index / 10) for index, row in enumerate(rows)]
    flags_a = MODULE.conditional_flags(rows, training=rows, budget=0.1)
    flags_b = MODULE.conditional_flags(shuffled_gt, training=shuffled_gt, budget=0.1)
    assert flags_a == flags_b, "分档阈值只许用预测时长，真值时长参与即为 oracle"


def test_sparse_bins_fall_back_to_the_global_cut():
    rows = [_row(f"k{index}", "A#s1", 6.0, 0.1 * index, defect=False) for index in range(10)]
    rows += [_row(f"s{index}", "B#s2", 0.3, 0.2 + index / 1000, defect=False) for index in range(60)]
    training = rows
    cuts_global = MODULE.quantile([row["entropy"] for row in training], 0.9)
    flags = MODULE.conditional_flags(rows, training=training, budget=0.1)
    rare = [row for row in rows if MODULE.pred_bin(row["pred_dur"]) == "2s+"]
    assert rare and all(flags[row["key"]] == (row["entropy"] >= cuts_global) for row in rare)


def test_pred_bin_and_quantile_edges():
    assert MODULE.pred_bin(0.1) == "0-0.25s" and MODULE.pred_bin(0.3) == "0.25-0.5s"
    assert MODULE.pred_bin(1.5) == "1-2s" and MODULE.pred_bin(9.0) == "2s+"
    assert MODULE.quantile([], 0.9) == float("inf")
    assert MODULE.quantile([0.1, 0.2, 0.3], 0.0) == 0.1
    assert MODULE.quantile([0.1, 0.2, 0.3], 1.0) == 0.3


def test_evaluation_reports_insufficient_songs_instead_of_inventing_a_result():
    rows = [_row("only|1", "One#song", 0.5, 0.3, defect=False)] * 40
    assert MODULE.evaluate(rows) == {"status": "insufficient_songs", "songs": 1}
