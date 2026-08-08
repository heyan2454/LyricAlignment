"""train_detector 辅助函数：数据集构建 + MLP 训练/预测（跨脚本复用）。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE
from lyricalign.research_transition_recovery_detector.detector_features import FEATURE_NAMES


def build_dataset(session_root: Path, role: str, *, tolerance: float = 0.32,
                 timeline_manifest: str | None = None) -> tuple[list[dict], list[float | None], dict]:
    """从 T2 records 的 raw_global_rows（含完整特征字段）构建数据集。

    records 只评估 committed rows（detector 的目标：已提交/将提交的 units）。
    GT 从 LONG_TIMELINE_MANIFEST.jsonl 读取（song_id -> units）。
    timeline_manifest 显式传入；缺省时尝试 session 周边已知路径。
    """
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][role]
    manifest = {}
    candidates = [timeline_manifest, split.get("timeline_manifest"),
                  str(session_root.parent.parent / "runs/research_transition_recovery_detector_20260807/long_manifest_60/LONG_TIMELINE_MANIFEST.jsonl"),
                  str(session_root.parent / "long_manifest_60" / "LONG_TIMELINE_MANIFEST.jsonl")]
    tl_path = next((c for c in candidates if c and Path(c).is_file()), None)
    if tl_path is None:
        raise FileNotFoundError("LONG_TIMELINE_MANIFEST.jsonl not found; pass --timeline-manifest")
    for line in Path(tl_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            manifest[r["song_id"]] = {int(u["canonical_unit_id"]): u for u in r["canonical_units"]}
    features: list[dict] = []
    labels: list[float | None] = []
    n_songs = 0
    raw_rows_by_song: dict[str, list[dict]] = {}
    for song_id in song_ids:
        p = session_root / "02_transition" / f"{song_id}__{TRANSITION_T2_CORE}.jsonl"
        if not p.is_file():
            continue
        gt = manifest.get(song_id)
        if gt is None:
            continue
        n_songs += 1
        committed_rows = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("skipped"):
                continue
            before = rec["state_before"]["committed_end_exclusive"]
            after = rec["decision"]["committed_end_exclusive"]
            committed_rows.extend(
                r for r in rec["evidence_summary"]["raw_global_rows"]
                if before <= int(r["global_character_index"]) < after
            )
        raw_rows_by_song[song_id] = committed_rows
    # 派生字段先从原始行回算（records 存 official_fixed_* 与 topk，不存 diff/gap 本身）
    def _derived(r: dict) -> dict:
        out = {}
        pred = _num(r.get("fixed_global_start_sec"))
        off = _num(r.get("official_fixed_global_start_sec"))
        out["raw_official_start_diff_sec"] = abs(pred - off) if pred is not None and off is not None else None
        probs = r.get("raw_start_topk_probabilities")
        if isinstance(probs, (list, tuple)) and len(probs) >= 2:
            out["start_top2_gap_sec"] = float(probs[0]) - float(probs[1])
        else:
            out["start_top2_gap_sec"] = None
        return out

    # 动态特征集：只保留覆盖率 >=0.9 的字段（records 可能只存 legacy 字段子集）
    field_hits = {name: 0 for name in FEATURE_NAMES}
    n_all = sum(len(v) for v in raw_rows_by_song.values())
    for rows in raw_rows_by_song.values():
        for r in rows:
            merged = {**r, **_derived(r)}
            for name in FEATURE_NAMES:
                if merged.get(name) is not None:
                    field_hits[name] += 1
    active_features = tuple(name for name in FEATURE_NAMES if field_hits[name] / max(n_all, 1) >= 0.9)
    for song_id in song_ids:
        rows = raw_rows_by_song.get(song_id, [])
        gt = manifest.get(song_id)
        for r in rows:
            cid = int(r["global_character_index"])
            merged = {**r, **_derived(r)}
            feats = {name: merged.get(name) for name in active_features}
            features.append(feats)
            g = gt.get(cid)
            pred_start = _num(r.get("original_global_start_sec", r.get("fixed_global_start_sec")))
            if g is None or pred_start is None:
                labels.append(None)
            else:
                labels.append(1.0 if abs(pred_start - float(g["start_sec"])) > tolerance else 0.0)
    meta = {"role": role, "n_songs": n_songs, "n_units": len(features),
            "n_labeled": sum(1 for l in labels if l is not None),
            "n_safe": sum(1 for l in labels if l == 0), "n_unsafe": sum(1 for l in labels if l == 1),
            "feature_names": list(active_features)}
    return features, labels, meta


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def train_mlp(features: list[dict], labels: list[float | None], *, feature_names: tuple[str, ...]):
    if not features or not any(l is not None for l in labels):
        raise ValueError("no labeled training rows")
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
