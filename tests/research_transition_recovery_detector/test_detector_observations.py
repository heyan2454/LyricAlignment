"""committed-observation binding 单测（二次补充 Stage A/B1-B3）。"""
from __future__ import annotations

import json

from lyricalign.research_transition_recovery_detector.detector_observations import (
    committed_observation_index,
    label_from_row,
)


def _rec(request_id, before, after, rows):
    return {
        "request": {"request_id": request_id},
        "state_before": {"committed_end_exclusive": before},
        "decision": {"committed_end_exclusive": after},
        "window_index": int(request_id[-3:]),
        "evidence_summary": {"raw_global_rows": rows},
    }


def _row(cid, start):
    return {"global_character_index": cid, "original_global_start_sec": start,
            "fixed_global_start_sec": start}


def test_committed_binding_overlap_not_override():
    """overlap 中后 view 不得覆盖 committed view。"""
    # request A commit unit 0-4；request B 是 overlap，重新观测 unit 2-4（时间不同）
    rec_a = _rec("req_a__w000", 0, 5, [_row(i, i * 1.0) for i in range(5)])
    rec_b = _rec("req_b__w001", 0, 5, [_row(i, i * 1.0 + 3.0) for i in range(5)])  # 全部 shift +3
    idx = committed_observation_index([rec_a, rec_b], song_id="s")
    # unit 2 的 committed request 是 req_a（第一个 commit 的）
    assert idx.committed_request[2] == "req_a__w000"
    # primary row 必须来自 committed request（start=2.0，不是 req_b 的 5.0）
    row = idx.primary_row(2)
    assert row["original_global_start_sec"] == 2.0
    # all_observations 保留两个 view
    assert len(idx.observations(2)) == 2


def test_recommit_after_first_commit_mismatch():
    """同 unit 被第二次 commit 记为 mismatch。"""
    rec_a = _rec("req_a__w000", 0, 3, [_row(i, i * 1.0) for i in range(5)])
    rec_b = _rec("req_b__w001", 2, 5, [_row(i, i * 1.0) for i in range(5)])  # 重新 commit 2-4
    idx = committed_observation_index([rec_a, rec_b], song_id="s")
    reasons = [m["reason"] for m in idx.mismatch_log]
    assert "recommit_after_first_commit" in reasons
    assert idx.committed_request[2] == "req_a__w000"  # 首次 commit 保持


def test_labels_match_authoritative_transition():
    """三态标签与 authoritative Transition 口径一致。"""
    gt = {i: {"start_sec": i * 1.0} for i in range(3)}
    # unit0: err=0.05 safe；unit1: err=0.15 grey；unit2: err=0.5 unsafe
    rec = _rec("req__w000", 0, 3, [_row(0, 0.05), _row(1, 1.15), _row(2, 0.5)])
    idx = committed_observation_index([rec], song_id="s")
    labels = [label_from_row(idx.primary_row(c), gt, safe_ms=0.1, grey_ms=0.25)
              for c in range(3)]
    assert labels == [0, 1, 2]  # safe / grey / unsafe
