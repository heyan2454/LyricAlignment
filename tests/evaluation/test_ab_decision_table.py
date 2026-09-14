from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ab_decision_table", ROOT / "scripts" / "evaluation" / "ab_decision_table.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _side(mean: float, p_t: float, p_m: float, *, status: str = "measured") -> dict:
    return {"sides": {"offset_long": {"status": status, "n": 938, "mean_delta_ms": mean,
                                      "p_t": p_t, "p_t_times_sides": p_t,
                                      "p_mcnemar_exact": p_m, "p_mcnemar_times_sides": p_m,
                                      "mcnemar_better": 20, "mcnemar_worse": 5,
                                      "median_delta_ms": -1.0, "trimmed_mean_delta_ms": -2.0}}}


def _short(delta_pp: float) -> dict:
    return {"variants": {"fixed": {"points": 5, "mean_delta_pp": delta_pp,
                                   "b_better_points": 0, "b_worse_points": 4,
                                   "last_shared": {"step": 500, "a": 0.9568, "b": 0.9501}}}}


def test_three_gates_all_required_before_claiming_improvement():
    strong, block = MODULE.long_verdict(_side(-18.0, 0.001, 0.002))
    assert strong == "improved"
    assert block["mean_delta_ms"] == -18.0 and block["n"] == 938      # 返回的是原始格子，供追溯
    # 只过均值一关 ⇒ 只能算迹象（今晚我自己犯的错就是这个）
    hint, _ = MODULE.long_verdict(_side(-12.0, 0.046, 0.20))
    assert hint == "hint"
    # 方向不对 ⇒ nothing
    nothing, _ = MODULE.long_verdict(_side(+1.2, 0.76, 0.60))
    assert nothing == "nothing"
    # 改善幅度不足 10 ms ⇒ 即便 p 很小也不算（预注册的效应量下限）
    small, _ = MODULE.long_verdict(_side(-3.0, 0.0001, 0.0001))
    assert small in ("nothing", "hint")


def test_short_states_use_the_registered_pp_thresholds():
    assert MODULE.short_verdict(_short(-0.32))[0] == "worse"
    assert MODULE.short_verdict(_short(-0.05))[0] == "flat"
    assert MODULE.short_verdict(_short(+0.40))[0] == "better"


def test_row_mapping_matches_the_preregistered_two_by_two():
    assert MODULE.ROWS[("improved", "worse")][0].startswith("第 1 行")
    assert MODULE.ROWS[("improved", "flat")][0].startswith("第 2 行")
    assert MODULE.ROWS[("nothing", "worse")][0].startswith("第 3 行")      # 不确定，不否证
    assert MODULE.ROWS[("nothing", "flat")][0].startswith("第 4 行")      # 唯一允许写"否证"的格
    assert "C 不启动" in MODULE.ROWS[("nothing", "flat")][1]


def test_missing_side_document_is_reported_as_missing_not_as_no_effect():
    assert MODULE.long_verdict(None)[0] == "missing"
    assert MODULE.long_verdict({"sides": {}})[0] == "missing"
    assert MODULE.long_verdict(_side(0, 1, 1, status="insufficient_data"))[0] == "missing"
    assert MODULE.short_verdict(None)[0] == "missing"
    assert MODULE.short_verdict({"variants": {}})[0] == "missing"
