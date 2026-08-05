#!/usr/bin/env python3
"""F1：p_bad 校准分析（自由规划，22 方向 B）。

对给定 run 的冻结模型 p_bad 输出，比较 raw / temperature / isotonic 三种校准的
Brier score 与 ECE（10-bin reliability）；输出 reliability diagram 数据点。

输入：--run-root（evidence_v2 + LABELS，split=train/validation）+ --frozen-op
（phaseB_final 冻结：model_kind/combo/T_accept/T_reject）。纯 CPU。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _load_frozen_op(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and {"raw", "official"} <= set(raw):
        return raw
    return {"raw": raw, "official": raw}


def brier(p, y):
    import numpy as np
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def ece(p, y, n_bins=10):
    import numpy as np
    p = np.asarray(p); y = np.asarray(y)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    e = 0.0; counts = 0
    for i in range(n_bins):
        m = (p > bins[i]) & (p <= bins[i + 1])
        if not m.any():
            continue
        conf = p[m].mean(); acc = y[m].mean()
        e += len(p[m]) * abs(conf - acc)
        counts += len(p[m])
    return float(e / counts) if counts else None


def temperature_scale(p_tr, y_tr, p_va, y_va):
    """单参数 temperature：T 使 10 折 val 内 Brier 最优（网格搜索）。"""
    import numpy as np
    best = (1.0, float("inf"))
    for T in np.arange(0.5, 3.01, 0.05):
        pt = 1.0 / (1.0 + np.exp(-(np.log(np.clip(p_va, 1e-7, 1 - 1e-7) / (1 - np.clip(p_va, 1e-7, 1 - 1e-7))) / T)))
        b = brier(pt, y_va)
        if b < best[1]:
            best = (float(T), b)
    return best[0]


def isotonic_pav(p, y):
    """栈式 PAV isotonic 回归（O(n)）：p 升序，单调不减的阶梯拟合。"""
    import numpy as np
    order = np.argsort(p)
    ps, ys = p[order], y[order].astype(float)
    # 栈：(块起点, 块和, 块计数)
    start = [0]; ssum = [float(ys[0])]; cnt = [1]
    for i in range(1, len(ps)):
        start.append(i); ssum.append(float(ys[i])); cnt.append(1)
        while len(start) > 1:
            v_prev = ssum[-2] / cnt[-2]
            v_cur = ssum[-1] / cnt[-1]
            if v_prev <= v_cur:
                break
            # 合并
            ssum[-2] += ssum[-1]; cnt[-2] += cnt[-1]
            start.pop(); ssum.pop(); cnt.pop()
    vs = np.empty(len(ps))
    for bi in range(len(start)):
        b0 = start[bi]
        b1 = start[bi + 1] if bi + 1 < len(start) else len(ps)
        vs[b0:b1] = ssum[bi] / cnt[bi]
    return ps, vs  # 阶梯：p 区间 -> 常数值


def calibrate(*, run_root: Path, frozen_op: dict, target: str = "official",
              n_bins: int = 10) -> dict:
    import numpy as np
    from train_detector_v2 import build_matrix
    from lyricalign.research_v7.detector_v2_models import _make_trainer

    bt = build_matrix(run_root / "evidence_v2", run_root / "LABELS.jsonl")
    tr = bt[target]["train"]; va = bt[target]["validation"]
    op = frozen_op.get(target) or {}
    if not op or op.get("model_kind") is None:
        return {"status": "no_frozen_op", "target": target}
    feat_keys = sorted({k for r in tr for k in r["features"]})
    combo = op["best_combo"]
    idx = [i for i, k in enumerate(feat_keys)
           if (combo and any(g in combo for g in ("R", "O", "V"))
               and ((g := None) is None))]
    # 信号列（与 evaluate 同口径）
    sig = []
    for g in combo.split("+"):
        for i, k in enumerate(feat_keys):
            if (g == "R" and k.startswith("raw_")) or (g == "O" and k.startswith(("official_", "ro_", "repair_", "has_"))) \
                    or (g == "V" and k.startswith("cv_")):
                sig.append(i)
    idx = sorted(set(sig))

    def _X(rows):
        full = np.asarray([[float(r["features"].get(k) or 0.0) for k in feat_keys]
                           for r in rows], dtype=float)
        return full[:, idx] if idx else np.zeros((len(rows), 1))

    yt = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in tr])
    yv = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in va])
    trainer = _make_trainer(op["model_kind"], seed=0)
    p_va = trainer(_X(tr), yt, _X(va))
    # 校准：temperature（val 上网格）、isotonic（train 上拟合 -> val 插值）
    T = temperature_scale(None, None, p_va, yv)
    pt = 1.0 / (1.0 + np.exp(-np.log(np.clip(p_va, 1e-7, 1 - 1e-7) / (1 - np.clip(p_va, 1e-7, 1 - 1e-7))) / T))
    p_tr = trainer(_X(tr), yt, _X(tr))
    ps_sorted, vs = isotonic_pav(p_tr, yt)
    pi = np.interp(p_va, ps_sorted, vs)

    out = {"target": target, "model_kind": op["model_kind"], "combo": combo,
           "n_val": len(yv), "n_unsafe_val": int(yv.sum()),
           "raw": {"brier": brier(p_va, yv), "ece": ece(p_va, yv, n_bins)},
           "temperature": {"T": T, "brier": brier(pt, yv), "ece": ece(pt, yv, n_bins)},
           "isotonic": {"brier": brier(pi, yv), "ece": ece(pi, yv, n_bins)}}
    # reliability diagram 数据（raw + calibrated）
    import numpy as np
    bins = np.linspace(0, 1, n_bins + 1)
    rel = []
    for name, pp in (("raw", p_va), ("temperature", pt), ("isotonic", pi)):
        pts = []
        for i in range(n_bins):
            m = (pp > bins[i]) & (pp <= bins[i + 1])
            if m.any():
                pts.append({"bin": i, "conf": float(pp[m].mean()), "acc": float(yv[m].mean()),
                            "n": int(m.sum())})
        rel.append({"method": name, "points": pts})
    out["reliability"] = rel
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--frozen-op", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    run_root = Path(a.run_root)
    frozen = _load_frozen_op(Path(a.frozen_op))
    result = {"schema": "research_v7_pbad_calibration_v1"}
    result["targets"] = {}
    for t in ("raw", "official"):
        result["targets"][t] = calibrate(run_root=run_root, frozen_op=frozen, target=t)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "PBAD_CALIBRATION.json"
    fd, tmp = tempfile.mkstemp(dir=str(out_dir), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
    print(json.dumps({"ok": True, "out": str(path),
                      "summary": {t: {m: v for m, v in d.items() if m in ("raw", "temperature", "isotonic")}
                                  for t, d in result["targets"].items()}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
