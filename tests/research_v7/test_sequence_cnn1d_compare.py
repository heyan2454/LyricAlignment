# -*- coding: utf-8 -*-
"""evaluate_sequence_cnn1d.py 测试：序列构造（定长/填充/歌内序/防泄漏）+
CNN1D 收敛 + 三方公平比较输出 schema（23 方向 3）。"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research_v7" / "evaluate_sequence_cnn1d.py"
_spec = importlib.util.spec_from_file_location("evaluate_sequence_cnn1d", _SCRIPT)
MOD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MOD)

FEAT_KEYS = ["official_start_sec", "official_end_sec", "official_repair_start_shift_sec",
             "ro_peak_align", "repair_end_shift_sec", "has_left_neighbor", "raw_start_sec"]


def _row(song, start, cid, label, rid="req-0"):
    return {"request_identity": rid, "canonical_unit_id": cid, "target": "raw",
            "label": label, "song_id": song,
            "features": {"official_start_sec": start, "official_end_sec": start + 0.5,
                         "official_repair_start_shift_sec": 0.01, "ro_peak_align": 0.8,
                         "repair_end_shift_sec": 0.02, "has_left_neighbor": 1.0,
                         "raw_start_sec": start}}


def _synthetic_rows():
    rows = []
    for i, start in enumerate([3.0, 1.0, 4.5, 2.0, 0.5, 5.5]):  # 故意乱序
        rows.append(_row("train_song_a", start, 100 + i,
                         "unsafe" if i % 3 == 0 else "safe", rid=f"req-a"))
    rows.append(_row("train_song_a", 6.0, 200, "safe", rid="req-a"))
    rows.append(_row("train_song_b", 0.0, 300, "safe", rid="req-b"))
    rows.append(_row("train_song_b", 1.2, 301, "unsafe", rid="req-b"))
    rows.append(_row("val_song_c", 0.0, 400, "safe", rid="req-c"))
    rows.append(_row("val_song_c", 1.0, 401, "safe", rid="req-c"))
    rows.append(_row("val_song_c", 2.0, 402, "unsafe", rid="req-c"))
    for r in rows:
        r["split"] = "validation" if r["song_id"].startswith("val_") else "train"
    return rows


def test_combo_keys_filters_prefix():
    keys = MOD.combo_keys(FEAT_KEYS + ["raw_entropy", "cv_x"])
    assert all(k.startswith(MOD.COMBO_PREFIXES) for k in keys)
    assert "raw_start_sec" not in keys
    assert "raw_entropy" not in keys
    assert keys == sorted(keys)


def test_select_T_quantile():
    assert MOD.select_T([3, 4, 5, 6, 7, 8], 0.9, 3) == 8
    assert MOD.select_T([2, 3], 0.9, 3) >= 3
    assert MOD.select_T([1, 1], 0.9, 3) == 3


def test_build_sequences_fixed_length_padding_and_order():
    rows = _synthetic_rows()
    train = [r for r in rows if r["split"] == "train"]
    seq = MOD.build_sequences(train, T=4, keys=MOD.combo_keys(FEAT_KEYS))
    assert seq["X"].shape == (seq["n_seq"], 4, len(seq["keys"]))
    assert seq["y"].shape == (seq["n_seq"],)  # 序列级标签（any-unsafe，frozen 契约）
    assert seq["mask"].shape == (3, 4)
    assert seq["n_seq"] == 3  # song_a 7 窗口 → 2 段，song_b 2 窗口 → 1 段
    assert seq["n_padded_rows"] == 3
    assert seq["seq_per_song"] == {"train_song_a": 2, "train_song_b": 1}
    # 歌内顺序保持：每序列 start 单调不减（canonical 序，不 shuffle）
    start_idx = seq["keys"].index("official_start_sec")
    for X, mask in zip(seq["X"], seq["mask"]):
        starts = X[mask, start_idx]
        assert np.all(np.diff(starts) >= -1e-9)
    # 段 0 = song_a 的 canonical 序前 4 窗口，无填充；段 1 尾 1 行填充；段 2 尾 2 行填充
    assert np.allclose(seq["X"][0, :4, start_idx], [0.5, 1.0, 2.0, 3.0])
    assert np.all(seq["mask"][0])
    assert not seq["mask"][1][3] and np.all(seq["mask"][1][:3])
    assert not np.any(seq["mask"][2][2:])
    # 序列标签（any-unsafe）：段 0=1（含 2.0/3.0 unsafe），段 1=0（全 safe），song_b=1
    assert seq["y"][0] == 1.0 and seq["y"][1] == 0.0 and seq["y"][2] == 1.0
    # 纯 safe 序列 → 0
    seq_safe = MOD.build_sequences([_row("safe_song", 0.0, 0, "safe", rid="r0"),
                                    _row("safe_song", 1.0, 1, "safe", rid="r0")],
                                   T=4, keys=MOD.combo_keys(FEAT_KEYS))
    assert seq_safe["y"][0] == 0.0


def test_partition_rows_no_cross_song_leak():
    rows = _synthetic_rows()
    train = [r for r in rows if r["split"] == "train"]
    val = [r for r in rows if r["split"] == "validation"]
    tr, va = MOD.partition_rows(train, val)
    assert {r["song_id"] for r in tr} == {"train_song_a", "train_song_b"}
    assert {r["song_id"] for r in va} == {"val_song_c"}
    with pytest.raises(ValueError, match="leak"):
        MOD.partition_rows(train, val + [_row("train_song_a", 9.0, 999, "safe", rid="req-a")])


def test_build_sequences_window_alignment():
    """review P1-1 回归：window_indices/y_window 与 mask 展平序、原始行 label 一致。"""
    rows = _synthetic_rows()
    val = [r for r in rows if r["split"] == "validation"]
    seq = MOD.build_sequences(val, T=4, keys=MOD.combo_keys(FEAT_KEYS))
    assert len(seq["window_indices"]) == len(val) == len(seq["y_window"])
    assert int(seq["mask"].sum()) == len(seq["window_indices"])
    aligned = [val[i] for i in seq["window_indices"]]
    assert np.allclose(seq["y_window"],
                       [1.0 if r["label"] == "unsafe" else 0.0 for r in aligned])
    start_idx = seq["keys"].index("official_start_sec")
    starts = [r["features"]["official_start_sec"] for r in aligned]
    assert np.all(np.diff(starts) >= -1e-9)


def test_compare_models_multi_song_val_alignment():
    """review P1-1 回归：多歌 val + 乱序输入下，三模型共用对齐后的窗口序。"""
    rows = _synthetic_rows()
    for start, cid in [(2.5, 500), (0.0, 501), (1.2, 502)]:
        rows.append(_row("val_song_d", start, cid,
                         "unsafe" if cid == 500 else "safe", rid="req-d"))
    for r in rows:
        if r["song_id"] == "val_song_d":
            r["split"] = "validation"
    train = [r for r in rows if r["split"] == "train"]
    val = [r for r in rows if r["split"] == "validation"]
    res = MOD.compare_models(train_rows=train, val_rows=val, T=4,
                             keys=MOD.combo_keys(FEAT_KEYS), epochs=15,
                             kernels=2, kernel_size=3, lr=0.1, seed=0,
                             min_safe_accept=0.05)
    assert res["n_val_songs"] == 2
    n_unsafe = sum(1 for r in val if r["label"] == "unsafe")
    for name, info in res["models"].items():
        assert info["op"]["n_unsafe"] == n_unsafe
        assert info["op"]["n_safe"] == len(val) - n_unsafe
    assert "p_bad_corr_cnn" in res["models"]["small_mlp"]


def test_operating_point():
    p = np.array([0.9, 0.8, 0.7, 0.2, 0.1, 0.05])
    y = np.array([1, 1, 0, 0, 1, 0])
    op = MOD.operating_point(p, y, min_safe_accept=0.5)
    assert op["feasible"]
    assert op["safe_accept"] >= 0.5 - 1e-9
    assert op["protocol"] > 0.5


def test_sequence_model_converges():
    from lyricalign.research_v7.detector_v2_models import sequence_model
    rng = np.random.RandomState(0)
    X = rng.randn(4, 8, 3)
    y = np.array([1, 0, 1, 0], dtype=float)
    m = sequence_model(X, y, kind="cnn1d", kernels=4, kernel_size=3,
                       epochs=80, lr=0.1, seed=0)
    assert m["loss_history"][-1] < m["loss_history"][0]
    pred = m["predict_fn"](X + 0.1)
    assert pred.shape == (4,)
    assert np.all((pred >= 0.0) & (pred <= 1.0))


def test_compare_models_schema():
    rows = _synthetic_rows()
    keys = MOD.combo_keys(FEAT_KEYS)
    train = [r for r in rows if r["split"] == "train"]
    val = [r for r in rows if r["split"] == "validation"]
    res = MOD.compare_models(train_rows=train, val_rows=val, T=4, keys=keys, epochs=20,
                             kernels=2, kernel_size=3, lr=0.1, seed=0,
                             min_safe_accept=0.05)
    assert set(res["models"]) == {"sequence_cnn1d", "small_mlp", "constrained_gbdt"}
    for name, info in res["models"].items():
        assert "op" in info and "threshold" in info["op"]
        assert info["op"]["n_unsafe"] > 0 and info["op"]["n_safe"] > 0
    assert res["n_train_windows"] == 9
    assert res["n_val_windows"] == 3
    assert res["n_train_songs"] == 2 and res["n_val_songs"] == 1
    cnn = res["models"]["sequence_cnn1d"]
    assert cnn["loss_first"] >= 0 and cnn["loss_history"]
    assert len(cnn["loss_history"]) == 20
    assert "p_bad_corr_cnn" in res["models"]["small_mlp"]
    seq_op = cnn["seq_op"]
    for key in ("supervision", "brier", "auc", "n_unique_p_seq", "n_seq",
                "n_seq_unsafe", "feasible", "n_safe", "n_unsafe"):
        assert key in seq_op, f"seq_op missing {key}"
    assert 0.0 <= seq_op["brier"] <= 1.0
    assert seq_op["auc"] is None or 0.0 <= seq_op["auc"] <= 1.0
    assert seq_op["n_unique_p_seq"] >= 1
    assert seq_op["n_seq"] >= 1
    assert seq_op["n_seq_unsafe"] == int(seq_op["n_unsafe"])
    assert seq_op["n_seq"] == seq_op["n_unsafe"] + seq_op["n_safe"]
    assert res["decision"] in ("sequence_level_viable", "degrade_documented")
    expected = ("sequence_level_viable" if (seq_op.get("feasible")
                and seq_op.get("protocol", 0.0) > 0.3) else "degrade_documented")
    assert res["decision"] == expected


def test_compare_models_decision_multisong_val():
    """decision 字段存在且与 seq_op 一致（多歌 val，seq_op 单类时 degrade）。"""
    rows = _synthetic_rows()
    for start, cid in [(2.5, 500), (0.0, 501), (1.2, 502)]:
        rows.append(_row("val_song_d", start, cid,
                         "unsafe" if cid == 500 else "safe", rid="req-d"))
    for r in rows:
        if r["song_id"] == "val_song_d":
            r["split"] = "validation"
    train = [r for r in rows if r["split"] == "train"]
    val = [r for r in rows if r["split"] == "validation"]
    res = MOD.compare_models(train_rows=train, val_rows=val, T=4,
                             keys=MOD.combo_keys(FEAT_KEYS), epochs=15,
                             kernels=2, kernel_size=3, lr=0.1, seed=0,
                             min_safe_accept=0.05)
    seq_op = res["models"]["sequence_cnn1d"]["seq_op"]
    expected = ("sequence_level_viable" if (seq_op.get("feasible")
                and seq_op.get("protocol", 0.0) > 0.3) else "degrade_documented")
    assert res["decision"] == expected
    assert not seq_op["feasible"] or len(seq_op.get("sweep_top", [])) > 0
