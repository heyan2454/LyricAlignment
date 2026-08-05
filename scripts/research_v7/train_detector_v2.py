#!/usr/bin/env python3
"""Detector V2 Phase2-train：真实数据八组合消融 + 三态阈值冻结（18 §9/§10，19 §G3）。

输入：run1/evidence_v2/*.jsonl（每行一请求的 EvidenceRow dict 数组）+ LABELS.jsonl
（request_identity/canonical_unit_id/target/label/family/split，split∈{train,validation,test}）。
按 18 §12：train 拟合、validation 冻结、test 只最终评价（本脚本默认只用 train/validation）。

输出：MODEL_SELECTION.json（八组合 H/R/O 消融）、FROZEN_OPERATING_POINTS.json
（最优组合 + T_accept/T_reject + val 三态主指标）。双 target（raw/official）独立。
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

sys_path_insert = None  # placeholder


def _load_labels(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _load_evidence_rows(dir_path: Path) -> dict[str, list[dict]]:
    """request_identity -> EvidenceRow dict 列表（跳过 failures.jsonl）。"""
    out: dict[str, list[dict]] = {}
    for f in sorted(dir_path.glob("*.jsonl")):
        if f.name.startswith("failures"):
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows = json.loads(line)
            if not rows:
                continue
            rid = rows[0].get("request_identity")
            if rid:
                out.setdefault(rid, rows)
    return out


def _unit_to_label(labels: list[dict]) -> dict[tuple[str, int, str], str]:
    """(request_identity, canonical_unit_id, target) -> label"""
    return {(x["request_identity"], int(x["canonical_unit_id"]), x["target"]): x["label"]
            for x in labels}


def _split_of(labels: list[dict]) -> dict[tuple[str, int, str], str]:
    """(request_identity, canonical_unit_id, target) -> split；validation 归一化 val。"""
    return {(x["request_identity"], int(x["canonical_unit_id"]), x["target"]):
            ("validation" if x["split"] == "validation" else x["split"]) for x in labels}


def build_matrix(evidence_dir: Path, labels_path: Path, *, limit_requests: int | None = None):
    from lyricalign.research_v7.detector_v2_evidence import EvidenceRow, RawView, OfficialView, HiddenView
    from lyricalign.research_v7.detector_v2_features import unit_feature_row, build_neighbors

    labels = _load_labels(labels_path)
    unit_label = _unit_to_label(labels)
    unit_split = _split_of(labels)
    evidence = _load_evidence_rows(evidence_dir)
    if limit_requests:
        evidence = dict(list(evidence.items())[:limit_requests])

    def _evrow(d: dict) -> EvidenceRow:
        raw = RawView(**(d.get("raw") or {}))
        off = OfficialView(**(d.get("official") or {}))
        h = d.get("hidden") or {}
        hidden = HiddenView(available=bool(h.get("available")), schema=h.get("schema"),
                            start=h.get("start") or {}, end=h.get("end") or {})
        return EvidenceRow(request_identity=d["request_identity"], view_id=d.get("view_id"),
                           canonical_unit_id=int(d["canonical_unit_id"]),
                           raw=raw, official=off, hidden=hidden,
                           cross_view=d.get("cross_view") or {})

    # 组装：每请求按 canonical 序排列 rows，unit_feature_row 用邻域
    by_target: dict[str, dict[str, list]] = {"raw": defaultdict(list), "official": defaultdict(list)}
    hidden_available_any = False
    for rid, rows in evidence.items():
        rows_sorted = sorted(rows, key=lambda r: int(r["canonical_unit_id"]))
        evs = [_evrow(r) for r in rows_sorted]
        hidden_available_any = hidden_available_any or any(ev.hidden.available for ev in evs)
        for target in ("raw", "official"):
            for i, ev in enumerate(evs):
                key = (rid, ev.canonical_unit_id, target)
                label = unit_label.get(key)
                if label not in ("safe", "unsafe"):
                    continue
                split = unit_split.get(key, "train")
                feats = unit_feature_row(ev, build_neighbors(evs, i), ev.cross_view)
                by_target[target][split].append(
                    {"request_identity": rid, "canonical_unit_id": ev.canonical_unit_id,
                     "target": target, "label": label, "features": feats})
    by_target["hidden_available_any"] = hidden_available_any
    return by_target


def run_train(*, by_target, out_dir: Path, model_kind: str = "standardized_logistic",
              combos=None, hidden_available_any=False):
    import numpy as np
    from lyricalign.research_v7.detector_v2_models import run_ablation
    from lyricalign.research_v7.detector_v2_intervals import freeze_thresholds, tristate_from_p_bad
    from lyricalign.research_v7.detector_v2_contract import UnitInterval
    from lyricalign.research_v7.detector_v2_metrics import tri_state_unit_metrics, interval_capture_metrics, output_unit_states

    out_dir.mkdir(parents=True, exist_ok=True)
    selection: dict[str, dict] = {}
    frozen: dict[str, dict] = {}
    for target, splits in by_target.items():
        if target == "hidden_available_any":
            continue
        train_rows = splits.get("train", [])
        val_rows = splits.get("validation", [])
        if not train_rows or not val_rows:
            selection[target] = {"status": "insufficient_data",
                                 "n_train": len(train_rows), "n_val": len(val_rows)}
            continue
        # 特征矩阵（信号分组：H/R/O/V）
        feat_keys = sorted({k for r in train_rows for k in r["features"]})
        def _X(rows):
            return np.asarray([[float(r["features"].get(k) or 0.0) for k in feat_keys]
                               for r in rows], dtype=float)
        Xt, Xv = _X(train_rows), _X(val_rows)
        yt = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in train_rows])
        yv = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in val_rows])
        # 信号分组：H 无特征（blocked）→ run_ablation 自动标含 H 组合 blocked
        sig_idx = {}
        for g in ("H", "R", "O", "V"):
            keys = [k for k in feat_keys
                    if (g == "R" and k.startswith("raw_")) or (g == "O" and k.startswith(("official_", "ro_", "repair_", "has_")))
                    or (g == "H" and k.startswith("hidden_")) or (g == "V" and k.startswith("cv_"))]
            sig_idx[g] = [feat_keys.index(k) for k in keys]
        X_by_signal = {g: Xt[:, idx] if idx else np.zeros((len(Xt), 1)) for g, idx in sig_idx.items()}
        # H blocked：evidence 的 hidden.available 全 False（G1 未完成）→ 从 signals 排除 H，
        # 含 H 组合不生成（等价 blocked，不选最优）。
        if not hidden_available_any:
            sig_idx.pop("H", None)
            X_by_signal.pop("H", None)
        combos_used = combos or ["H", "R", "O", "H+R", "H+O", "R+O", "H+R+O", "H+R+O+V"]
        # run_ablation 需完整 train/val 划分（内部冻结 operating points 用）；
        # 用外部 train_rows 的 80/20 随机划分做八组合选优，外部 val 留给最终冻结。
        n_tr = len(Xt)
        rng = np.random.RandomState(0)
        perm = rng.permutation(n_tr)
        k = max(1, int(n_tr * 0.8))
        inner_train, inner_val = perm[:k], perm[k:]
        result = run_ablation(X_by_signal, yt, signals=("H", "R", "O", "V"),
                              split_indices=(inner_train, inner_val), model_kind=model_kind)
        selection[target] = result
        # 最优组合：val protected_recall_95 最高、safe_accept_rate 非零、H+R+O+V 优先
        combos_by_name = {c.get("combo"): c for c in (result.get("combos") or [])}
        best = None
        for combo in combos_used:
            c = combos_by_name.get(combo)
            if not c or c.get("status") != "ok":
                continue
            op95 = ((c.get("operating_points") or {}).get("protected_recall_95") or {})
            if not op95.get("protected_recall"):
                continue
            score = (op95.get("protected_recall", 0), op95.get("safe_accept_rate", 0),
                     1 if combo == "H+R+O+V" else 0)
            if best is None or score > best[0]:
                best = (score, combo, c)
        if best is None:
            frozen[target] = {"status": "no_ok_combo", "n_train": len(train_rows), "n_val": len(val_rows)}
            continue
        _, combo, combo_res = best
        # 用最优组合的模型（完整外部 train 重训）对 val 打分 → 冻结三态阈值（18 §10）
        from lyricalign.research_v7.detector_v2_models import _make_trainer
        combo_signals = [s for s in combo.split("+") if s in sig_idx]
        idxs = [i for s in combo_signals for i in sig_idx[s]]
        Xt_c = Xt[:, idxs] if idxs else np.zeros((len(Xt), 1))
        Xv_c = Xv[:, idxs] if idxs else np.zeros((len(Xv), 1))
        trainer = _make_trainer(model_kind, seed=0)
        # _make_trainer 契约：trainer(Xtr, ytr, Xva) 直接返回 Xva 的 p_bad 概率数组
        val_p_bad = trainer(Xt_c, yt, Xv_c)
        # freeze_thresholds 契约：labels 为 unit_index -> "unsafe"/"safe" 的映射
        val_labels = {i: ("unsafe" if yv[i] == 1.0 else "safe") for i in range(len(yv))}
        val_p_bad_map = {i: float(p) for i, p in enumerate(val_p_bad)}
        op_points = freeze_thresholds(val_p_bad_map, val_labels)
        # 三态输出 + 主指标（18 §11）
        if op_points and op_points.get("T_accept") is not None and op_points.get("T_reject") is not None:
            output = tristate_from_p_bad({i: float(p) for i, p in enumerate(val_p_bad)},
                                         op_points["T_accept"], op_points["T_reject"])
            unit_states = {u: s.value for u, s in output_unit_states(output).items()}
            unsafe_units = {i for i in np.where(yv == 1.0)[0].tolist()}
            safe_units = {i for i in np.where(yv == 0.0)[0].tolist()}
            tri = tri_state_unit_metrics(output=output, unsafe_units=unsafe_units,
                                         safe_units=safe_units)
            intervals = [UnitInterval(start, end) for start, end in
                         _unsafe_runs(sorted(unsafe_units))]
            iv = interval_capture_metrics(output=output, unsafe_intervals=intervals)
            frozen[target] = {"best_combo": combo, "operating_points": op_points,
                              "tri_state_val": tri, "interval_val": iv,
                              "n_train": len(train_rows), "n_val": len(val_rows),
                              "n_unsafe_val": int(yv.sum()),
                              "note": "val frozen; test evaluation in Phase3"}
        else:
            frozen[target] = {"best_combo": combo, "status": "no_thresholds",
                              "n_train": len(train_rows), "n_val": len(val_rows)}
    _atomic_write(out_dir / "MODEL_SELECTION.json", selection)
    _atomic_write(out_dir / "FROZEN_OPERATING_POINTS.json", frozen)
    return {"selection": selection, "frozen": frozen}


def _unsafe_runs(sorted_unsafe: list[int]) -> list[tuple[int, int]]:
    """连续 unsafe unit 段 → [(start, end_exclusive)]。"""
    runs: list[tuple[int, int]] = []
    for u in sorted_unsafe:
        if runs and u == runs[-1][1]:
            runs[-1] = (runs[-1][0], u + 1)
        else:
            runs.append((u, u + 1))
    return runs


def _atomic_write(path: Path, payload) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit-requests", type=int, default=None)
    p.add_argument("--model-kind", default="standardized_logistic")
    a = p.parse_args(argv)
    run_root = Path(a.run_root)
    by_target = build_matrix(run_root / "evidence_v2", run_root / "LABELS.jsonl",
                             limit_requests=a.limit_requests)
    result = run_train(by_target=by_target, out_dir=Path(a.out), model_kind=a.model_kind,
                     hidden_available_any=by_target.get("hidden_available_any", False))
    print(json.dumps({"ok": True, "targets": {t: (s.get("best_combo") if isinstance(s, dict) else None)
                                               for t, s in result["frozen"].items()},
                      "out": str(Path(a.out))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
