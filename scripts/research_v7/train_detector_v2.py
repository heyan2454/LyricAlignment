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


def _song_of(labels: list[dict]) -> dict[tuple[str, int, str], str]:
    """(request_identity, canonical_unit_id, target) -> song_id。"""
    return {(x["request_identity"], int(x["canonical_unit_id"]), x["target"]): x.get("song_id")
            for x in labels}


def build_matrix(evidence_dir: Path, labels_path: Path, *, limit_requests: int | None = None,
                 keep_labels: tuple[str, ...] = ("safe", "unsafe")):
    from lyricalign.research_v7.detector_v2_evidence import EvidenceRow, RawView, OfficialView, HiddenView
    from lyricalign.research_v7.detector_v2_features import unit_feature_row, build_neighbors

    labels = _load_labels(labels_path)
    unit_label = _unit_to_label(labels)
    unit_split = _split_of(labels)
    unit_song = _song_of(labels)
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
                if label not in keep_labels:
                    continue
                split = unit_split.get(key, "train")
                feats = unit_feature_row(ev, build_neighbors(evs, i), ev.cross_view)
                by_target[target][split].append(
                    {"request_identity": rid, "canonical_unit_id": ev.canonical_unit_id,
                     "target": target, "label": label, "features": feats,
                     "song_id": unit_song.get(key)})
    by_target["hidden_available_any"] = hidden_available_any
    return by_target


def _song_of(labels: list[dict]) -> dict[tuple[str, int, str], str]:
    """(request_identity, canonical_unit_id, target) -> song_id（22 §6.2 song-grouped）。"""
    return {(x["request_identity"], int(x["canonical_unit_id"]), x["target"]): x.get("song_id")
            for x in labels}


def constant_baselines(yv: np.ndarray, unsafe_units: set, safe_units: set) -> dict:
    """常量基线三态指标（22 §4.3/§7）：always-accept / always-uncertain / always-reject。

    在冻结阈值语义下：all-accept = 全部单元 p_bad=0（≤T_accept → accept）；
    all-reject = 全部 p_bad=1（≥T_reject → reject）；all-uncertain 用中等 p_bad 区间值。
    """
    from lyricalign.research_v7.detector_v2_contract import UnitInterval
    from lyricalign.research_v7.detector_v2_intervals import tristate_from_p_bad
    from lyricalign.research_v7.detector_v2_metrics import tri_state_unit_metrics

    out = {}
    n = len(yv)
    for name, p, ta, tr in (("always_accept", 0.0, 0.5, 0.9),
                            ("always_reject", 1.0, 0.5, 0.9),
                            ("always_uncertain", 0.5, 0.4, 0.6)):
        output = tristate_from_p_bad({i: float(p) for i in range(n)}, ta, tr)
        out[name] = tri_state_unit_metrics(output=output, unsafe_units=unsafe_units,
                                           safe_units=safe_units)
    return out


