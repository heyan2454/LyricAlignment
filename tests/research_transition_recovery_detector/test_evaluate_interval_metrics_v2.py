"""interval evaluator v2 修复测试（二次补充 Stage F）。

验证：
1. Grey(1) 不计入 unsafe denominator；
2. 两首歌 canonical_id 连续不合并；
3. REJECT-only 与 protected 数值不同；
4. build_intervals_by_song 逐歌构造。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from lyricalign.research_transition_recovery_detector.detector_intervals import (
    build_intervals,
    build_intervals_by_song,
)
from lyricalign.research_transition_recovery_detector.thresholds import (
    STATE_ACCEPT,
    STATE_REJECT,
    STATE_UNCERTAIN,
)

REPO = Path(__file__).resolve().parents[2]
EVAL_SCRIPT = REPO / "scripts" / "research_transition_recovery_detector" / "evaluate_interval_metrics_v2.py"


def test_grey_not_in_unsafe_denominator():
    """Grey(1) 不入 unsafe 分母；unsafe recall 只基于 label==2。"""
    p_bad = [0.1, 0.9, 0.9, 0.9]
    labels = [0, 1, 2, 2]  # safe / grey / unsafe / unsafe
    wps = {"R95": {"t_accept": 0.0, "t_reject": 0.5}}
    eval_path = Path("/tmp/opencode/eval_grey.json")
    th_path = Path("/tmp/opencode/th_grey.json")
    out_path = Path("/tmp/opencode/interval_grey.json")
    eval_path.write_text(json.dumps({"p_bad": p_bad, "labels": labels,
                                     "song_ids": ["a", "a", "a", "a"],
                                     "canonical_ids": [0, 1, 2, 3]}))
    th_path.write_text(json.dumps({"working_points_v3_format": wps}))
    cp = subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), "--session-root", str(REPO),
         "--eval", str(eval_path), "--thresholds", str(th_path),
         "--out", str(out_path), "--role", "threshold_validation"],
        capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stderr[-500:]
    res = json.loads(out_path.read_text())["working_points"]["R95"]
    # 只有 label==2 是 unsafe：n_unsafe=2（unit 2,3）；grey(unit1) 不计入
    assert res["C3"]["n_unsafe"] == 2
    assert res["C3"]["n_grey_excluded"] == 1
    # unit2,3 都是 REJECT（p_bad=0.9>=0.5）-> unsafe reject recall = 1.0
    assert res["C3"]["unsafe_reject"] == 1.0


def test_two_songs_canonical_contiguous_not_merged():
    """两首歌 canonical 连续（A 末 2、B 首 3）不得合并成一个 interval。"""
    rows = [
        {"song_id": "songA", "canonical_id": 0, "state": STATE_REJECT},
        {"song_id": "songA", "canonical_id": 1, "state": STATE_REJECT},
        {"song_id": "songA", "canonical_id": 2, "state": STATE_REJECT},
        {"song_id": "songB", "canonical_id": 3, "state": STATE_REJECT},
    ]
    intervals = build_intervals_by_song(rows)
    # 每歌独立 interval，不合并
    assert len(intervals) == 2
    assert intervals[0]["song_id"] == "songA"
    assert intervals[1]["song_id"] == "songB"
    assert intervals[0]["start_id"] == 0 and intervals[0]["end_id"] == 2
    assert intervals[1]["start_id"] == 3 and intervals[1]["end_id"] == 3
    # 对比单歌 build_intervals（会合并成 1 个）
    single = build_intervals([(0, STATE_REJECT), (1, STATE_REJECT), (2, STATE_REJECT), (3, STATE_REJECT)])
    assert len(single) == 1


def test_reject_only_vs_protected_differs():
    """REJECT-only 与 protected(REJECT+UNCERTAIN) 数值不同。"""
    p_bad = [0.9, 0.4, 0.4, 0.9]  # REJECT, UNCERTAIN, UNCERTAIN, REJECT
    labels = [2, 2, 2, 2]  # 全 unsafe
    wps = {"R95": {"t_accept": 0.0, "t_reject": 0.5}}
    eval_path = Path("/tmp/opencode/eval_prot.json")
    th_path = Path("/tmp/opencode/th_prot.json")
    out_path = Path("/tmp/opencode/interval_prot.json")
    eval_path.write_text(json.dumps({"p_bad": p_bad, "labels": labels,
                                     "song_ids": ["a", "a", "a", "a"],
                                     "canonical_ids": [0, 1, 2, 3]}))
    th_path.write_text(json.dumps({"working_points_v3_format": wps}))
    cp = subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), "--session-root", str(REPO),
         "--eval", str(eval_path), "--thresholds", str(th_path),
         "--out", str(out_path), "--role", "threshold_validation"],
        capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stderr[-500:]
    res = json.loads(out_path.read_text())["working_points"]["R95"]
    reject_only = res["C1"]["unit_unsafe_recall_reject_only"]
    protected = res["C1"]["unit_unsafe_recall_reject_plus_uncertain"]
    assert reject_only == 0.5  # 2/4 REJECT
    assert protected == 1.0  # 4/4 REJECT+UNCERTAIN
    assert reject_only != protected


def test_multisong_label_position_mapping():
    """多歌 interval：canonical_id 与扁平 labels position 正确映射（P1-1 修复）。"""
    # songA: canonical 0,1（全 REJECT）；songB: canonical 0,1（全 ACCEPT）
    # 扁平 position: [A0, A1, B0, B1]
    # labels: A0=safe, A1=unsafe, B0=unsafe, B1=safe
    p_bad = [0.9, 0.9, 0.1, 0.1]
    labels = [0, 2, 2, 0]
    wps = {"R95": {"t_accept": 0.0, "t_reject": 0.5}}
    eval_path = Path("/tmp/opencode/eval_multi.json")
    th_path = Path("/tmp/opencode/th_multi.json")
    out_path = Path("/tmp/opencode/interval_multi.json")
    eval_path.write_text(json.dumps({"p_bad": p_bad, "labels": labels,
                                     "song_ids": ["songA", "songA", "songB", "songB"],
                                     "canonical_ids": [0, 1, 0, 1]}))
    th_path.write_text(json.dumps({"working_points_v3_format": wps}))
    cp = subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), "--session-root", str(REPO),
         "--eval", str(eval_path), "--thresholds", str(th_path),
         "--out", str(out_path), "--role", "threshold_validation"],
        capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stderr[-500:]
    res = json.loads(out_path.read_text())["working_points"]["R95"]
    # songA: [A0 REJECT, A1 REJECT] -> 1 interval；songB: [B0 ACCEPT, B1 ACCEPT] -> 1 interval
    assert res["n_intervals"] == 2
    # unsafe 在 A1（position 1, REJECT）和 B0（position 2, ACCEPT）
    assert res["C1"]["unit_unsafe_recall_reject_only"] == 0.5
    # intervals_with_unsafe：A interval（含 A1）和 B interval（含 B0）= 2
    assert res["C1"]["reject_only"]["intervals_with_unsafe"] == 2
