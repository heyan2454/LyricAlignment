#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluate_sequence_cnn1d.py — 方向 3：CNN1D 序列模型公平比较（23_FUTURE_DIRECTIONS）。

在 run2 evidence_v2 + LABELS 上构造 song-grouped 定长序列数据集（canonical 序：
歌内按 official.start_sec 升序 + canonical_unit_id + request_identity 决胜，
序列内不 shuffle，train/val 按 LABELS split 隔离不跨歌），训练 sequence_model
（CNN1D，detector_v2_models.sequence_model），并与 frozen raw 口径的 small_mlp /
constrained_gbdt（combo=R+O，_make_trainer）在同一 validation 分区公平比较：
每个模型在 val 上找 p_bad 阈值使 safe_accept >= --min-safe-accept，记 protocol
（unsafe 拒绝率）。输出 schema sequence_cnn1d_compare_v1（原子写）。

特征列与 frozen official combo 对齐：仅 official_/ro_/repair_/has_ 前缀键
（同 train_detector_v2.sig_idx 的 O 组），CNN 与基线用同一列集。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

SCHEMA = "sequence_cnn1d_compare_v1"
COMBO_PREFIXES = ("official_", "ro_", "repair_", "has_")
START_KEYS = ("official_start_sec", "raw_start_sec", "cv_start_sec")

_SCRIPT = Path(__file__).resolve()
_SCRIPTS_DIR = _SCRIPT.parents[1]
_TRAIN_MODULE = _SCRIPTS_DIR / "research_v7" / "train_detector_v2.py"


def _load_train_module():
    spec = importlib.util.spec_from_file_location("train_detector_v2", _TRAIN_MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def combo_keys(feat_keys) -> list[str]:
    """frozen official combo R+O 列集：official_/ro_/repair_/has_ 前缀，稳定排序。"""
    return sorted(k for k in feat_keys if k.startswith(COMBO_PREFIXES))


def canonical_sort_key(row: dict) -> tuple:
    """canonical 序：official.start_sec 升序 + canonical_unit_id + request_identity。"""
    feats = row.get("features") or {}
    start = next((feats.get(k) for k in START_KEYS if feats.get(k) is not None), 0.0)
    return (float(start or 0.0), int(row["canonical_unit_id"]), str(row["request_identity"]))


def partition_rows(train_rows: list[dict], val_rows: list[dict]):
    """断言 train/val 歌集合不相交（防泄漏），返回 (train, validation) 列表。"""
    overlap = {r["song_id"] for r in train_rows} & {r["song_id"] for r in val_rows}
    if overlap:
        raise ValueError(f"song leak across train/validation: {sorted(overlap)[:5]}")
    return train_rows, val_rows


def build_sequences(rows: list[dict], T: int, keys: list[str]):
    """song-grouped 定长序列：每歌窗口按 canonical 序排好，切成 T 长片段，尾填 0。

    rows 需含 song_id/features/label（"safe"=0，"unsafe"=1）。返回
    {"X": (n,T,d), "y": (n,) any-of 窗口 label, "mask": (n,T) bool,
     "seq_song", "keys", "T", ...}；序列标签 = 序列内任意窗口 unsafe → 1
    （frozen sequence_model 契约：y 为每序列一个标签）。尾部填充位置
    mask=False（输出 data.padding 注明：填充 0 行参与模型统计量/前向，
    不参与指标）。**窗口级对齐**：window_indices 为 mask 展平序下每窗口
    在输入 rows 的原始索引，y_window 为同序窗口 label——消费方必须用
    [rows[i] for i in window_indices] 重排后做窗口级评价（避免与基线
    build_matrix 原始行序错位，review P1-1）。
    """
    d = len(keys)
    by_song: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_song[r["song_id"]].append((i, r))
    Xs, ys, masks, seq_song = [], [], [], []
    idx: list[int] = []
    y_window: list[float] = []
    n_padded = 0
    for song in sorted(by_song):
        windows = sorted(by_song[song], key=lambda ir: canonical_sort_key(ir[1]))
        for chunk_start in range(0, len(windows), T):
            chunk = windows[chunk_start:chunk_start + T]
            m = len(chunk)
            X = np.zeros((T, d), dtype=float)
            mask = np.zeros(T, dtype=bool)
            for k, (i, r) in enumerate(chunk):
                f = r["features"]
                X[k] = [np.nan if k not in f or f[k] is None else float(f[k]) for k in keys]
                mask[k] = True
                idx.append(i)
                y_window.append(1.0 if r["label"] == "unsafe" else 0.0)
            n_padded += T - m
            Xs.append(X)
            masks.append(mask)
            seq_song.append(song)
            ys.append(1.0 if any(r["label"] == "unsafe" for _, r in chunk) else 0.0)
    if not Xs:
        return None
    return {"X": np.stack(Xs), "y": np.asarray(ys, dtype=float), "mask": np.stack(masks),
            "seq_song": seq_song, "keys": keys, "T": T, "n_seq": len(Xs),
            "n_padded_rows": n_padded,
            "n_windows": sum(len(v) for v in by_song.values()),
            "seq_per_song": {s: max(1, math.ceil(len(v) / T)) for s, v in by_song.items()},
            "window_indices": idx,
            "y_window": np.asarray(y_window, dtype=float)}


def select_T(song_lens: list[int], quantile: float, kernel_size: int) -> int:
    """T = 分位截断（ceil，至少 kernel_size）。"""
    T = int(math.ceil(np.quantile(np.asarray(sorted(song_lens)), quantile)))
    return max(T, kernel_size)


def window_matrix(rows: list[dict], keys: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """行级特征矩阵（缺键 NaN，基线 trainer 内部各自 impute）。"""
    X = np.asarray([[np.nan if k not in r["features"] or r["features"][k] is None
                     else float(r["features"][k]) for k in keys] for r in rows], dtype=float)
    y = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in rows], dtype=float)
    return X, y


