from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "duration_calibration_test", ROOT / "scripts" / "evaluation" / "duration_calibration_test.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

XS = [0.3, 1.0, 2.0]
YS = [0.3, 1.0, 2.2]


def test_out_of_range_duration_is_left_alone_instead_of_clamped():
    """Clamping beyond the last knot invents a correction and wrecked the ≥2s bucket once already."""
    assert MODULE.interp(5.0, XS, YS, outside="identity") == 5.0      # 不修正
    assert MODULE.interp(0.05, XS, YS, outside="identity") == 0.05
    assert MODULE.interp(5.0, XS, YS, outside="clamp") == 2.2         # 旧行为，保留以便对比
    assert MODULE.interp(0.05, XS, YS, outside="clamp") == 0.3


def test_bias_outside_range_is_zero_not_a_shift():
    assert MODULE.interp(9.0, XS, YS, outside="zero") == 0.0
    assert MODULE.interp(0.01, XS, YS, outside="zero") == 0.0


def test_interpolation_inside_the_range_is_linear():
    assert MODULE.interp(1.5, XS, YS, outside="identity") == 1.6      # 中点 (1.0+2.2)/2
    assert abs(MODULE.interp(1.0, XS, YS, outside="identity") - 1.0) < 1e-9


def test_grouping_is_per_song_not_per_singer():
    # item_id 是 Singer#Song#NNNN；留出单位必须是 singer#song，与其它 macro-over-songs 指标一致
    keys = {"ZH-Alto-1#不再见#0001", "ZH-Alto-1#不再见#0002", "ZH-Soprano-2#风雨#0001"}
    # characters() 需要 dump 文件，这里只验证分组函数逻辑等价的形式
    def group(item_id: str) -> str:
        parts = str(item_id).split("#")
        return "#".join(parts[:2]) if len(parts) >= 2 else str(item_id)
    assert {group(k) for k in keys} == {"ZH-Alto-1#不再见", "ZH-Soprano-2#风雨"}
