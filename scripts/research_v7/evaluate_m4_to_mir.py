#!/usr/bin/env python3
"""Detector V2 跨域评价：M4 frozen detector → MIR-1K 弱标签（18 §13，21 §1）。

输入：
- --m4-run-root <run1>：evidence_v2/*.jsonl + LABELS.jsonl（split=train 提供 M4 train 行）+
  FROZEN_OPERATING_POINTS.json（M4 冻结 op，best_combo/T_accept/T_reject，raw/official）
- --mir-run-root <mir_run>：evidence_v2/*.jsonl + LABELS.jsonl（MIR 弱标签 GT，
  split=mir1k，validation_basis=null）

方法：每个 target 用 M4 train 拟合冻结 combo 信号列的 standardized_logistic（seed=0）
→ 对 MIR 全部有 GT 的 rows 打分 → 冻结阈值三态 → tri_state_unit_metrics +
interval_capture_metrics → 按 family×target 分层。

输出 M4_TO_MIR_BY_FAMILY.json：每 target 的 pooled + by_family 指标；弱标签轴
validation_basis=weak_labeled_qwen_fa / note="not human GT"（21 §1：MIR 弱标签不与
M4 精确 GT 混合）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from evaluate_detector_v2 import _family_map, _load_frozen_op, _score_rows  # noqa: E402
from train_detector_v2 import build_matrix  # noqa: E402

SCHEMA = "research_v7_m4_to_mir_v1"


def _target_op(frozen_op: dict, target: str) -> dict:
    op = frozen_op.get(target) or {}
    if not op or op.get("best_combo") is None or not op.get("operating_points"):
        return {}
    return op


def evaluate_m4_to_mir(*, m4_train: dict, mir_rows: list[dict],
                       frozen_op: dict) -> dict:
    """M4 train 冻结打分器 → MIR rows 三态/interval，按 family 分层。"""
    out: dict = {"schema": SCHEMA, "targets": {}}
    for target in ("raw", "official"):
        op = _target_op(frozen_op, target)
        train_rows = m4_train.get(target, [])
        rows = [r for r in mir_rows if r.get("target") == target
                and r.get("label") in ("safe", "unsafe")]
        if not op or not train_rows or not rows:
            out["targets"][target] = {"status": "insufficient_data",
                                      "n_train": len(train_rows), "n_score": len(rows)}
            continue
        op_pts = op["operating_points"]
        tri, iv = _score_rows(train_rows, rows, combo=op["best_combo"],
                              model_kind="standardized_logistic",
                              t_accept=float(op_pts["T_accept"]),
                              t_reject=float(op_pts["T_reject"]))
        by_family: dict[str, dict] = {}
        for fam in sorted({r.get("family") for r in rows}):
            fam_rows = [r for r in rows if r.get("family") == fam]
            tri_f, iv_f = _score_rows(train_rows, fam_rows, combo=op["best_combo"],
                                      model_kind="standardized_logistic",
                                      t_accept=float(op_pts["T_accept"]),
                                      t_reject=float(op_pts["T_reject"]))
            by_family[fam] = {"n_units": len(fam_rows), "tri_unit_metrics": tri_f,
                              "interval_metrics": iv_f}
        out["targets"][target] = {
            "n_train": len(train_rows), "n_score": len(rows),
            "combo": op["best_combo"], "T_accept": op_pts["T_accept"],
            "T_reject": op_pts["T_reject"],
            "tri_unit_metrics": tri, "interval_metrics": iv, "by_family": by_family}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--m4-run-root", required=True)
    p.add_argument("--mir-run-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--frozen-op", default=None,
                   help="M4 冻结 op json；缺省 <m4-run-root>/FROZEN_OPERATING_POINTS.json")
    a = p.parse_args(argv)

    m4_root, mir_root = Path(a.m4_run_root), Path(a.mir_run_root)
    m4_bt = build_matrix(m4_root / "evidence_v2", m4_root / "LABELS.jsonl")
    _attach_family = _family_map(m4_root / "LABELS.jsonl")
    for target in ("raw", "official"):
        for rows in m4_bt[target].values():
            for r in rows:
                r["family"] = _attach_family.get(
                    (r["request_identity"], r["canonical_unit_id"], r["target"]),
                    "unknown")
    m4_train = {t: m4_bt[t].get("train", []) for t in ("raw", "official")}

    mir_bt = build_matrix(mir_root / "evidence_v2", mir_root / "LABELS.jsonl")
    mir_fam = _family_map(mir_root / "LABELS.jsonl")
    mir_rows: list[dict] = []
    for target in ("raw", "official"):
        for rows in mir_bt[target].values():
            for r in rows:
                r["family"] = mir_fam.get(
                    (r["request_identity"], r["canonical_unit_id"], r["target"]),
                    "unknown")
                mir_rows.append(r)

    frozen_path = Path(a.frozen_op) if a.frozen_op else m4_root / "FROZEN_OPERATING_POINTS.json"
    frozen = _load_frozen_op(frozen_path)
    result = evaluate_m4_to_mir(m4_train=m4_train, mir_rows=mir_rows, frozen_op=frozen)
    result["validation_basis"] = "weak_labeled_qwen_fa"
    result["note"] = "not human GT; MIR-1K 弱标签不与 M4 精确 GT 混合（21 §1）"
    result["scoring_subset"] = {
        "note": "n_score 仅统计 label∈{safe,unsafe} 的 units；ambiguous/grey/gt_unavailable "
                "不计入打分分母（LABEL_SUMMARY pooled 含全部 labeled units，二者口径不同）",
        "labels_included": ["safe", "unsafe"],
        "labels_excluded": ["ambiguous", "grey", "gt_unavailable"],
    }

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "M4_TO_MIR_BY_FAMILY.json"
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(out_dir), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    print(json.dumps({
        "ok": True, "out": str(path),
        "targets": {t: {"combo": d.get("combo"), "n_train": d.get("n_train"),
                        "n_score": d.get("n_score"),
                        "families": sorted(d.get("by_family", {}))}
                    for t, d in result["targets"].items()},
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
