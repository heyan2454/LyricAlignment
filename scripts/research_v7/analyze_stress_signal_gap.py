#!/usr/bin/env python3
"""stress 弱检测信号缺口分析（总体 review backlog #6，契约边界内只分析）。

对 stress2_run 的 mutation 后 forward evidence（H/R/O/V 特征）与 baseline_legal
对照，逐特征计算 rank-AUC + KS（判别 mutation family 的能力）。**契约边界**：
detector_v2_features 只消费 EvidenceRow（不消费 GT/mutation/family），本脚本
用 LABELS 的 family 仅作分组/对照，绝不传入特征函数。

输出：per-family top-K 特征表 + verdict（best_auc_all_families < 0.6 →
negative_no_signal）+ recommendation。schema: stress_signal_gap_v1。
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

_SCHEMA = "stress_signal_gap_v1"
VERDICT_THRESHOLD = 0.6


def rank_auc(x_pos: np.ndarray, x_neg: np.ndarray) -> float | None:
    """rank-based AUC（Mann-Whitney U / n_pos*n_neg）。单侧空返回 None。"""
    if len(x_pos) == 0 or len(x_neg) == 0:
        return None
    y = np.concatenate([np.ones(len(x_pos)), np.zeros(len(x_neg))])
    x = np.concatenate([x_pos, x_neg])
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    u = ranks[y == 1].sum() - len(x_pos) * (len(x_pos) + 1) / 2.0
    return float(u / (len(x_pos) * len(x_neg)))


def ks_stat(x_pos: np.ndarray, x_neg: np.ndarray) -> float | None:
    """两样本 KS 统计量（经验 CDF 最大差）。"""
    if len(x_pos) == 0 or len(x_neg) == 0:
        return None
    a = np.sort(np.asarray(x_pos, dtype=float))
    b = np.sort(np.asarray(x_neg, dtype=float))
    i = j = 0
    d = 0.0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            d = max(d, abs((i + 1) / len(a) - j / len(b)))
            i += 1
        else:
            d = max(d, abs(i / len(a) - (j + 1) / len(b)))
            j += 1
    return float(d)


def _load_rows(path: Path) -> list[dict]:
    """evidence 文件：JSON 数组（第 0 元素可能为 header dict，无 canonical_unit_id）。"""
    arr = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(arr, list):
        return []
    return [r for r in arr if isinstance(r, dict) and "canonical_unit_id" in r]


def analyze(*, run_root: Path, baseline_family: str = "baseline_legal",
            max_files: int | None = None, min_samples: int = 20) -> dict:
    from lyricalign.research_v7.detector_v2_evidence import (
        EvidenceRow, HiddenView, OfficialView, RawView,
    )
    from lyricalign.research_v7.detector_v2_features import build_neighbors, unit_feature_row

    def _sub_view(cls, d: dict) -> object:
        return cls(**{k: v for k, v in (d or {}).items()
                      if k in getattr(cls, "__dataclass_fields__", {})})

    labels_path = run_root / "LABELS.jsonl"
    fam_units: dict[str, list[dict]] = {}
    if labels_path.is_file():
        for line in labels_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            fam_units.setdefault(r.get("family") or "unknown", []).append(r)

    ev_dir = run_root / "evidence_v2"
    files = sorted(ev_dir.glob("sha256:*.jsonl"))
    if max_files:
        files = files[:max_files]
    rows_by_key: dict[tuple, list[dict]] = {}
    for f in files:
        for row in _load_rows(f):
            key = (row.get("request_identity"), row.get("view_id"))
            rows_by_key.setdefault(key, []).append(row)
    for key in rows_by_key:
        rows_by_key[key].sort(key=lambda r: int(r["canonical_unit_id"]))

    def _features_for_unit(unit: dict) -> dict[str, float | None] | None:
        key = (unit.get("request_identity"), unit.get("view_id"))
        rows = rows_by_key.get(key)
        if not rows:
            return None
        cid = unit.get("canonical_unit_id")
        idx = next((i for i, r in enumerate(rows)
                    if int(r["canonical_unit_id"]) == int(cid)), None)
        if idx is None:
            return None
        evs = [EvidenceRow(
            request_identity=r.get("request_identity"),
            view_id=r.get("view_id"),
            canonical_unit_id=int(r["canonical_unit_id"]),
            raw=_sub_view(RawView, r.get("raw") or {}),
            official=_sub_view(OfficialView, r.get("official") or {}),
            hidden=_sub_view(HiddenView, r.get("hidden") or {}),
            cross_view=r.get("cross_view") or {},
        ) for r in rows]
        ev = evs[idx]
        feats = unit_feature_row(ev, build_neighbors(evs, idx), ev.cross_view)
        return {k: (None if v is None else float(v)) for k, v in feats.items()}

    families = sorted(f for f in fam_units if f != baseline_family)
    per_family: dict[str, dict] = {}
    baseline_feats: list[dict] = []
    for u in fam_units.get(baseline_family, []):
        f = _features_for_unit(u)
        if f:
            baseline_feats.append(f)
    all_aucs: list[float] = []
    for fam in families:
        fam_feats = []
        for u in fam_units.get(fam, []):
            f = _features_for_unit(u)
            if f:
                fam_feats.append(f)
        if len(baseline_feats) < min_samples or len(fam_feats) < min_samples:
            per_family[fam] = {"n_baseline": len(baseline_feats), "n_family": len(fam_feats),
                               "skipped": "insufficient_samples", "top_features": []}
            continue
        keys = sorted({k for d in fam_feats for k in d if d.get(k) is not None})
        scores = []
        for k in keys:
            pos = np.asarray([d[k] for d in fam_feats if d.get(k) is not None], dtype=float)
            neg = np.asarray([d[k] for d in baseline_feats if d.get(k) is not None], dtype=float)
            if len(pos) < min_samples or len(neg) < min_samples:
                continue
            auc = rank_auc(pos, neg)
            if auc is None:
                continue
            disc = max(auc, 1.0 - auc)
            scores.append({"feature": k, "auc": round(auc, 4), "discriminative_auc": round(disc, 4),
                           "ks": round(ks_stat(pos, neg), 4) if ks_stat(pos, neg) is not None else None})
            all_aucs.append(disc)
        scores.sort(key=lambda s: -s["discriminative_auc"])
        per_family[fam] = {"n_baseline": len(baseline_feats), "n_family": len(fam_feats),
                           "best": scores[0] if scores else None,
                           "top_features": scores[:5]}
    best_auc = max(all_aucs) if all_aucs else 0.0
    verdict = "negative_no_signal" if best_auc < VERDICT_THRESHOLD else "weak_signal"
    families_over = [f for f in families
                     if (per_family.get(f, {}).get("best") or {}).get("discriminative_auc", 0) >= VERDICT_THRESHOLD]
    return {"schema": _SCHEMA, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_root": str(run_root), "baseline_family": baseline_family,
            "min_samples": min_samples, "max_files": max_files,
            "families_analyzed": [f for f in families
                                  if per_family.get(f, {}).get("skipped") is None],
            "per_family": per_family,
            "best_discriminative_auc": round(best_auc, 4),
            "families_over_threshold": families_over,
            "verdict": verdict,
            "verdict_threshold": VERDICT_THRESHOLD,
            "verdict_note": ("max-over-features 的判别 AUC 存在选择偏差未校正；且"
                             " %d/%d family 低于阈值 0.6——实质负结论：现有 H/R/O/V "
                             "特征空间对窗口级文本扰动无实用判别力"
                             % (len(families) - len(families_over), len(families))),
            "contract_boundary": ("只读 H/R/O/V 特征（unit_feature_row），family 仅用于分组；"
                                  "未扩展特征契约"),
            "recommendation": ("mutation 感知特征需扩展证据契约（如 posterior 距离、文本级"
                               "扰动度量），与 cross-view posterior 管线（backlog #4）对接；"
                               "repeat 类特征为起点" if verdict == "negative_no_signal"
                               else "仅个别 family 出现弱信号（如 repeated_section），整体"
                               "仍需特征契约扩展")}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--max-files", type=int, default=None)
    p.add_argument("--min-samples", type=int, default=20)
    a = p.parse_args(argv)
    result = analyze(run_root=a.run_root, max_files=a.max_files,
                     min_samples=a.min_samples)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(a.out.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, a.out)
    print(json.dumps({"ok": True, "out": str(a.out),
                      "verdict": result["verdict"],
                      "best_discriminative_auc": result["best_discriminative_auc"],
                      "families": result["families_analyzed"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
