"""10_FOLLOWUP Task B：retry 驱动 closed-loop writeback（v3）fixture 测试（无 GPU）。

覆盖（10_FOLLOWUP_IMPLEMENTATION_PLAN.md §2 Task B）：
1. 同一 initial plan、不同 retry rows -> writeback state、next request、final committed times 不同；
2. retry 无改善（retry rows 全 unsafe）时不得虚报 recovery 或提交（无 retry-derived 写回，
   Gate C ② 失败）；
3. L/W 的 retry audio（query 覆盖区间）/query/writeback 有可观察差异；
4. Gate C 双条件：① 写回改变后续 state/request；② 写回含至少一个 retry-derived row；
5. retry provenance（source: serial|retry, window, request_id）字段存在且正确；
6. baseline serial（retry_enabled=False）不触发 retry forward、无 retry-derived 写回。

执行阶段 GT 不泄漏进 backend（仅最终评估消费 GT）。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from research_transition_recovery_detector.run_closed_loop_v3 import (  # noqa: E402
    build_retry_writeback_plan,
    run_closed_loop_v3_song,
)
from research_transition_recovery_detector.run_closed_loop import (  # noqa: E402
    RecordingAlignerBackend,
)
from lyricalign.research_transition_recovery_detector.contracts import (  # noqa: E402
    ROUTE_LOCAL,
    ROUTE_SHADOW,
    ROUTE_WHOLE,
    TRANSITION_T2_CORE,
)
from lyricalign.research_transition_recovery_detector.query_estimator import (  # noqa: E402
    QueryEstimator,
)
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    FakeAlignerBackend,
)

N_UNITS = 13
DURATION = 130.0
SR = 16000
SEC_PER_UNIT = 1.2
FROZEN_WP = {"t_accept": 0.5, "t_reject": 0.9}
ALL_ACCEPT = 0.1
BAD = 0.95

# 初始窗 serial p_bad：id0 ACCEPT，id1/2 REJECT -> L: commit [0], gap (1,3)；W: whole reject
SERIAL_W0 = [ALL_ACCEPT, BAD, BAD, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT]
RETRY_IMPROVE = [ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT]  # L retry rows: ids [0,1,2]
RETRY_FAIL = [ALL_ACCEPT, BAD, BAD]


class _Doc:
    characters = [f"c{i}" for i in range(N_UNITS)]


def _make_gt() -> dict:
    return {
        i: {"canonical_unit_id": i, "text": f"c{i}", "start_sec": float(i * SEC_PER_UNIT)}
        for i in range(N_UNITS)
    }


def _make_window_plan() -> dict:
    return {"windows": [
        {"window_index": 0, "core_start_sec": 0.0, "core_end_sec": 60.0,
         "input_start_sec": 0.0, "input_end_sec": 70.0},
        {"window_index": 1, "core_start_sec": 60.0, "core_end_sec": 130.0,
         "input_start_sec": 50.0, "input_end_sec": 130.0},
    ]}


def _make_estimator() -> QueryEstimator:
    return QueryEstimator(n_units=N_UNITS, effective_audio_sec=DURATION)


class _PBadInjector:
    """显式 p_bad 队列 + 兜底全 ACCEPT（覆盖未知长度的后续窗 rows）。"""

    def __init__(self, queue):
        self.queue = list(queue)
        self.n_serial_calls = 0
        self.n_retry_calls = 0

    def __call__(self, rows):
        if self.queue:
            item = list(self.queue.pop(0))
            if len(item) < len(rows):
                item = item + [ALL_ACCEPT] * (len(rows) - len(item))
            return item[:len(rows)]
        return [ALL_ACCEPT] * len(rows)


def _run(
    *,
    route_mode: str,
    p_bad_queue: list[list[float]],
    backend=None,
    retry_enabled: bool = True,
) -> tuple[dict, object, _PBadInjector]:
    injector = _PBadInjector(p_bad_queue)
    backend = backend or RecordingAlignerBackend(FakeAlignerBackend(sec_per_unit=SEC_PER_UNIT))
    out = run_closed_loop_v3_song(
        song_id="song-a",
        audio=np.zeros(int(DURATION * SR), dtype=np.float32),
        document=_Doc(),
        gt=_make_gt(),
        window_plan=_make_window_plan(),
        estimator=_make_estimator(),
        backend=backend,
        transition=TRANSITION_T2_CORE,
        frozen_wp=FROZEN_WP,
        route_mode=route_mode,
        detector_predict=injector,
        retry_enabled=retry_enabled,
    )
    return out, backend, injector


def test_same_initial_plan_different_retry_rows_differs():
    """同一 initial plan（同 serial p_bad），不同 retry rows -> writeback state / next request /
    final committed times 全部不同。"""
    out_a, _, _ = _run(route_mode="L", p_bad_queue=[
        list(SERIAL_W0), list(RETRY_IMPROVE),  # retry 全 ACCEPT -> gap 解决
    ])
    out_b, _, _ = _run(route_mode="L", p_bad_queue=[
        list(SERIAL_W0), list(RETRY_FAIL),  # retry 仍 unsafe -> 无 retry 写回
    ])
    w0a, w0b = out_a["windows"][0], out_b["windows"][0]
    assert w0a["plan"] == w0b["plan"]  # 同一 initial RoutePlan
    assert w0a["retry"]["request_id"] == w0b["retry"]["request_id"]
    assert w0a["retry"]["query_ids"] == w0b["retry"]["query_ids"]  # 同一 retry 请求
    # writeback state 不同
    assert w0a["writeback"]["state_hash_after"] != w0b["writeback"]["state_hash_after"]
    assert w0a["writeback"]["committed_this_window"] != w0b["writeback"]["committed_this_window"]
    assert w0a["retry_writeback"]["commit_ids"] == [1, 2]
    assert w0b["retry_writeback"]["commit_ids"] == []
    assert w0a["retry_writeback"]["unresolved_gap_after"] is None
    assert w0b["retry_writeback"]["unresolved_gap_after"] == [1, 3]
    # next request 不同（A 从 id3 出发，B 从 id1 出发）
    assert w0a["writeback"]["gate_c"]["next_request_changed"] is True
    assert w0a["writeback"]["gate_c"]["next_request_changed"] == \
        w0b["writeback"]["gate_c"]["next_request_changed"]
    # next request 分叉体现在 committed 轨迹（lookback 使 query 起点都回看 0）
    assert out_a["windows"][1]["committed_this_window"] != out_b["windows"][1]["committed_this_window"]
    # final committed times 不同：A 含 retry-derived id1/2 times（全轨迹写回累积）
    assert out_a["committed_provenance"]["1"]["source"] == "retry"
    assert out_b["committed_provenance"].get("1", {}).get("source") == "serial"
    assert out_a["committed_times"]["1"] == 1.0 * SEC_PER_UNIT  # 来自 retry row


def test_retry_no_improvement_no_false_recovery():
    """retry rows 全 unsafe -> 无新增写回、不得虚报 recovery（无 retry-derived commit），
    Gate C ② 失败；unresolved 保持，不提交 gap 内单位。"""
    out, _, injector = _run(route_mode="L", p_bad_queue=[
        list(SERIAL_W0), list(RETRY_FAIL),
    ])
    w0 = out["windows"][0]
    assert w0["plan"]["route"] == ROUTE_LOCAL
    assert w0["plan"]["commit_ids"] == [0]
    assert w0["retry_writeback"]["evidence"] is True
    assert w0["retry_writeback"]["commit_ids"] == []  # 无 retry-derived 写回
    assert w0["retry_writeback"]["unresolved_gap_after"] == [1, 3]  # gap 未解决
    assert w0["writeback"]["n_retry_derived"] == 0
    assert w0["writeback"]["committed_this_window"] == [0]  # 仅 serial prefix
    # 不得虚报 recovery：Gate C ② 失败（无 retry-derived row）
    assert w0["writeback"]["gate_c"]["retry_derived_ok"] is False
    assert w0["writeback"]["gate_c"]["ok"] is False
    assert out["gate_c"]["passed"] is False
    assert out["gate_c"]["failures"][0]["retry_derived_ok"] is False
    # final committed 只有 serial 写回的 id0（id1/2 未提交，后续窗全 ACCEPT 也应提交）
    assert "0" in out["committed_times"]
    assert out["committed_provenance"]["0"]["source"] == "serial"  # 无 retry-derived 写回
    # retry rows 确实再入了 detector：retry_writeback evidence 已证明（脚本对 retry rows 调 detector）
    assert w0["retry_writeback"]["evidence"] is True


def test_l_w_retry_audio_query_writeback_distinct():
    """L/W 的 retry audio（query 覆盖区间）/query/writeback 有可观察差异。"""
    out_l, _, _ = _run(route_mode="L", p_bad_queue=[
        list(SERIAL_W0), list(RETRY_IMPROVE),
    ])
    out_w, _, _ = _run(route_mode="W", p_bad_queue=[
        list(SERIAL_W0), [ALL_ACCEPT] * 7,  # W retry 重跑整窗 7 ids
    ])
    w0l, w0w = out_l["windows"][0], out_w["windows"][0]
    assert w0l["plan"]["route"] == ROUTE_LOCAL and w0w["plan"]["route"] == ROUTE_WHOLE
    # retry query 不同：L 只覆盖 gap(+左回看)，W 重跑整窗
    assert w0l["retry"]["query_ids"] == [0, 1, 2]
    assert w0w["retry"]["query_ids"] == list(range(7))
    assert w0l["retry"]["query_ids"] != w0w["retry"]["query_ids"]
    # retry audio 可观察差异：query 覆盖音频区间不同（L 0..3.6s，W 0..8.4s）
    assert w0l["retry"]["query_audio_span_sec"] == [0.0, 30.0]  # L gap 3 行 × spu=10
    assert w0w["retry"]["query_audio_span_sec"] == [0.0, 70.0]  # W 整窗 7 行 × spu=10
    assert w0l["retry"]["query_audio_span_sec"] != w0w["retry"]["query_audio_span_sec"]
    # writeback 不同：L 为 serial[0] + retry[1,2]；W 全部来自 retry[0..6]
    assert w0l["writeback"]["committed_this_window"] == [0, 1, 2]
    assert w0w["writeback"]["committed_this_window"] == list(range(7))
    assert w0l["writeback"]["n_serial_derived"] == 1 and w0l["writeback"]["n_retry_derived"] == 2
    assert w0w["writeback"]["n_serial_derived"] == 0 and w0w["writeback"]["n_retry_derived"] == 7
    assert w0l["writeback"]["state_hash_after"] != w0w["writeback"]["state_hash_after"]
    assert w0l["retry"]["request_id"] == w0w["retry"]["request_id"]  # 同一窗 retry id 格式
    # provenance 可观察差异：L 混合 serial+retry；W 全 retry
    prov_l = {p["source"] for cid, p in out_l["committed_provenance"].items() if int(cid) < 3}
    prov_w = {p["source"] for cid, p in out_w["committed_provenance"].items() if int(cid) < 3}
    assert prov_l == {"serial", "retry"}
    assert prov_w == {"retry"}


def test_gate_c_dual_conditions():
    """Gate C 双条件：①写回改变后续 state/request；②写回含 >=1 retry-derived row。"""
    # 双条件均满足 -> pass
    out_ok, _, _ = _run(route_mode="L", p_bad_queue=[
        list(SERIAL_W0), list(RETRY_IMPROVE),
    ])
    w_ok = out_ok["windows"][0]
    assert w_ok["writeback"]["gate_c"]["ok"] is True
    assert w_ok["writeback"]["gate_c"]["state_changed"] is True
    assert w_ok["writeback"]["gate_c"]["next_request_changed"] is True
    assert w_ok["writeback"]["gate_c"]["retry_derived_required"] is True
    assert w_ok["writeback"]["gate_c"]["retry_derived_ok"] is True
    assert out_ok["gate_c"]["passed"] is True

    # ②失败：retry 执行了但无 retry-derived row -> gate fail（①仍满足）
    out_c2, _, _ = _run(route_mode="L", p_bad_queue=[
        list(SERIAL_W0), list(RETRY_FAIL),
    ])
    w_c2 = out_c2["windows"][0]
    assert w_c2["writeback"]["gate_c"]["state_changed"] is True  # ① serial prefix 写回
    assert w_c2["writeback"]["gate_c"]["retry_derived_ok"] is False  # ② 失败
    assert w_c2["writeback"]["gate_c"]["ok"] is False
    assert out_c2["gate_c"]["passed"] is False

    # ①失败：shadow 不写回 -> gate fail（② vacuous pass）
    out_c1, _, _ = _run(route_mode="shadow", p_bad_queue=[
        list(SERIAL_W0), [ALL_ACCEPT] * 3,
    ])
    w_c1 = out_c1["windows"][0]
    assert w_c1["plan"]["route"] == ROUTE_SHADOW
    assert w_c1["writeback"]["actual_writeback"] == 0
    assert w_c1["writeback"]["gate_c"]["state_changed"] is False
    assert w_c1["writeback"]["gate_c"]["retry_derived_required"] is False
    assert w_c1["writeback"]["gate_c"]["retry_derived_ok"] is True  # vacuous
    assert w_c1["writeback"]["gate_c"]["ok"] is False
    assert out_c1["gate_c"]["passed"] is False

    # 无 retry 窗（全 ACCEPT）：①满足 + ② vacuous -> pass
    out_no_retry, _, _ = _run(route_mode="L", p_bad_queue=[
        [ALL_ACCEPT] * 7,
    ])
    w_nr = out_no_retry["windows"][0]
    assert w_nr["plan"]["route"] == "none"
    assert w_nr["writeback"]["gate_c"]["retry_derived_required"] is False
    assert w_nr["writeback"]["gate_c"]["ok"] is True


def test_retry_provenance_fields():
    """row provenance（source: serial|retry, window, request_id）存在且正确。"""
    out, _, _ = _run(route_mode="L", p_bad_queue=[
        list(SERIAL_W0), list(RETRY_IMPROVE),
    ])
    w0 = out["windows"][0]
    prov = out["committed_provenance"]
    assert "0" in prov and "1" in prov and "2" in prov
    assert prov["0"] == {"source": "serial", "window": 0, "request_id": w0["request_id"]}
    assert prov["1"] == {"source": "retry", "window": 0, "request_id": w0["retry"]["request_id"]}
    assert prov["2"]["source"] == "retry"
    assert prov["2"]["window"] == 0
    assert prov["2"]["request_id"] == w0["retry"]["request_id"]
    # committed timestamps 来自实际写回的 row
    assert out["committed_times"]["0"] == 0.0  # serial row
    assert out["committed_times"]["1"] == 1.0 * SEC_PER_UNIT  # retry row
    assert out["committed_times"]["2"] == 2.0 * SEC_PER_UNIT
    # 歌曲级 retry provenance 汇总
    assert out["retry_provenance"]["n_retry_derived_commits"] == 2
    assert out["retry_provenance"]["n_windows_with_retry"] == 1
    assert out["retry_provenance"]["retry_request_ids"] == [w0["retry"]["request_id"]]
    # 后续窗无 retry，provenance 为 serial
    w1 = out["windows"][1]
    assert w1["plan"]["route"] == "none"
    assert prov["3"]["source"] == "serial"
    assert prov["3"]["window"] == 1


def test_baseline_serial_no_retry():
    """baseline serial（retry_enabled=False）：无 retry forward、无 retry-derived 写回。"""
    out, backend, injector = _run(route_mode="L", p_bad_queue=[
        list(SERIAL_W0),  # 后续窗兜底全 ACCEPT
    ], retry_enabled=False)
    w0 = out["windows"][0]
    assert w0["plan"]["route"] == ROUTE_LOCAL
    assert w0["retry"]["executed_forward_count"] == 0
    assert w0["retry"]["n_rows"] == 0
    assert w0["retry_writeback"]["evidence"] is False
    assert w0["retry_writeback"]["commit_ids"] == []
    assert w0["writeback"]["n_retry_derived"] == 0
    assert w0["writeback"]["committed_this_window"] == [0]  # 仅 serial prefix
    assert out["totals"]["extra_forward_count"] == 0
    assert out["retry_provenance"]["n_retry_derived_commits"] == 0
    assert out["retry_provenance"]["n_windows_with_retry"] == 0
    # 每 committed id 的 provenance 全为 serial
    assert all(p["source"] == "serial" for p in out["committed_provenance"].values())
    assert w0["plan"]["unresolved_gap"] == [1, 3]  # L 路由 gap 正确识别


def test_build_retry_writeback_plan_never_crosses_gap():
    """retry plan 只从 gap 起连续提交，不跨 gap 内非 ACCEPT（直接单测纯函数）。"""
    from lyricalign.research_transition_recovery_detector.contracts import RoutePlan

    plan = RoutePlan(
        route=ROUTE_LOCAL, window_id="w000",
        commit_ids=(0,), unresolved_gap=(1, 4), retry_request=None,
    )
    rows = [
        {"global_character_index": 0},
        {"global_character_index": 1},
        {"global_character_index": 2},
        {"global_character_index": 3},
    ]
    commits, gap, evidence = build_retry_writeback_plan(
        plan=plan, retry_rows=rows,
        retry_p_bad=[0.1, 0.1, 0.95, 0.1],  # id2 仍 REJECT，id3 ACCEPT 也不得提交
        frozen_wp=FROZEN_WP, base_cursor=1,
    )
    assert evidence is True
    assert commits == (1,)  # 只提交 id1，id2 起为 gap，不跨 gap 提交 id3
    assert gap == (2, 3)
    # 全 ACCEPT -> gap 解决
    commits2, gap2, _ = build_retry_writeback_plan(
        plan=plan, retry_rows=rows,
        retry_p_bad=[0.1, 0.1, 0.1, 0.1],
        frozen_wp=FROZEN_WP, base_cursor=1,
    )
    assert commits2 == (1, 2, 3) and gap2 is None