def operating_point(p_bad: np.ndarray, y: np.ndarray, *, min_safe_accept: float,
                    n_sweep: int = 5) -> dict:
    """val 上找阈值：safe_accept >= min_safe_accept 时 protocol（unsafe 拒绝率）最高。"""
    p = np.asarray(p_bad, dtype=float).ravel()
    yb = np.asarray(y, dtype=float).ravel()
    unsafe = yb == 1.0
    safe = yb == 0.0
    n_unsafe = int(unsafe.sum())
    n_safe = int(safe.sum())
    if n_unsafe == 0 or n_safe == 0:
        return {"feasible": False, "n_unsafe": n_unsafe, "n_safe": n_safe,
                "note": "single-class val split"}
    best = None
    sweep = []
    for t in np.unique(p):
        acc = p <= t
        safe_accept = float(acc[safe].mean())
        protocol = float((~acc[unsafe]).mean())
        sweep.append({"threshold": float(t), "safe_accept": safe_accept,
                      "protocol": protocol})
        if safe_accept >= min_safe_accept - 1e-12:
            if best is None or protocol > best[1]:
                best = (float(t), protocol, safe_accept)
    if best is None:
        return {"feasible": False, "n_unsafe": n_unsafe, "n_safe": n_safe,
                "min_safe_accept": min_safe_accept,
                "note": "no threshold reaches min_safe_accept on val",
                "sweep_top": sorted(sweep, key=lambda s: -s["safe_accept"])[:n_sweep]}
    return {"feasible": True, "threshold": best[0], "protocol": best[1],
            "safe_accept": best[2], "n_unsafe": n_unsafe, "n_safe": n_safe,
            "min_safe_accept": min_safe_accept,
            "sweep_top": sorted(sweep, key=lambda s: -s["safe_accept"])[:n_sweep]}


