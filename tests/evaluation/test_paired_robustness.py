from __future__ import annotations

import importlib.util
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "paired_robustness_check", ROOT / "scripts" / "evaluation" / "paired_robustness_check.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_mcnemar_exact_is_symmetric_and_conservative():
    assert MODULE.mcnemar_exact(0, 0) == 1.0
    assert abs(MODULE.mcnemar_exact(0, 5) - min(1.0, 2 * 0.5 ** 5)) < 1e-12
    assert abs(MODULE.mcnemar_exact(5, 0) - MODULE.mcnemar_exact(0, 5)) < 1e-12      # 对称
    assert MODULE.mcnemar_exact(20, 20) == 1.0                                        # 完全对称无证据
    assert MODULE.mcnemar_exact(2, 20) < 0.001                                        # 强不对称


def test_trimmed_mean_ignores_a_few_extreme_moves():
    import statistics as st
    values = [0.0] * 97 + [20000.0, -5000.0, 9000.0]          # 均值 240 ms，中位数 0
    assert st.mean(values) > 100                               # 普通均值被极端值主导
    assert abs(MODULE.trimmed_mean(values, 0.05)) < 1e-9       # 截尾后回到真实中心


def test_mean_significant_but_median_zero_is_reported_as_hint_not_proof():
    """少数极端值能把均值做到 p<0.05，此时不得写"确证"——这正是我 08:13 犯的错。"""
    old = {("i", idx): {"onset": {"duration": 2.0, "abs_err_argmax": 0.04},
                        "offset": {"duration": 2.0, "abs_err_argmax": 0.04}} for idx in range(60)}
    new = {key: {kind: dict(value, abs_err_argmax=value["abs_err_argmax"])
                 for kind, value in sides.items()} for key, sides in old.items()}
    for index, (kind, extra, broken) in enumerate([("offset", 0.0, 5)]):
        keys = sorted(new)[:broken]
        for key in keys:
            new[key][kind]["abs_err_argmax"] = 3.0        # 5 个字符从 40ms 变成 3s
    payload = MODULE.analyse(old, new, sorted(old.keys()))
    block = payload["sides"]["offset_long"]
    assert block["status"] == "measured"
    assert block["mean_delta_ms"] > 200                              # 均值被少数极端值推动
    assert abs(block["median_delta_ms"]) < 1e-9                      # 中位数没动
    assert block["verdict"] in ("迹象（未过校正）", "无证据")           # 绝不是"确证"
    assert block["mcnemar_better"] == 0 and block["mcnemar_worse"] == 5


def test_insufficient_side_is_labelled_not_invented():
    old = {("i", idx): {"onset": {"duration": 2.0, "abs_err_argmax": 0.01},
                        "offset": {"duration": 2.0, "abs_err_argmax": 0.01}} for idx in range(5)}
    payload = MODULE.analyse(old, old, sorted(old))
    assert payload["sides"]["onset_long"]["status"] == "insufficient_data"
    assert payload["sides"]["offset_long"]["n"] == 5
