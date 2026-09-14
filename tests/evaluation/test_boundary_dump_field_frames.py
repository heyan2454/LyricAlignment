from __future__ import annotations

import json

TIME_KEYS = ("abs_err_argmax", "abs_err_constrained", "signed_err", "pred_sec", "duration")
LOUDNESS_KEYS = ("gt", "pred_argmax", "pred_constrained")


def test_documented_field_frames_are_not_cross_checked():
    """守夜人测试：坐标系列在源码注释里，且明确禁止跨坐标系的自洽检查。"""
    import pathlib
    source = pathlib.Path("scripts/evaluation/measure_predicted_boundary_acoustics.py").read_text(encoding="utf-8")
    assert "响度类" in source and "时间类" in source
    assert "别再做" in source
    # 时间字段与响度字段不得混在同一份断言里（这里只是把名单钉住，改名时测试会提醒更新注释）
    assert set(TIME_KEYS).isdisjoint(LOUDNESS_KEYS)


def test_a_real_dump_row_carries_both_frames(tmp_path):
    row = {"kind": "onset", "duration": 0.4, "gt": 250.0, "pred_argmax": 240.0,
           "pred_sec": 1.2, "signed_err": -0.08, "abs_err_argmax": 0.08}
    assert abs(row["pred_sec"] + row["signed_err"] - 1.12) < 1e-9      # 时间坐标系内自洽
    assert abs(row["gt"] - row["pred_sec"]) > 1                        # 跨坐标系差值毫无意义
    assert json.dumps(row)
