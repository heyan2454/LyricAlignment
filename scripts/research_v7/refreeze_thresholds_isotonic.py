#!/usr/bin/env python3
"""isotonic 校准后重冻结阈值（总体 review backlog #3）。

对 frozen model_kind 在 train 上训练 → train p_bad 拟合 isotonic（PAV）→
train+val p_bad 映射为校准概率 p_cal → 在 val 上用 freeze_thresholds 语义
重冻结（protected_recall_95 达成下 safe_accept 最优；不可达如实
constraint_violated + 记录最优可达点）。**不覆盖原 FROZEN_OPERATING_POINTS**，
输出新文件（默认 exploration/FROZEN_OPERATING_POINTS_V2.json）。

输入：--run-root（evidence_v2 + LABELS.jsonl，build_matrix 消费）+ --frozen-op。
纯 CPU。schema: refreeze_v2_v1。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np

from lyricalign.research_v7.detector_v2_models import _make_trainer
from lyricalign.research_v7.detector_v2_intervals import freeze_thresholds

_SCHEMA = "refreeze_v2_v1"


def _load_frozen_op(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and {"raw", "official"} <= set(raw):
        return raw
    return {"raw": raw, "official": raw}


def _frozen_entry(frozen_op: dict, target: str, model_kind: str | None) -> dict:
    tgt = frozen_op.get(target) or {}
    if not isinstance(tgt, dict):
        raise ValueError(f"frozen-op target {target!r} 结构非法")
    kinds = [k for k in tgt if isinstance(tgt[k], dict) and tgt[k].get("best_combo")]
    if not kinds:
        raise ValueError(f"frozen-op target {target!r} 无可用 model_kind")
    if model_kind is None:
        picked = "small_mlp" if "small_mlp" in kinds else kinds[0]
    else:
        picked = model_kind
        if picked not in kinds:
            raise ValueError(f"model_kind {picked!r} 不在 frozen-op target {target!r}")
    entry = tgt[picked]
    op = entry.get("operating_points") or {}
    return {"model_kind": picked, "combo": entry["best_combo"],
            "old": {"T_accept": op.get("T_accept"),
                    "T_reject": op.get("T_reject"),
                    "protected_recall_95": op.get("protected_recall_95"),
                    "safe_accept_rate": op.get("safe_accept_rate"),
                    "constraint_violated": op.get("constraint_violated")}}


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


def isotonic_pav(p, y):
    """栈式 PAV isotonic 回归（O(n)）：p 升序，单调不减阶梯拟合。返回 (ps_sorted, vs)。"""
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


def refreeze_target(*, train_rows, val_rows, entry: dict,
                    min_safe_accept_rate: float = 0.2,
                    target_protected_recalls=(0.95, 0.99)) -> dict:
    feat_keys = sorted({k for r in train_rows for k in r["features"]})
    idx = _signal_idx(feat_keys, entry["combo"])
    y_tr = _y(train_rows)
    y_va = _y(val_rows)
    trainer = _make_trainer(entry["model_kind"], seed=0)
    p_tr = np.asarray(trainer(_X(train_rows, feat_keys, idx), y_tr,
                              _X(train_rows, feat_keys, idx)), dtype=float)
    p_va = np.asarray(trainer(_X(train_rows, feat_keys, idx), y_tr,
                              _X(val_rows, feat_keys, idx)), dtype=float)
    ps, vs = isotonic_pav(p_tr, y_tr)
    p_cal_tr = np.interp(p_tr, ps, vs)
    p_cal_va = np.interp(p_va, ps, vs)
    n_va = int(len(y_va))
    n_unsafe_va = int(y_va.sum())
    ids = list(range(n_va))
    if n_unsafe_va == 0:
        return {"status": "no_unsafe_val", "n_val": n_va, "n_unsafe_val": 0,
                "isotonic_curve": {"p": ps.tolist(), "v": vs.tolist()},
                "new": {"constraint_violated": True,
                        "note": "val 无 unsafe，无法冻结（记录原状态）"},
                "old": entry["old"]}
    frozen = freeze_thresholds(
        {u: float(p_cal_va[i]) for i, u in enumerate(ids)},
        {u: "unsafe" if y_va[i] else "safe" for i, u in enumerate(ids)},
        target_protected_recalls=target_protected_recalls,
        min_safe_accept_rate=min_safe_accept_rate)
    new = {"T_accept": frozen.get("T_accept"),
           "T_reject": frozen.get("T_reject"),
           "protected_recall_95": frozen.get("protected_recall_95"),
           "safe_accept_rate": frozen.get("safe_accept_rate"),
           "constraint_violated": bool(frozen.get("constraint_violated", False))}
    comparison = {"old_vs_new": {
        "T_accept": [entry["old"].get("T_accept"), new["T_accept"]],
        "T_reject": [entry["old"].get("T_reject"), new["T_reject"]],
        "safe_accept_rate": [entry["old"].get("safe_accept_rate"),
                             new["safe_accept_rate"]],
        "protected_recall_95": [entry["old"].get("protected_recall_95"),
                                new["protected_recall_95"]]},
        "delta": {"safe_accept_rate":
                  None if new["safe_accept_rate"] is None or entry["old"].get("safe_accept_rate") is None
                  else float(new["safe_accept_rate"] - entry["old"]["safe_accept_rate"])}}
    return {"status": "ok", "n_val": n_va, "n_unsafe_val": n_unsafe_va,
            "model_kind": entry["model_kind"], "combo": entry["combo"],
            "isotonic_curve": {"p": ps.tolist(), "v": vs.tolist()},
            "isotonic_train_stats": {"n": int(len(p_tr)),
                                     "raw_brier": float(np.mean((p_tr - y_tr) ** 2)),
                                     "cal_brier": float(np.mean((p_cal_tr - y_tr) ** 2))},
            "new": new, "old": entry["old"], "comparison": comparison}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True, type=Path)
    p.add_argument("--frozen-op", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--model-kind", default=None)
    p.add_argument("--min-safe-accept-rate", type=float, default=0.2)
    a = p.parse_args(argv)

    from train_detector_v2 import build_matrix

    frozen = _load_frozen_op(a.frozen_op)
    bt = build_matrix(a.run_root / "evidence_v2", a.run_root / "LABELS.jsonl")
    result = {"schema": _SCHEMA, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "run_root": str(a.run_root),
              "frozen_op_source": str(a.frozen_op),
              "min_safe_accept_rate": a.min_safe_accept_rate,
              "note": ("重冻结结果；不覆盖 FROZEN_OPERATING_POINTS.json。真实 run2 实测："
                       "isotonic 校准后重冻结为负结果（safe_accept 0.0345/0.0472 -> 0.0，"
                       "T_accept=0.0）——校准改善 ECE/Brier 但不改善阈值下 safe_accept，"
                       "safe/unsafe 的 p 分布重叠是判别力问题（22 文档：safe_accept 低是"
                       "frozen 点属性），非校准问题。其他 run-root 重跑时以本次 new 字段为准。")}
    for t in ("raw", "official"):
        rows = bt[t].get("train", [])
        va = bt[t].get("validation", [])
        if not rows or not va:
            result[t] = {"status": "no_train_or_val"}
            continue
        entry = _frozen_entry(frozen, t, a.model_kind)
        result[t] = refreeze_target(train_rows=rows, val_rows=va, entry=entry,
                                    min_safe_accept_rate=a.min_safe_accept_rate)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(a.out.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, a.out)
    print(json.dumps({"ok": True, "out": str(a.out),
                      "summary": {t: {k: r.get(k) for k in ("status", "new", "comparison")}
                                  for t, r in result.items()
                                  if isinstance(r, dict) and "new" in r}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