def _auc(p: np.ndarray, y: np.ndarray):
    """Mann-Whitney U 的 AUC（mergesort 稳定秩；并列分数不取平均秩，探索口径足够）。
    单类返回 None。"""
    p = np.asarray(p, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    yb = y == 1.0
    n_pos = int(yb.sum())
    n_neg = int((~yb).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    rank = np.empty_like(order)
    rank[order] = np.arange(1, len(p) + 1)
    u = float(rank[yb].sum() - n_pos * (n_pos + 1) / 2)
    return float(u / (n_pos * n_neg))


def sequence_compare(seq_train: dict, seq_val: dict, *, epochs: int, kernels: int,
                     kernel_size: int, lr: float, seed: int,
                     min_safe_accept: float = 0.05) -> tuple[dict, np.ndarray]:
    """训练 CNN1D（supervision：序列级 any-unsafe 标签，frozen 契约 y=(n,)）。

    val 上做**序列级评价**：p_seq = predict_fn(seq_val["X"]) 直接输出 (n_seq,)，
    与 seq_val["y"] 序列标签同口径评估 operating_point + Brier + AUC（输出 seq_op，
    监督语义 = 序列整体 unsafe 与否，不广播）；同时保留窗口级 broadcast
    p_bad（np.repeat → mask 展平）用于窗口级公平对比。
    """
    from lyricalign.research_v7.detector_v2_models import sequence_model
    model = sequence_model(seq_train["X"], seq_train["y"], kind="cnn1d",
                           kernels=kernels, kernel_size=kernel_size,
                           epochs=epochs, lr=lr, seed=seed)
    p_seq = np.asarray(model["predict_fn"](seq_val["X"]), dtype=float)  # (n_seq,)
    seq_op = operating_point(p_seq, seq_val["y"], min_safe_accept=min_safe_accept)
    seq_op["supervision"] = "sequence_any_bad（y=每序列一标签，不广播，直接评估）"
    seq_op["brier"] = float(np.mean((p_seq - seq_val["y"]) ** 2))
    seq_op["auc"] = _auc(p_seq, seq_val["y"])
    seq_op["n_unique_p_seq"] = int(len(np.unique(np.round(p_seq, 6))))
    seq_op["n_seq"] = int(len(p_seq))
    seq_op["n_seq_unsafe"] = int(seq_val["y"].sum())
    seq_op["note"] = ("序列级评价（协议同口径：safe_accept>=min_safe_accept 下最高"
                      "unsafe 拒绝率），与窗口级 op 并列但监督对象不同，不可互换")
    p_full = np.repeat(p_seq[:, None], seq_val["T"], axis=1)  # (n_seq, T)
    p_bad = p_full[seq_val["mask"]]
    n_unique = int(len(np.unique(np.round(p_bad, 6))))
    return {"kind": "sequence_cnn1d", "kernels": kernels, "kernel_size": kernel_size,
            "epochs": epochs, "lr": lr, "seed": seed,
            "supervision": "sequence_any_bad + broadcast",
            "seq_op": seq_op,
            "degenerate": n_unique < 3,
            "n_unique_p_bad": n_unique,
            "note": ("degenerate=True 表示窗口级 p_bad 近似常量（序列级监督广播后"
                     "区分度不足），protocol 数字不可作为窗口级结论" if n_unique < 3
                     else "窗口级 p_bad 由序列级预测广播得到，见 supervision"),
            "loss_first": float(model["loss_history"][0]),
            "loss_last": float(model["loss_history"][-1]),
            "loss_history": [float(v) for v in model["loss_history"]]}, p_bad


def compare_models(*, train_rows: list[dict], val_rows: list[dict], T: int, keys: list[str],
                   epochs: int, kernels: int, kernel_size: int, lr: float = 0.05,
                   seed: int = 0, min_safe_accept: float = 0.05) -> dict:
    """三方公平比较：CNN1D / small_mlp / constrained_gbdt，同 val 分区同列集。"""
    from lyricalign.research_v7.detector_v2_models import _make_trainer
    train_rows, val_rows = partition_rows(train_rows, val_rows)
    seq_train = build_sequences(train_rows, T, keys)
    seq_val = build_sequences(val_rows, T, keys)

    cn_out, p_cnn = sequence_compare(seq_train, seq_val, epochs=epochs,
                                     kernels=kernels, kernel_size=kernel_size,
                                     lr=lr, seed=seed,
                                     min_safe_accept=min_safe_accept)

    val_aligned = [val_rows[i] for i in seq_val["window_indices"]]
    Xt, yt = window_matrix(train_rows, keys)
    Xv, yv = window_matrix(val_aligned, keys)
    yv_flat = np.asarray([1.0 if r["label"] == "unsafe" else 0.0
                          for r in val_aligned], dtype=float)

    models: dict[str, dict] = {"sequence_cnn1d": cn_out}
    for kind in ("small_mlp", "constrained_gbdt"):
        trainer = _make_trainer(kind, seed=seed)
        p_val = trainer(Xt, yt, Xv)
        models[kind] = {"kind": kind, "combo": "R+O",
                        "op": operating_point(p_val, yv_flat,
                                              min_safe_accept=min_safe_accept)}
        if len(p_val) == len(p_cnn) and np.std(p_cnn) > 1e-9 and np.std(p_val) > 1e-9:
            models[kind]["p_bad_corr_cnn"] = float(np.corrcoef(p_val, p_cnn)[0, 1])
        else:
            models[kind]["p_bad_corr_cnn"] = None  # 常量输出时相关性无定义
    models["sequence_cnn1d"]["op"] = operating_point(
        p_cnn, yv_flat, min_safe_accept=min_safe_accept)
    seq_op = models["sequence_cnn1d"]["seq_op"]
    if seq_op.get("feasible") and seq_op.get("protocol", 0.0) > 0.3:
        decision = "sequence_level_viable"
    else:
        decision = "degrade_documented"
    return {"models": models, "decision": decision,
            "n_train_windows": len(train_rows),
            "n_val_windows": len(val_rows),
            "n_val_songs": len({r["song_id"] for r in val_rows}),
            "n_train_songs": len({r["song_id"] for r in train_rows})}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--target", default="raw", choices=("raw", "official"))
    ap.add_argument("--t-quantile", type=float, default=0.9)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--kernels", type=int, default=4)
    ap.add_argument("--kernel-size", type=int, default=3)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--min-safe-accept", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit-requests", type=int, default=None)
    ap.add_argument("--max-songs", type=int, default=None)
    args = ap.parse_args()

    t0 = time.time()
    train_mod = _load_train_module()
    by_target = train_mod.build_matrix(args.evidence_dir, args.labels,
                                       limit_requests=args.limit_requests)
    splits = by_target[args.target]
    train_rows = splits.get("train", [])
    val_rows = splits.get("validation", [])
    if args.max_songs:
        keep = sorted({r["song_id"] for r in (train_rows + val_rows)})[:args.max_songs]
        train_rows = [r for r in train_rows if r["song_id"] in keep]
        val_rows = [r for r in val_rows if r["song_id"] in keep]
    train_rows, val_rows = partition_rows(train_rows, val_rows)
    if not train_rows or not val_rows:
        print(json.dumps({"ok": False,
                          "error": "empty split after filtering (train=%d, val=%d)"
                          % (len(train_rows), len(val_rows))}))
        return 1
    feat_keys = sorted({k for r in (train_rows + val_rows) for k in r["features"]})
    keys = combo_keys(feat_keys)
    if not keys:
        print(json.dumps({"ok": False, "error": "no combo features found"}))
        return 1
    train_lens = [sum(1 for r in train_rows if r["song_id"] == s)
                  for s in sorted({r["song_id"] for r in train_rows})]
    T = select_T(train_lens, args.t_quantile, args.kernel_size)

    result = compare_models(train_rows=train_rows, val_rows=val_rows, T=T, keys=keys,
                            epochs=args.epochs, kernels=args.kernels,
                            kernel_size=args.kernel_size, lr=args.lr, seed=args.seed,
                            min_safe_accept=args.min_safe_accept)
    seq_train = build_sequences(train_rows, T, keys)
    seq_val = build_sequences(val_rows, T, keys)

    payload = {
        "schema": SCHEMA,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "target": args.target,
        "args": {k: str(v) if isinstance(v, Path) else v
                 for k, v in vars(args).items()},
        "data": {
            "n_train_songs": result["n_train_songs"], "n_val_songs": result["n_val_songs"],
            "n_train_windows": result["n_train_windows"], "n_val_windows": result["n_val_windows"],
            "T": T, "t_quantile": args.t_quantile,
            "padding": "zero_pad_no_mask",
            "n_seq_train": seq_train["n_seq"], "n_seq_val": seq_val["n_seq"],
            "n_seq_train_unsafe": int(seq_train["y"].sum()),
            "n_seq_val_unsafe": int(seq_val["y"].sum()),
            "n_seq_val_safe": int((seq_val["y"] == 0).sum()),
            "n_seq_val_positive_rate": float(seq_val["y"].mean()),
            "decision": result["decision"],
            "n_padded_rows_train": seq_train["n_padded_rows"],
            "n_padded_rows_val": seq_val["n_padded_rows"],
            "seq_per_song_train": seq_train["seq_per_song"],
            "seq_per_song_val": seq_val["seq_per_song"],
            "song_len_dist_train": sorted(train_lens),
            "features": {"n_features": len(keys), "keys": keys, "combo": "R+O"},
        },
        "models": result["models"],
        "metrics": {
            "train_seconds": round(time.time() - t0, 1),
            "note": ("protocol = unsafe 拒绝率（val 阈值 safe_accept>=min_safe_accept）；"
                     "与冻结三态语义（T_accept/T_reject+uncertain）不同：此处为单阈值"
                     "二元探索口径，结果不作 Detector V2 frozen 工作点；"
                     "sequence_cnn1d.seq_op 为序列级（y=每序列一标签）同口径评估，"
                     "decision 由 seq_op.protocol>0.3 决定（backlog #2 三选一决策）；"
                     "序列级为探索性结论：n_seq_val 极小（见 data.n_seq_val），"
                     "AUC=1.0 仅指示性"),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(args.out.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.out)
    print(json.dumps({"ok": True, "out": str(args.out), "T": T,
                      "n_seq_train": seq_train["n_seq"], "n_seq_val": seq_val["n_seq"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
