# -*- coding: utf-8 -*-
"""WP5 features / region_metrics 单测。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.features import feature_extractor_blocked, gap_features, unit_features
from lyricalign.research_v7.region_metrics import (
    gap_metrics,
    interval_recall,
    summarize_by_split,
    unit_metrics,
)


def _row(start=0.5, end=0.9, **kw):
    base = {
        "raw_start_sec": start, "raw_end_sec": end,
        "raw_global_start_sec": start, "raw_global_end_sec": end,
        "official_fixed_global_start_sec": start - 0.01, "official_fixed_global_end_sec": end + 0.01,
        "raw_start_margin": 0.2, "raw_end_margin": 0.3, "raw_start_entropy": 0.1, "raw_end_entropy": 0.2,
    }
    base.update(kw)
    return base


def test_unit_features_raw_official():
    f = unit_features(_row(0.5, 0.9))
    assert abs(f["raw_duration_sec"] - 0.4) < 1e-9
    assert "official_duration_sec" in f and "ro_official_minus_raw_sec" in f


def test_unit_features_inverted_zero():
    assert unit_features(_row(0.9, 0.5))["raw_inverted"] == 1.0
    assert unit_features(_row(0.5, 0.5))["raw_zero"] == 1.0


def test_gap_features_left_right():
    g = gap_features(_row(0.0, 0.5), _row(0.8, 1.2))
    assert "left_raw_duration_sec" in g and "right_raw_duration_sec" in g
    assert abs(g["raw_start_jump_sec"] - 0.3) < 1e-6


def test_feature_extractor_rejects_gt_fields():
    res = feature_extractor_blocked({"positive": True, "omitted_canonical_unit_ids": [1]})
    assert res["ok"] is False  # 发现泄漏


def test_unit_metrics_recall_fpr():
    m = unit_metrics(total_gt_units=10, unsafe_pred_units=[1, 2, 9], truly_unsafe_indices={1, 3, 9},
                     correct_retained_units=8, total_retained_gt=8)
    assert m["unit_recall"] == round(2 / 3, 4)
    assert m["correct_unit_fpr"] == round(1 / 8, 4)  # index2 是 fp


def test_gap_metrics_recall():
    # omitted-units 加权：gap 10 命中(omitted=[30,31]); gap 20 未命中(omitted=[40])
    g = gap_metrics(gt_gaps=[10, 20], pred_gap_ids=[10, 30],
                    gt_gap_omitted={10: [30, 31], 20: [40]})
    assert g["gap_event_recall"] == 0.5
    # omitted units: gt=[30,31,40], 命中与检出的=gap10→[30,31] 命中 2/3
    assert abs(g["gap_omitted_unit_weighted_recall"] - round(2 / 3, 4)) < 1e-9


def test_interval_recall_at():
    r = interval_recall([{1, 2, 3}, {5, 6}], pred_cover={1, 2}, cover_frac=0.66)
    # 第一段 {1,2,3} 覆盖 2/3>=0.66 hit；第二段 {5,6} 覆盖 0
    assert r == 0.5


def test_summarize_by_split():
    per = [
        {"split": "train", "domain": "m4", "mutation_family": "extra", "unit_recall": 1.0, "fpr": 0.1, "gap_recall": 0.5},
        {"split": "train", "domain": "m4", "mutation_family": "extra", "unit_recall": 0.5, "fpr": 0.2, "gap_recall": 0.0},
    ]
    out = summarize_by_split(per)
    k = "train|m4|extra"
    assert k in out
    assert out[k]["unit_recall_mean"] == 0.75
    assert out[k]["n_items"] == 2


def test_wrong_output_two_directions_independent():
    from lyricalign.research_v7.region_metrics import wrong_output_metrics
    m = wrong_output_metrics(gt_replaced=10, wrong_output_hits=6, replaced_omission_hits=3, replaced_omission_gt=9)
    assert m["wrong_output_recall"] == round(6 / 10, 4)
    assert m["replaced_gt_omission_recall"] == round(3 / 9, 4)


def test_region_metrics_docstring_claims_only_implemented():
    # review17-minor：docstring 只宣称已实现指标，不得再提未实现的
    # interval recall@75/100、>=3-unit 全漏检率、unsafe 扩张长度
    import lyricalign.research_v7.region_metrics as rm
    doc = " ".join(rm.__doc__.split())  # 折叠换行（docstring 跨行换行不破坏断言）
    for unreal in ("interval recall@75/100", ">=3-unit 全漏检率", "unsafe 扩张长度", "deleted-GT weighted"):
        assert unreal not in doc
    for real in ("unit recall", "correct-retained-unit FPR", "gap event recall",
                 "gap omitted-unit weighted recall", "wrong-output recall",
                 "replaced-GT omission recall", "interval recall"):
        assert real in doc
    # 已实现函数确实存在（防 docstring 与实现再次脱节）
    for fn in ("unit_metrics", "gap_metrics", "wrong_output_metrics", "interval_recall", "summarize_by_split"):
        assert callable(getattr(rm, fn))


def test_gap_metrics_no_dead_params():
    from lyricalign.research_v7.region_metrics import gap_metrics
    # 不再接受 pred_gap_omitted/weighted_deleted_gt（死参数已移除）
    import inspect
    sig = inspect.signature(gap_metrics)
    assert "pred_gap_omitted" not in sig.parameters
    assert "weighted_deleted_gt" not in sig.parameters


def test_unit_features_real_executor_fixed_global_rows():
    from lyricalign.research_v7.features import unit_features
    # real executor 行：只用 fixed_global_start/end + raw（无 official_fixed_*）
    row = {"raw_global_start_sec": 0.5, "raw_global_end_sec": 0.9,
           "fixed_global_start_sec": 0.4, "fixed_global_end_sec": 1.0,
           "start_sec": 99.0}  # start_sec 是噪声，官向必须用 fixed_global，不得退回
    f = unit_features(row)
    assert f["official_duration_sec"] == round(0.6, 6)  # 1.0-0.4，非 99
    assert f["official_missing_geometry"] == 0.0


def test_unit_features_missing_official_marks_missing():
    from lyricalign.research_v7.features import unit_features
    row = {"raw_global_start_sec": 0.5, "raw_global_end_sec": 0.9}  # 无任何 official 几何
    f = unit_features(row)
    assert f["official_missing_geometry"] == 1.0
    assert f["official_duration_sec"] is None  # 不悄悄退回 start_sec
