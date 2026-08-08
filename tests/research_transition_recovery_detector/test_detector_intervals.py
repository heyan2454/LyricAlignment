"""detector intervalization 纯函数测试（09 §3 P4 必做项）。"""

import pytest

from lyricalign.research_transition_recovery_detector.detector_intervals import (
    build_intervals,
    interval_metrics,
)
from lyricalign.research_transition_recovery_detector.thresholds import (
    STATE_ACCEPT,
    STATE_REJECT,
    STATE_UNCERTAIN,
)


def test_build_intervals_contiguous_merge():
    states = [(0, STATE_ACCEPT), (1, STATE_ACCEPT), (2, STATE_REJECT), (3, STATE_REJECT),
              (4, STATE_ACCEPT)]
    ivs = build_intervals(states)
    assert len(ivs) == 3
    assert ivs[0] == {"state": STATE_ACCEPT, "start_id": 0, "end_id": 1, "n_units": 2}
    assert ivs[1] == {"state": STATE_REJECT, "start_id": 2, "end_id": 3, "n_units": 2}
    assert ivs[2] == {"state": STATE_ACCEPT, "start_id": 4, "end_id": 4, "n_units": 1}


def test_build_intervals_no_overlap_gap():
    """interval 拼接无 gap/overlap：覆盖 ids 0..4 恰好一次。"""
    states = [(0, STATE_ACCEPT), (2, STATE_REJECT), (4, STATE_UNCERTAIN)]
    ivs = build_intervals(states)
    covered = [cid for iv in ivs for cid in range(iv["start_id"], iv["end_id"] + 1)]
    assert covered == [0, 2, 4]  # 非连续 id 不合并
    assert len(ivs) == 3


def test_interval_metrics_full():
    # 0 ACCEPT(safe), 1-3 REJECT(全 unsafe → @75+@100), 4 UNCERTAIN(safe 分隔),
    # 5-8 REJECT(3 unsafe+1 safe=0.75 → @75 仅), 9-10 ACCEPT(unsafe run=2),
    # 11 UNCERTAIN(safe)
    states = [
        (0, STATE_ACCEPT), (1, STATE_REJECT), (2, STATE_REJECT), (3, STATE_REJECT),
        (4, STATE_UNCERTAIN),
        (5, STATE_REJECT), (6, STATE_REJECT), (7, STATE_REJECT), (8, STATE_REJECT),
        (9, STATE_ACCEPT), (10, STATE_ACCEPT), (11, STATE_UNCERTAIN),
    ]
    gt = {0: 0, 1: 1, 2: 1, 3: 1, 4: 0, 5: 1, 6: 1, 7: 1, 8: 0, 9: 1, 10: 1, 11: 0}
    m = interval_metrics(states, gt)
    # REJECT [1,3] 3/3 → @75+@100；REJECT [5,8] 3/4=0.75 → @75 仅
    assert m["unsafe_reject_interval_75"] == 2
    assert m["unsafe_reject_interval_100"] == 1
    # ACCEPT [9,10] 全 unsafe → longest unsafe ACCEPT run = 2
    assert m["longest_unsafe_accept_run"] == 2
    # 误杀：REJECT 区间 correct = id 8；UNCERTAIN 区间 correct = id 4 + id 11
    assert m["correct_unit_false_reject"] == 1
    assert m["correct_unit_false_uncertain"] == 2
    assert m["n_intervals"] == 6
