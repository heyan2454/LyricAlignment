# -*- coding: utf-8 -*-
"""cross-view posterior 采集管线测试（backlog #4）：converter 的
group_posteriors/keep_posterior 扩展 + features 端 fallback 兼容 dict 条目。"""
import pytest

from lyricalign.research_v7.detector_v2_evidence_converter import (
    POSTERIOR_REASON_CLASS_SPACE,
    POSTERIOR_REASON_INSUFFICIENT_VIEWS,
    POSTERIOR_REASON_TOPK_ONLY,
    convert_evidence,
)
from lyricalign.research_v7.detector_v2_features import _cross_view_features


def _evidence_json():
    return {
        "attempt": {
            "decoder_outputs": {
                "official": {"rows": [{"global_character_index": 0},
                                      {"global_character_index": 1}]},
                "_posterior": {"rows": []},
            }
        },
        "content_identity": "req-0",
    }


def _request_row(view_id="view_full"):
    return {"canonical_to_local": {"10": 0, "11": 1}, "view_id": view_id,
            "hidden_schema": None, "request_id": "req_full"}


def _groups(canonical_ids, view_ids):
    return [{"pair_id": "p0", "views": view_ids,
             "canonical_ids": [str(c) for c in canonical_ids]}]


def test_two_views_aligned_distance():
    gp = {"req_full": {10: {"start": [1.0, 0.0], "end": [0.0, 1.0]}},
          "req_overlap": {10: {"start": [0.0, 1.0], "end": [1.0, 0.0]}}}
    rows = convert_evidence(
        _evidence_json(), _request_row(),
        multiview_groups=_groups([10, 11], ["req_full", "req_overlap"]),
        group_posteriors=gp)
    cv = rows[0].cross_view
    assert cv["unit_covered_by"] == ["req_full", "req_overlap"]
    assert cv["posterior_distance"] is not None and cv["posterior_distance"] > 0
    assert cv["posterior_reason"] is None
    # 未覆盖 unit（11 只被一个 view 覆盖）→ 保持 None
    assert rows[1].cross_view["posterior_distance"] is None
    # 默认不落盘向量
    assert "posterior_vectors" not in cv


def test_keep_posterior_writes_vectors():
    gp = {"req_full": {10: {"start": [1.0, 0.0], "end": [0.0, 1.0]}},
          "req_overlap": {10: {"start": [0.0, 1.0], "end": [1.0, 0.0]}}}
    rows = convert_evidence(
        _evidence_json(), _request_row(),
        multiview_groups=_groups([10, 11], ["req_full", "req_overlap"]),
        group_posteriors=gp, keep_posterior=True)
    cv = rows[0].cross_view
    assert len(cv["posterior_vectors"]) == 2
    assert {v["view_id"] for v in cv["posterior_vectors"]} == {"req_full", "req_overlap"}
    # features fallback：直接消费 distance
    f = _cross_view_features(cv)
    assert f["cv_posterior_distance"] == pytest.approx(cv["posterior_distance"], abs=1e-9)


def test_topk_only_reason():
    gp = {"req_full": {10: {"start": [1.0, 0.0], "end": [0.0, 1.0]}}}
    rows = convert_evidence(
        _evidence_json(), _request_row(),
        multiview_groups=_groups([10, 11], ["req_full", "req_overlap"]),
        group_posteriors=gp)
    cv = rows[0].cross_view
    assert cv["posterior_distance"] is None
    assert cv["posterior_reason"] == POSTERIOR_REASON_TOPK_ONLY


def test_class_space_mismatch():
    gp = {"req_full": {10: {"start": [1.0, 0.0], "end": [0.0, 1.0]}},
          "req_overlap": {10: {"start": [0.0, 1.0, 0.0], "end": [1.0, 0.0, 0.0]}}}
    rows = convert_evidence(
        _evidence_json(), _request_row(),
        multiview_groups=_groups([10, 11], ["req_full", "req_overlap"]),
        group_posteriors=gp)
    assert rows[0].cross_view["posterior_reason"] == POSTERIOR_REASON_CLASS_SPACE


def test_insufficient_views_and_default_path():
    gp = {"req_full": {10: {"start": [1.0], "end": [0.0]}}}
    rows = convert_evidence(
        _evidence_json(), _request_row(),
        multiview_groups=_groups([10, 11], ["req_full", "req_overlap"]),
        group_posteriors=gp)
    # unit 10 被 2 请求覆盖但仅 1 个有全量后验 → topk_only
    assert rows[0].cross_view["posterior_reason"] == POSTERIOR_REASON_TOPK_ONLY
    # 不传 group_posteriors → 完全保持旧行为
    rows0 = convert_evidence(_evidence_json(), _request_row(),
                                 multiview_groups=_groups([10, 11], ["view_full", "view_overlap"]))
    assert rows0[0].cross_view.get("posterior_distance") is None
    assert "posterior_reason" not in rows0[0].cross_view


def test_features_fallback_dict_entries():
    # 双侧均值口径：start/end 取平均后算 pairwise L2（与 converter 一致）
    cv = {"n_views": 2,
          "posterior_vectors": [{"view_id": "a", "start": [1.0, 0.0], "end": [1.0, 0.0]},
                                {"view_id": "b", "start": [0.0, 1.0], "end": [0.0, 1.0]}]}
    f = _cross_view_features(cv)
    assert f["cv_posterior_distance"] == pytest.approx(1.41421356, abs=1e-3)
