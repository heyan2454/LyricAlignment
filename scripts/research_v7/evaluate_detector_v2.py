#!/usr/bin/env python3
"""Detector V2 Phase3 evaluation：M4 song-heldout + family-LOO（18 §11/§12，19 §G3）。

输入：run1/evidence_v2/*.jsonl + LABELS.jsonl（复用 train_detector_v2.build_matrix，
含 split∈{train,validation,test}）+ 冻结 operating point（FROZEN_OPERATING_POINTS.json
或 --frozen-op 注入 {"raw": {...}, "official": {...}}，best_combo/T_accept/T_reject）。

M4 song-heldout：对 split=test 的 rows 用 frozen combo 的信号列 + 完整 train 拟合
standardized_logistic → predict test → tristate_from_p_bad(冻结阈值) →
tri_state_unit_metrics + interval_capture_metrics（unsafe runs→UnitInterval）→
按 family×target 分层。family-LOO：每个 family 从 train 排除重训 → 对留出 family 的
test rows 打分（同一冻结阈值）。

输出：M4_SONG_HELDOUT.json、FAMILY_LOO.json。test 只在最终评价使用（18 §12）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from train_detector_v2 import build_matrix, _unsafe_runs

SCHEMA_M4 = "research_v7_m4_song_heldout_v1"
SCHEMA_FAMILY_LOO = "research_v7_family_loo_v1"


def _load_frozen_op(path: Path) -> dict:
    """frozen op dict：双 target（raw/official）或旧式单 target 结构均接受。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and {"raw", "official"} <= set(raw):
        return raw
    return {"raw": raw, "official": raw}


def _family_map(labels_path: Path) -> dict[tuple[str, int, str], str]:
    """(request_identity, canonical_unit_id, target) -> family。"""
    out: dict[tuple[str, int, str], str] = {}
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        x = json.loads(line)
        out[(x["request_identity"], int(x["canonical_unit_id"]), x["target"])] = \
            x.get("family") or "unknown"
    return out


def _attach_family(by_target: dict, labels_path: Path) -> None:
    """build_matrix 的 rows 不含 family；从 LABELS 回填（mutation family 只分层不进特征）。"""
    fam = _family_map(labels_path)
    for target in ("raw", "official"):
        for rows in by_target[target].values():
            for r in rows:
                if not r.get("family"):
                    r["family"] = fam.get(
                        (r["request_identity"], r["canonical_unit_id"], r["target"]),
                        "unknown")


def _signal_indices(feat_keys: list[str], combo: str) -> list[int]:
    """信号列分组与 train_detector_v2.run_train 一致（H/R/O/V 前缀）。"""
    idx: list[int] = []
    for g in combo.split("+"):
        for i, k in enumerate(feat_keys):
            if (g == "R" and k.startswith("raw_")) \
                    or (g == "O" and k.startswith(("official_", "ro_", "repair_", "has_"))) \
                    or (g == "H" and k.startswith("hidden_")) \
                    or (g == "V" and k.startswith("cv_")):
                idx.append(i)
    return sorted(set(idx))


def _score(output, rows) -> tuple[dict, dict]:
    from lyricalign.research_v7.detector_v2_contract import UnitInterval
    from lyricalign.research_v7.detector_v2_metrics import (
        interval_capture_metrics, tri_state_unit_metrics)

    unsafe = {i for i, r in enumerate(rows) if r["label"] == "unsafe"}
    safe = {i for i, r in enumerate(rows) if r["label"] == "safe"}
    tri = tri_state_unit_metrics(output=output, unsafe_units=unsafe, safe_units=safe)
    intervals = [UnitInterval(s, e) for s, e in _unsafe_runs(sorted(unsafe))]
    iv = interval_capture_metrics(output=output, unsafe_intervals=intervals)
    return tri, iv


def _score_rows(train_rows, score_rows, *, combo: str, model_kind: str,
                t_accept: float, t_reject: float) -> tuple[dict, dict]:
    """冻结 combo 信号列 + 完整 train 拟合 → 对 score_rows 打分（冻结阈值三态）。"""
    import numpy as np
    from lyricalign.research_v7.detector_v2_intervals import tristate_from_p_bad
    from lyricalign.research_v7.detector_v2_models import _make_trainer

    feat_keys = sorted({k for r in train_rows for k in r["features"]})
    idxs = _signal_indices(feat_keys, combo)

    def _X(rows):
        full = np.asarray([[float(r["features"].get(k) or 0.0) for k in feat_keys]
                           for r in rows], dtype=float)
        return full[:, idxs] if idxs else np.zeros((len(rows), 1))

    ytr = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in train_rows])
    trainer = _make_trainer(model_kind, seed=0)
    p_bad = trainer(_X(train_rows), ytr, _X(score_rows))
    output = tristate_from_p_bad({i: float(p) for i, p in enumerate(p_bad)},
                                 t_accept, t_reject)
    return _score(output, score_rows)


def _target_op(frozen_op: dict, target: str) -> dict:
    op = frozen_op.get(target) or {}
    if not op or op.get("best_combo") is None or not op.get("operating_points"):
        return {}
    return op


