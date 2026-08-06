#!/usr/bin/env python3
"""F1 升级（23 方向 2）：p_bad 校准 song-grouped 交叉验证 + uncertain 成本模型。

风险背景：analyze_pbad_calibration.py 的 val 仅 5 歌，校准曲线不可信。本脚本按
LABELS.jsonl train 分区歌曲做 K 折（默认 K=5）song-grouped CV：每折在 4/5 歌曲上
重训 frozen op 指定的 model_kind+best_combo（读 FROZEN_OPERATING_POINTS.json），
留出折上出 p_bad 与三种校准（raw / temperature / isotonic，isotonic 与 temperature
均在折内 train 拟合，杜绝 val 上拟合校准参数的信息泄漏）。

成本模型（uncertain 三态，文档化语义见输出 JSON 的 cost_model 字段）：
  - 误收 = unsafe & p < T_accept（成本 C1）
  - 漏收 = unsafe & p < T_reject = 误收 ∪ unsafe_uncertain（成本 C2）
  - 人工审查 = T_accept <= p < T_reject 的单元（成本 C3）
  total = C1*n_误收 + C2*n_漏收 + C3*n_uncertain。
代价曲线：固定 T_reject，等间距扫描人工审查阈值 tau（数据空间等距，见 cost_curve
  scan 字段），accept: p < tau；uncertain: tau <= p < T_reject；reject: p >= T_reject。

输入：--run-root（evidence_v2 + LABELS，split=train）+ --frozen-op + --out（JSON 文件）。
纯 CPU。不读取、不修改任何模型/标签文件。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np


def _load_frozen_op(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and {"raw", "official"} <= set(raw):
        return raw
    raise ValueError(f"frozen-op {path} 缺少 raw/official 目标级结构")


def _frozen_entry(frozen_op: dict, target: str, model_kind: str | None) -> dict:
    tgt = frozen_op.get(target) or {}
    if not isinstance(tgt, dict):
        raise ValueError(f"frozen-op target {target!r} 结构非法")
    kinds = [k for k in tgt if isinstance(tgt[k], dict) and tgt[k].get("best_combo")]
    if not kinds:
        raise ValueError(f"frozen-op target {target!r} 无可用 model_kind")
    if model_kind is None:
        picked = "small_mlp" if "small_mlp" in kinds else (
            "standardized_logistic" if "standardized_logistic" in kinds else kinds[0])
    else:
        picked = model_kind
        if picked not in kinds:
            raise ValueError(f"model_kind {picked!r} 不在 frozen-op target {target!r}: {kinds}")
    entry = tgt[picked]
    op = entry.get("operating_points") or {}
    if not op or op.get("T_accept") is None or op.get("T_reject") is None:
        raise ValueError(
            f"frozen-op target {target!r} model_kind {picked!r} 缺 operating_points"
            f".T_accept/T_reject（cost model 依赖冻结三态阈值，不可省略）")
    return {"model_kind": picked, "combo": entry["best_combo"],
            "T_accept": float(op["T_accept"]), "T_reject": float(op["T_reject"])}


def _signal_idx(feat_keys: list[str], combo: str) -> list[int]:
    sig = []
    for g in combo.split("+"):
        for i, k in enumerate(feat_keys):
            if (g == "R" and k.startswith("raw_")) or \
               (g == "O" and k.startswith(("official_", "ro_", "repair_", "has_"))) or \
               (g == "V" and k.startswith("cv_")):
                sig.append(i)
    return sorted(set(sig))


def _X(rows, feat_keys, idx):
    full = np.asarray([[float(r["features"].get(k) or 0.0) for k in feat_keys]
                       for r in rows], dtype=float)
    return full[:, idx] if idx else np.zeros((len(rows), 1))


def _y(rows):
    return np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in rows])


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def ece(p, y, n_bins=10):
    p = np.asarray(p); y = np.asarray(y)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    e = 0.0; counts = 0
    for i in range(n_bins):
        m = (p >= bins[i]) & (p <= bins[i + 1]) if i == 0 else (p > bins[i]) & (p <= bins[i + 1])
        if not m.any():
            continue
        conf = p[m].mean(); acc = y[m].mean()
        e += len(p[m]) * abs(conf - acc)
        counts += len(p[m])
    return float(e / counts) if counts else None


def isotonic_pav(p, y):
    order = np.argsort(p)
    ps, ys = p[order], y[order].astype(float)
    start = [0]; ssum = [float(ys[0])]; cnt = [1]
    for i in range(1, len(ps)):
        start.append(i); ssum.append(float(ys[i])); cnt.append(1)
        while len(start) > 1:
            if ssum[-2] / cnt[-2] <= ssum[-1] / cnt[-1]:
                break
            ssum[-2] += ssum[-1]; cnt[-2] += cnt[-1]
            start.pop(); ssum.pop(); cnt.pop()
    vs = np.empty(len(ps))
    for bi in range(len(start)):
        b0 = start[bi]
        b1 = start[bi + 1] if bi + 1 < len(start) else len(ps)
        vs[b0:b1] = ssum[bi] / cnt[bi]
    return ps, vs


def _temperature_scale(p_tr, y_tr):
    best = (1.0, float("inf"))
    for T in np.arange(0.5, 3.01, 0.05):
        logit = np.log(np.clip(p_tr, 1e-7, 1 - 1e-7) / (1 - np.clip(p_tr, 1e-7, 1 - 1e-7)))
        pt = 1.0 / (1.0 + np.exp(-logit / T))
        b = brier(pt, y_tr)
        if b < best[1]:
            best = (float(T), b)
    return best[0]


def song_grouped_folds(rows, k=5, seed=0):
    rng = np.random.RandomState(seed)
    missing = {r["request_identity"] for r in rows if not r.get("song_id")}
    if missing:
        raise ValueError(
            f"song_id 缺失 {len(missing)} 个 request_identity（禁止降级为 request 级"
            f"分组：同歌多 request 会被拆进不同折造成歌级泄漏，review P2-3）")
    groups = sorted({r["song_id"] for r in rows})
    if len(groups) < k:
        raise ValueError(f"歌曲数 {len(groups)} < k={k}，无法 song-grouped 折")
    perm = rng.permutation(len(groups))
    folds = [[] for _ in range(k)]
    for i, gi in enumerate(perm):
        folds[i % k].append(groups[gi])
    out = []
    for fi, val_songs in enumerate(folds):
        val = [r for r in rows if r["song_id"] in set(val_songs)]
        tr = [r for r in rows if r["song_id"] not in set(val_songs)]
        out.append({"fold": fi, "train_songs": sorted({r["song_id"] for r in tr}),
                    "val_songs": val_songs, "train_rows": tr, "val_rows": val})
    return out


def _metric_table(p_va, yv, p_tr, y_tr):
    T = _temperature_scale(p_tr, y_tr)
    logit = np.log(np.clip(p_va, 1e-7, 1 - 1e-7) / (1 - np.clip(p_va, 1e-7, 1 - 1e-7)))
    pt = 1.0 / (1.0 + np.exp(-logit / T))
    ps_sorted, vs = isotonic_pav(p_tr, y_tr)
    pi = np.interp(p_va, ps_sorted, vs)
    return ({"brier": brier(p_va, yv), "ece": ece(p_va, yv)},
            {"T": T, "brier": brier(pt, yv), "ece": ece(pt, yv)},
            {"brier": brier(pi, yv), "ece": ece(pi, yv)},
            {"p": ps_sorted.tolist(), "v": vs.tolist()}, pi)


def _summary(values):
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    return {"mean": float(arr.mean()), "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
            "values": [None if v is None else float(v) for v in values]}


def sgcv_calibration_core(train_rows, frozen_entry, *, k=5, seed=0) -> dict:
    """对单个 target 做 song-grouped K 折 CV。train_rows 为 build_matrix 的 train 行。"""
    from lyricalign.research_v7.detector_v2_models import _make_trainer

    feat_keys = sorted({k for r in train_rows for k in r["features"]})
    idx = _signal_idx(feat_keys, frozen_entry["combo"])
    trainer = _make_trainer(frozen_entry["model_kind"], seed=seed)
    folds = song_grouped_folds(train_rows, k=k, seed=seed)
    fold_out = []
    pooled_p = {"raw": [], "isotonic": []}
    pooled_y = []
    for f in folds:
        tr, va = f["train_rows"], f["val_rows"]
        Xtr, ytr, Xva = _X(tr, feat_keys, idx), _y(tr), _X(va, feat_keys, idx)
        yv = _y(va)
        p_va = trainer(Xtr, ytr, Xva)
        p_tr = trainer(Xtr, ytr, Xtr)
        raw, temp, iso, iso_curve, pi = _metric_table(p_va, yv, p_tr, ytr)
        fold_out.append({
            "fold": f["fold"], "train_songs": f["train_songs"],
            "val_songs": f["val_songs"],
            "n_train": len(tr), "n_val": len(va), "n_unsafe_val": int(yv.sum()),
            "n_train_songs": len(f["train_songs"]), "n_val_songs": len(f["val_songs"]),
            "raw": raw, "temperature": temp, "isotonic": iso})
        pooled_p["raw"].append(p_va)
        pooled_p["isotonic"].append(pi)
        pooled_y.append(yv)
    p_all = {"raw": np.concatenate(pooled_p["raw"]),
             "isotonic": np.concatenate(pooled_p["isotonic"])}
    y_all = np.concatenate(pooled_y)
    pooled_oof = {m: {"brier": brier(p_all[m], y_all), "ece": ece(p_all[m], y_all)}
                  for m in p_all}
    summary = {}
    for method in ("raw", "temperature", "isotonic"):
        for metric in ("brier", "ece"):
            summary[f"{method}_{metric}"] = _summary(
                [fo[method][metric] for fo in fold_out])
    return {"k": k, "seed": seed, "model_kind": frozen_entry["model_kind"],
            "combo": frozen_entry["combo"],
            "n_train_songs": len({r["song_id"] for r in train_rows}),
            "n_units": len(train_rows),
            "folds": fold_out, "summary": summary, "pooled_oof": pooled_oof,
            "isotonic_curve_fold0": iso_curve}


def _quadrant_counts(p, y, T_accept, T_reject):
    acc = p < T_accept
    rej = p >= T_reject
    unc = ~acc & ~rej
    unsafe = y > 0.5
    return {
        "n_unsafe_accept": int(np.sum(unsafe & acc)),
        "n_unsafe_uncertain": int(np.sum(unsafe & unc)),
        "n_unsafe_reject": int(np.sum(unsafe & rej)),
        "n_safe_accept": int(np.sum(~unsafe & acc)),
        "n_safe_uncertain": int(np.sum(~unsafe & unc)),
        "n_safe_reject": int(np.sum(~unsafe & rej)),
        "n_accept": int(np.sum(acc)), "n_uncertain": int(np.sum(unc)),
        "n_reject": int(np.sum(rej)), "n_total": int(len(p))}


def cost_model(p_va, y_va, *, T_accept, T_reject, C1=10.0, C2=5.0, C3=1.0,
               n_scan=41) -> dict:
    p = np.asarray(p_va); y = np.asarray(y_va)
    frozen = _quadrant_counts(p, y, T_accept, T_reject)
    frozen_cost = (C1 * frozen["n_unsafe_accept"]
                   + C2 * (frozen["n_unsafe_accept"] + frozen["n_unsafe_uncertain"])
                   + C3 * frozen["n_uncertain"])
    grid = np.linspace(0, len(p) - 1, n_scan).astype(int)
    taus = np.unique(np.sort(p)[grid])
    curve = []
    for tau in taus:
        tau = min(float(tau), float(T_reject))
        q = _quadrant_counts(p, y, tau, T_reject)
        total = (C1 * q["n_unsafe_accept"]
                 + C2 * (q["n_unsafe_accept"] + q["n_unsafe_uncertain"])
                 + C3 * q["n_uncertain"])
        curve.append({"tau": float(tau),
                      "n_unsafe_accept": q["n_unsafe_accept"],
                      "n_unsafe_not_rejected": q["n_unsafe_accept"] + q["n_unsafe_uncertain"],
                      "n_uncertain": q["n_uncertain"],
                      "total_cost": float(total)})
    return {"costs": {"C1_false_accept": float(C1), "C2_missed_reject": float(C2),
                      "C3_review": float(C3)},
            "semantics": "total = C1*误收 + C2*漏收(unsafe未拒) + C3*uncertain; "
                         "accept: p<tau; uncertain: tau<=p<T_reject; reject: p>=T_reject",
            "frozen_thresholds": {"T_accept": T_accept, "T_reject": T_reject},
            "frozen_quadrants": frozen,
            "frozen_total_cost": float(frozen_cost),
            "scan": {"method": "data-space equal-spacing over sorted p, tau clamped to T_reject",
                     "n": len(curve)},
            "curve": curve}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--frozen-op", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--model-kind", default=None,
                   help="缺省：small_mlp > standardized_logistic > 首个可用（与 PBAD 冻结一致）")
    p.add_argument("--c1", type=float, default=10.0)
    p.add_argument("--c2", type=float, default=5.0)
    p.add_argument("--c3", type=float, default=1.0)
    p.add_argument("--n-scan", type=int, default=41)
    a = p.parse_args(argv)

    from train_detector_v2 import build_matrix

    run_root = Path(a.run_root)
    frozen = _load_frozen_op(Path(a.frozen_op))
    bt = build_matrix(run_root / "evidence_v2", run_root / "LABELS.jsonl")

    result = {"schema": "research_v7_pbad_calibration_sgcv_v1",
              "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "run_root": str(run_root), "k": a.k, "seed": 0,
              "frozen_op": {t: _frozen_entry(frozen, t, a.model_kind) for t in ("raw", "official")}}
    for t in ("raw", "official"):
        rows = bt[t].get("train", [])
        if not rows:
            result[t] = {"status": "no_train_rows"}
            continue
        entry = _frozen_entry(frozen, t, a.model_kind)
        cv = sgcv_calibration_core(rows, entry, k=a.k, seed=0)
        cv["status"] = "ok"
        result[t] = cv
        result[t]["cost_model"] = cost_model(
            _pooled_oof_p(bt[t], entry, a.k), _pooled_oof_y(bt[t], a.k),
            T_accept=entry["T_accept"], T_reject=entry["T_reject"],
            C1=a.c1, C2=a.c2, C3=a.c3, n_scan=a.n_scan)
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(out_path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, out_path)
    print(json.dumps({"ok": True, "out": str(out_path),
                      "summary": {t: r.get("summary") for t, r in result.items()
                                  if isinstance(r, dict) and "summary" in r}},
                     ensure_ascii=False, indent=1))
    return 0


def _pooled_oof_p(rows_by_target, entry, k):
    from lyricalign.research_v7.detector_v2_models import _make_trainer
    rows = rows_by_target["train"]
    feat_keys = sorted({k for r in rows for k in r["features"]})
    idx = _signal_idx(feat_keys, entry["combo"])
    trainer = _make_trainer(entry["model_kind"], seed=0)
    parts = []
    for f in song_grouped_folds(rows, k=k, seed=0):
        tr, va = f["train_rows"], f["val_rows"]
        parts.append(trainer(_X(tr, feat_keys, idx), _y(tr), _X(va, feat_keys, idx)))
    return np.concatenate(parts)


def _pooled_oof_y(rows_by_target, k):
    rows = rows_by_target["train"]
    parts = []
    for f in song_grouped_folds(rows, k=k, seed=0):
        parts.append(_y(f["val_rows"]))
    return np.concatenate(parts)


if __name__ == "__main__":
    raise SystemExit(main())
