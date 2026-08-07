"""train_detector 辅助函数：数据集构建 + MLP 训练/预测（跨脚本复用）。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE
from lyricalign.research_transition_recovery_detector.detector_features import FEATURE_NAMES


def build_dataset(session_root: Path, role: str, *, tolerance: float = 0.32) -> tuple[list[dict], list[float | None], dict]:
    """从 T2 records 的 raw_global_rows（含完整特征字段）构建数据集。

    records 只评估 committed rows（detector 的目标：已提交/将提交的 units）。
    GT 从 LONG_TIMELINE_MANIFEST.jsonl 读取（song_id -> units）。
    """
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][role]
    manifest = {}
    tl_path = split.get("timeline_manifest") or session_root.parent / "long_manifest_60" / "LONG_TIMELINE_MANIFEST.jsonl"
    if not Path(tl_path).is_file():
        for cand in session_root.glob("../../long_manifest_60/LONG_TIMELINE_MANIFEST.jsonl"):
            tl_path = cand
            break
    for line in Path(tl_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            manifest[r["song_id"]] = {int(u["canonical_unit_id"]): u for u in r["canonical_units"]}
    features: list[dict] = []
    labels: list[float | None] = []
    n_songs = 0
    for song_id in song_ids:
        p = session_root / "02_transition" / f"{song_id}__{TRANSITION_T2_CORE}.jsonl"
        if not p.is_file():
            continue
        gt = manifest.get(song_id)
        if gt is None:
            continue
        n_songs += 1
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("skipped"):
                continue
            before = rec["state_before"]["committed_end_exclusive"]
            after = rec["decision"]["committed_end_exclusive"]
            for r in rec["evidence_summary"]["raw_global_rows"]:
                cid = int(r["global_character_index"])
                if not (before <= cid < after):
                    continue
                feats = {name: r.get(name) for name in FEATURE_NAMES}
                if feats["raw_official_start_diff_sec"] is None:
                    # 从存储字段重新计算（若 original 不存在用 fixed）
                    pred = _num(r.get("fixed_global_start_sec"))
                    off = _num(r.get("official_fixed_global_start_sec"))
                    feats["raw_official_start_diff_sec"] = abs(pred - off) if pred is not None and off is not None else None
                if feats["start_top2_gap_sec"] is None and r.get("raw_start_topk_probabilities"):
                    probs = r["raw_start_topk_probabilities"]
                    if len(probs) >= 2:
                        feats["start_top2_gap_sec"] = float(probs[0]) - float(probs[1])
                features.append(feats)
                g = gt.get(cid)
                pred_start = _num(r.get("original_global_start_sec", r.get("fixed_global_start_sec")))
                if g is None or pred_start is None:
                    labels.append(None)
                else:
                    labels.append(1.0 if abs(pred_start - float(g["start_sec"])) > tolerance else 0.0)
    meta = {"role": role, "n_songs": n_songs, "n_units": len(features),
            "n_labeled": sum(1 for l in labels if l is not None),
            "n_safe": sum(1 for l in labels if l == 0), "n_unsafe": sum(1 for l in labels if l == 1)}
    return features, labels, meta


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def train_mlp(features: list[dict], labels: list[float | None], *, feature_names: tuple[str, ...]):
    """simple MLP（sklearn）：仅用有标签样本；特征缺失行丢弃。返回 (model, scaler, auc)。"""
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    X = []
    y = []
    for feats, label in zip(features, labels, strict=True):
        if label is None:
            continue
        row = [feats.get(name) for name in feature_names]
        if any(v is None for v in row):
            continue
        X.append([float(v) for v in row])
        y.append(int(label))
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    model = MLPClassifier(hidden_layer_sizes=(16, 8), max_iter=400, random_state=0).fit(Xs, y)
    auc = float(roc_auc_score(y, model.predict_proba(Xs)[:, 1]))
    return model, scaler, {"auc_train": auc, "n_train": len(y)}


def predict_p_bad(artifact: dict, features: list[dict], feature_names: tuple[str, ...]) -> list[float]:
    model = artifact["model"]
    scaler = artifact["scaler"]
    X = []
    valid = []
    for i, feats in enumerate(features):
        row = [feats.get(name) for name in feature_names]
        if any(v is None for v in row):
            continue
        X.append([float(v) for v in row])
        valid.append(i)
    if not X:
        return []
    Xs = scaler.transform(np.asarray(X, dtype=float))
    probs = model.predict_proba(Xs)[:, 1]
    out = [None] * len(features)
    for i, p in zip(valid, probs, strict=True):
        out[i] = float(p)
    return [p if p is not None else 0.5 for p in out]