def evaluate_m4_song_heldout(*, by_target: dict, frozen_op: dict,
                             model_kind: str = "standardized_logistic") -> dict:
    """split=test 全量 + family×target 分层三态/interval 指标。"""
    out: dict = {"schema": SCHEMA_M4, "model_kind": model_kind, "targets": {}}
    for target in ("raw", "official"):
        op = _target_op(frozen_op, target)
        train_rows = by_target[target].get("train", [])
        test_rows = by_target[target].get("test", [])
        if not op or not train_rows or not test_rows:
            out["targets"][target] = {"status": "insufficient_data",
                                      "n_train": len(train_rows), "n_test": len(test_rows)}
            continue
        op_pts = op["operating_points"]
        tri, iv = _score_rows(train_rows, test_rows, combo=op["best_combo"],
                              model_kind=model_kind,
                              t_accept=float(op_pts["T_accept"]),
                              t_reject=float(op_pts["T_reject"]))
        by_family: dict[str, dict] = {}
        for fam in sorted({r.get("family") for r in test_rows}):
            idx = [i for i, r in enumerate(test_rows) if r.get("family") == fam]
            fam_rows = [test_rows[i] for i in idx]
            tri_f, iv_f = _score_rows(train_rows, fam_rows, combo=op["best_combo"],
                                      model_kind=model_kind,
                                      t_accept=float(op_pts["T_accept"]),
                                      t_reject=float(op_pts["T_reject"]))
            by_family[fam] = {"n_units": len(fam_rows), "tri_unit_metrics": tri_f,
                              "interval_metrics": iv_f}
        out["targets"][target] = {
            "n_train": len(train_rows), "n_test": len(test_rows),
            "combo": op["best_combo"], "T_accept": op_pts["T_accept"],
            "T_reject": op_pts["T_reject"],
            "tri_unit_metrics": tri, "interval_metrics": iv, "by_family": by_family}
    return out


def evaluate_family_loo(*, by_target: dict, frozen_op: dict,
                        model_kind: str = "standardized_logistic") -> dict:
    """每 family 从 train 排除重训 → 对留出 family 的 test rows 打分。"""
    out: dict = {"schema": SCHEMA_FAMILY_LOO, "model_kind": model_kind, "targets": {}}
    for target in ("raw", "official"):
        op = _target_op(frozen_op, target)
        train_rows = by_target[target].get("train", [])
        test_rows = by_target[target].get("test", [])
        if not op:
            out["targets"][target] = {"status": "no_frozen_op",
                                      "n_train": len(train_rows), "n_test": len(test_rows)}
            continue
        op_pts = op["operating_points"]
        by_family: dict[str, dict] = {}
        for fam in sorted({r.get("family") for r in train_rows}):
            loo_train = [r for r in train_rows if r.get("family") != fam]
            fam_test = [r for r in test_rows if r.get("family") == fam]
            if not fam_test:
                by_family[fam] = {"n_train": len(loo_train), "n_test": 0}
                continue
            tri, iv = _score_rows(loo_train, fam_test, combo=op["best_combo"],
                                  model_kind=model_kind,
                                  t_accept=float(op_pts["T_accept"]),
                                  t_reject=float(op_pts["T_reject"]))
            by_family[fam] = {
                "n_train": len(loo_train), "n_test": len(fam_test),
                "combo": op["best_combo"],
                "protected_recall_95": tri["protected_recall"],
                "safe_accept_rate": tri["safe_accept_rate"],
                "unsafe_false_accept": tri["counts"]["unsafe_accept"],
                "unsafe_false_accept_rate": tri["unsafe_false_accept_rate"],
                "tri_unit_metrics": tri, "interval_metrics": iv}
        out["targets"][target] = {"n_train": len(train_rows), "n_test": len(test_rows),
                                  "combo": op["best_combo"], "by_family": by_family}
    return out


def _atomic_write(path: Path, payload) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--frozen-op", default=None,
                   help="冻结 op json；缺省 <run-root>/FROZEN_OPERATING_POINTS.json")
    p.add_argument("--model-kind", default="standardized_logistic")
    p.add_argument("--limit-requests", type=int, default=None)
    a = p.parse_args(argv)
    run_root = Path(a.run_root)
    by_target = build_matrix(run_root / "evidence_v2", run_root / "LABELS.jsonl",
                             limit_requests=a.limit_requests)
    _attach_family(by_target, run_root / "LABELS.jsonl")
    frozen_path = Path(a.frozen_op) if a.frozen_op else run_root / "FROZEN_OPERATING_POINTS.json"
    frozen = _load_frozen_op(frozen_path)
    m4 = evaluate_m4_song_heldout(by_target=by_target, frozen_op=frozen,
                                  model_kind=a.model_kind)
    floo = evaluate_family_loo(by_target=by_target, frozen_op=frozen,
                               model_kind=a.model_kind)
    out_dir = Path(a.out)
    _atomic_write(out_dir / "M4_SONG_HELDOUT.json", m4)
    _atomic_write(out_dir / "FAMILY_LOO.json", floo)
    summary = {t: {"combo": d.get("combo"), "n_test": d.get("n_test"),
                   "families": sorted(d.get("by_family", {}))}
               for t, d in m4["targets"].items()}
    print(json.dumps({"ok": True, "targets": summary, "out": str(out_dir)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
