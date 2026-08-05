#!/usr/bin/env python3
"""Detector V2 stress 评价（18 §13 replace 1/2/4/8 + missing + acoustic + repeated）。

输入：--run-root <stress_run>（evidence_v2 + LABELS.jsonl）+ M4 frozen op
（--frozen-op <run1>/FROZEN_OPERATING_POINTS.json，缺省 <run-root> 下）。

对每个 family×target：
- 有 GT 的 family（baseline_legal/crop_late/cursor_shift/end_early/end_late）：
  M4 train 冻结打分 → 三态/interval 指标（与 M4 song-heldout 同口径）。
- 无 GT 的 stress family（replace_*/missing_*/repeated_section/acoustic_difficulty）：
  无 occurrence GT（gt_ambiguity）→ 报告三态分布 accept/reject/uncertain 比例与
  reject_ratio（压力测试口径：detector 应对替换/缺失窗提高保护）。

输出 STRESS_EVAL.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from evaluate_detector_v2 import _family_map, _load_frozen_op, _score, _signal_indices  # noqa: E402
from train_detector_v2 import build_matrix  # noqa: E402

SCHEMA = "research_v7_stress_eval_v1"
GT_FAMILIES = ("baseline_legal", "crop_late", "cursor_shift", "end_early", "end_late")


def _score_stress(by_target: dict, frozen_op: dict) -> dict:
    """M4 frozen 打分：GT family 走指标；ambiguous family 走三态分布。"""
    import numpy as np
    from lyricalign.research_v7.detector_v2_intervals import tristate_from_p_bad
    from lyricalign.research_v7.detector_v2_models import _make_trainer
    from evaluate_detector_v2 import _score_rows

    out: dict = {"schema": SCHEMA, "targets": {}}
    for target in ("raw", "official"):
        op = frozen_op.get(target) or {}
        train_rows = by_target["m4_train"][target]
        score_rows = [r for r in by_target["stress"][target]]
        if not op or not train_rows or not score_rows:
            out["targets"][target] = {"status": "insufficient_data",
                                      "n_train": len(train_rows),
                                      "n_score": len(score_rows)}
            continue
        op_pts = op["operating_points"]
        combo = op["best_combo"]
        model_kind = op.get("model_kind") or "standardized_logistic"
        # 全量打分一次 → 三态分布（ambiguous family 用）
        feat_keys = sorted({k for r in train_rows for k in r["features"]})
        idxs = _signal_indices(feat_keys, combo)

        def _X(rows):
            full = np.asarray([[float(r["features"].get(k) or 0.0) for k in feat_keys]
                               for r in rows], dtype=float)
            return full[:, idxs] if idxs else np.zeros((len(rows), 1))

        ytr = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in train_rows])
        trainer = _make_trainer("standardized_logistic", seed=0)
        p_bad = trainer(_X(train_rows), ytr, _X(score_rows))
        output = tristate_from_p_bad({i: float(p) for i, p in enumerate(p_bad)},
                                     float(op_pts["T_accept"]), float(op_pts["T_reject"]))
        states = {}
        for iv in output.state_intervals:
            for i in range(int(iv.interval.start), int(iv.interval.end)):
                states[i] = iv.state.value
        by_family: dict[str, dict] = {}
        for fam in sorted({r.get("family") for r in score_rows}):
            idx = [i for i, r in enumerate(score_rows) if r.get("family") == fam]
            n = len(idx)
            st = {"accept": 0, "reject": 0, "uncertain": 0}
            for i in idx:
                st[states[i]] = st.get(states[i], 0) + 1
            fam_rows = [score_rows[i] for i in idx]
            has_gt = any(r["label"] in ("safe", "unsafe") for r in fam_rows)
            if has_gt:
                tri, iv = _score_rows(train_rows, fam_rows, combo=combo,
                                      model_kind=model_kind,
                                      t_accept=float(op_pts["T_accept"]),
                                      t_reject=float(op_pts["T_reject"]))
                by_family[fam] = {
                    "n_units": n, "gt_kind": "labels",
                    "n_labeled_units": sum(r["label"] in ("safe", "unsafe") for r in fam_rows),
                    "state_distribution": st,
                    "tri_unit_metrics": tri, "interval_metrics": iv}
            else:
                by_family[fam] = {
                    "n_units": n, "gt_kind": "no_occurrence_gt_ambiguity",
                    "state_distribution": st,
                    "accept_rate": st["accept"] / n, "reject_rate": st["reject"] / n,
                    "uncertain_rate": st["uncertain"] / n}
        out["targets"][target] = {
            "n_train": len(train_rows), "n_score": len(score_rows),
            "combo": combo, "model_kind": model_kind,
            "T_accept": op_pts["T_accept"], "T_reject": op_pts["T_reject"],
            "by_family": by_family}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--m4-run-root", required=True, help="M4 run1（train 行 + frozen op）")
    p.add_argument("--out", required=True)
    p.add_argument("--frozen-op", default=None)
    a = p.parse_args(argv)

    run_root, m4_root = Path(a.run_root), Path(a.m4_run_root)
    m4_bt = build_matrix(m4_root / "evidence_v2", m4_root / "LABELS.jsonl")
    m4_fam = _family_map(m4_root / "LABELS.jsonl")
    for target in ("raw", "official"):
        for rows in m4_bt[target].values():
            for r in rows:
                r["family"] = m4_fam.get(
                    (r["request_identity"], r["canonical_unit_id"], r["target"]), "unknown")

    stress_bt = build_matrix(run_root / "evidence_v2", run_root / "LABELS.jsonl",
                             keep_labels=("safe", "unsafe", "ambiguous", "grey"))
    stress_fam = _family_map(run_root / "LABELS.jsonl")
    stress_rows: dict[str, list] = {"raw": [], "official": []}
    for target in ("raw", "official"):
        for rows in stress_bt[target].values():
            for r in rows:
                r["family"] = stress_fam.get(
                    (r["request_identity"], r["canonical_unit_id"], r["target"]), "unknown")
                stress_rows[target].append(r)

    frozen_path = Path(a.frozen_op) if a.frozen_op else m4_root / "FROZEN_OPERATING_POINTS.json"
    frozen = _load_frozen_op(frozen_path)
    result = _score_stress(
        {"m4_train": {t: m4_bt[t].get("train", []) for t in ("raw", "official")},
         "stress": stress_rows}, frozen)

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "STRESS_EVAL.json"
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