def run_train(*, by_target, out_dir: Path, model_kinds: tuple[str, ...] = ("standardized_logistic",),
              combos=None, hidden_available_any=False, min_safe_accept_rate: float = 0.0,
              source_song_grouped: bool = True):
    import numpy as np
    from lyricalign.research_v7.detector_v2_models import run_ablation, _make_trainer
    from lyricalign.research_v7.detector_v2_intervals import freeze_thresholds, tristate_from_p_bad
    from lyricalign.research_v7.detector_v2_contract import UnitInterval
    from lyricalign.research_v7.detector_v2_metrics import tri_state_unit_metrics, interval_capture_metrics, output_unit_states

    out_dir.mkdir(parents=True, exist_ok=True)
    selection: dict[str, dict] = {"models": {}}
    frozen: dict[str, dict] = {}
    best_per_target: dict[str, str] = {}

    for model_kind in model_kinds:
        for target, splits in by_target.items():
            if target == "hidden_available_any":
                continue
            train_rows = splits.get("train", [])
            val_rows = splits.get("validation", [])
            if not train_rows or not val_rows:
                selection["models"].setdefault(model_kind, {})[target] = {
                    "status": "insufficient_data",
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
            combos_used = combos or ["R", "O", "R+O"]
            # inner split（22 §6.2）：按 source song 集合 80/20（seed=0），同歌全部行同侧
            rng = np.random.RandomState(0)
            if source_song_grouped and train_rows and train_rows[0].get("song_id") is not None:
                songs = sorted({r.get("song_id") for r in train_rows})
                perm_songs = rng.permutation(len(songs))
                k = max(1, int(len(songs) * 0.8))
                tr_songs = {songs[i] for i in perm_songs[:k]}
                inner_train = [i for i, r in enumerate(train_rows) if r.get("song_id") in tr_songs]
                inner_val = [i for i, r in enumerate(train_rows) if r.get("song_id") not in tr_songs]
            else:
                n_tr = len(Xt)
                perm = rng.permutation(n_tr)
                k = max(1, int(n_tr * 0.8))
                inner_train, inner_val = perm[:k], perm[k:]
            result = run_ablation(X_by_signal, yt, signals=("H", "R", "O", "V"),
                                  split_indices=(inner_train, inner_val), model_kind=model_kind)
            selection["models"].setdefault(model_kind, {})[target] = result
            # 最优组合：val protected_recall_95 最高、safe_accept_rate 非零、R+O 优先
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
                         1 if combo == "R+O" else 0)
                if best is None or score > best[0]:
                    best = (score, combo, c)
            if best is None:
                frozen.setdefault(target, {})[model_kind] = {
                    "status": "no_ok_combo", "n_train": len(train_rows), "n_val": len(val_rows)}
                continue
            _, combo, combo_res = best
            # 用最优组合的模型（完整外部 train 重训）对 val 打分 → 冻结三态阈值（18 §10）
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
            op_points = freeze_thresholds(val_p_bad_map, val_labels,
                                          min_safe_accept_rate=min_safe_accept_rate)
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
                entry = {"best_combo": combo, "model_kind": model_kind,
                         "operating_points": op_points,
                         "tri_state_val": tri, "interval_val": iv,
                         "n_train": len(train_rows), "n_val": len(val_rows),
                         "n_unsafe_val": int(yv.sum()),
                         "n_train_songs": len({r.get("song_id") for r in train_rows}),
                         "n_val_songs": len({r.get("song_id") for r in val_rows}),
                         "note": "val frozen; test evaluation in Phase3"}
                frozen.setdefault(target, {})[model_kind] = entry

            # 选定模型（22 §4.3/§B）：达标（protected_recall_95 >= 0.95）优先，
            # 同达标比 safe_accept_rate，都不达标比 protected。
            def _entry_score(e: dict) -> tuple:
                op = e.get("operating_points") or {}
                prot = float(op.get("protected_recall_95") or op.get("protected_recall") or 0.0)
                return (prot >= 0.95, prot, op.get("safe_accept_rate", 0.0))
            if model_kind in frozen.get(target, {}):
                cur = frozen[target].get("best")
                cand = frozen[target][model_kind]
                if cur is None or _entry_score(cand) > _entry_score(cur):
                    frozen[target]["best"] = dict(cand)
                    best_per_target[target] = model_kind
            else:
                frozen.setdefault(target, {})[model_kind] = {
                    "best_combo": combo, "model_kind": model_kind, "status": "no_thresholds",
                    "n_train": len(train_rows), "n_val": len(val_rows)}

    # 常量基线（val 上，选定模型无关）
    if by_target and "models" in selection:
        for target, splits in by_target.items():
            if target == "hidden_available_any":
                continue
            val_rows = splits.get("validation", [])
            if not val_rows:
                continue
            yv = np.asarray([1.0 if r["label"] == "unsafe" else 0.0 for r in val_rows])
            unsafe_units = {i for i in np.where(yv == 1.0)[0].tolist()}
            safe_units = {i for i in np.where(yv == 0.0)[0].tolist()}
            frozen.setdefault(target, {})["constant_baselines"] = constant_baselines(
                yv, unsafe_units, safe_units)

    # 顶层兼容：消费方读 frozen[target]["best_combo"/"operating_points"]，用选定模型
    for target in list(frozen):
        best = frozen[target].get("best")
        if best:
            frozen[target]["best_combo"] = best["best_combo"]
            frozen[target]["model_kind"] = best["model_kind"]
            frozen[target]["operating_points"] = best["operating_points"]
            frozen[target]["tri_state_val"] = best["tri_state_val"]
            frozen[target]["interval_val"] = best["interval_val"]
            frozen[target].pop("best", None)

    selection["best_per_target"] = best_per_target
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
    p.add_argument("--labels-path", default=None,
                   help="LABELS.jsonl 覆盖（缺省 <run-root>/LABELS.jsonl；"
                        "Phase B 用 run1 evidence + run1_v2 修正标签）")
    p.add_argument("--model-kind", default="standardized_logistic",
                   help="兼容单模型参数（同 --model-kinds 单元素）")
    p.add_argument("--model-kinds", default=None,
                   help="逗号分隔模型阶梯：standardized_logistic,constrained_gbdt,small_mlp,"
                        "rule_baseline")
    p.add_argument("--min-safe-accept-rate", type=float, default=0.0,
                   help="双约束冻结：val safe_accept_rate 下限（22 §Phase B）")
    p.add_argument("--no-song-grouped", action="store_true",
                   help="inner split 退回 unit 级随机（默认按 source song 分组）")
    a = p.parse_args(argv)
    run_root = Path(a.run_root)
    labels_path = Path(a.labels_path) if a.labels_path else run_root / "LABELS.jsonl"
    by_target = build_matrix(run_root / "evidence_v2", labels_path,
                             limit_requests=a.limit_requests)
    model_kinds = tuple(x.strip() for x in (a.model_kinds or a.model_kind).split(",") if x.strip())
    result = run_train(by_target=by_target, out_dir=Path(a.out), model_kinds=model_kinds,
                       hidden_available_any=by_target.get("hidden_available_any", False),
                       min_safe_accept_rate=a.min_safe_accept_rate,
                       source_song_grouped=not a.no_song_grouped)
    frozen = result["frozen"]
    print(json.dumps({"ok": True,
                      "model_kinds": list(model_kinds),
                      "best_per_target": result["selection"].get("best_per_target", {}),
                      "targets": {t: (s.get("best_combo"), s.get("model_kind")) if isinstance(s, dict)
                                  else None for t, s in frozen.items()},
                      "out": str(Path(a.out))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
