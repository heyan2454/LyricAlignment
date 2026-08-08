"""train_detector_v2 辅助：v2 evidence adapter + 标签 + 阈值选择（跨脚本复用）。

v2 口径（10_FOLLOWUP_IMPLEMENTATION_PLAN §3）：
- 标签：Safe (|err|<=100ms) / Grey (100<err<=250ms) / Unsafe (>250ms)；Grey 排除出二元训练/冻结分母；
  label 只由 GT error 与 row 的 fixed_global_start_sec 决定（无 leak）。
- 特征族：R/O/RO/P/V/S/H/PR 全族提取（extract_signal_features + cross_window_features），
  缺失字段逐族记录 availability 与 missing reason；H 无 hidden 字段 → blocked_api，不伪造。
- V 族从 records 的 query 覆盖构造：同一 cid 跨窗观察（所有 record 的 raw_global_rows）。
- S 族 per-song 序列聚合（committed 行序）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE
from lyricalign.research_transition_recovery_detector.detector_features import (
    LEGACY_FEATURE_NAMES,
    SIGNAL_GROUPS,
    cross_window_features,
    extract_signal_features,
)

LABEL_SCHEMA = "safe100_grey100_250_unsafe250_structural_v1"
SAFE_MS = 0.100
GREY_MS = 0.250


def load_gt_manifest(timeline_manifest: str | None, session_root: Path) -> dict[str, dict[int, dict]]:
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    candidates = [timeline_manifest, split.get("timeline_manifest"),
                  str(session_root.parent / "research_transition_recovery_detector_20260807"
                      / "long_manifest_60" / "LONG_TIMELINE_MANIFEST.jsonl"),
                  str(session_root / "long_manifest_60" / "LONG_TIMELINE_MANIFEST.jsonl")]
    tl_path = next((c for c in candidates if c and Path(c).is_file()), None)
    if tl_path is None:
        raise FileNotFoundError("LONG_TIMELINE_MANIFEST.jsonl not found; pass --timeline-manifest")
    manifest: dict[str, dict[int, dict]] = {}
    for line in Path(tl_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            manifest[r["song_id"]] = {int(u["canonical_unit_id"]): u for u in r["canonical_units"]}
    return manifest


def collect_records(session_root: Path, song_ids: list[str]) -> dict[str, list[dict]]:
    """按角色收集 T2 records（02_transition/{song}__T2_core.jsonl）。"""
    out: dict[str, list[dict]] = {}
    for song_id in song_ids:
        p = session_root / "02_transition" / f"{song_id}__{TRANSITION_T2_CORE}.jsonl"
        if not p.is_file():
            continue
        recs = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        out[song_id] = [r for r in recs if not r.get("skipped")]
    return out


def committed_rows_from_records(records: list[dict]) -> list[dict]:
    """records 的 committed rows：cursor 区间内的 raw_global_rows（与 v1 同口径）。"""
    rows: list[dict] = []
    for rec in records:
        before = rec["state_before"]["committed_end_exclusive"]
        after = rec["decision"]["committed_end_exclusive"]
        rows.extend(
            r for r in rec["evidence_summary"]["raw_global_rows"]
            if before <= int(r["global_character_index"]) < after
        )
    return rows


def build_v2_dataset(
    session_root: Path, role: str, *, timeline_manifest: str | None = None,
) -> tuple[dict, list[dict], list[int | None], dict]:
    """返回 (meta, features, labels, coverage)。

    labels: None=无 GT 或 Grey 除外？—— Grey 保留三态编码：0=safe, 1=grey, 2=unsafe, None=无 GT。
    二元训练/冻结分母由调用方按 label!=1 过滤；此处保存完整三态以便分母审计。
    coverage: 每族 {available_rows, missing_rows, missing_reasons, song_coverage}。
    """
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][role]
    manifest = load_gt_manifest(timeline_manifest, session_root)
    records_by_song = collect_records(session_root, song_ids)

    observations_by_id: dict[int, list[dict]] = {}
    features: list[dict] = []
    labels: list[int | None] = []
    meta_rows: list[dict] = []
    n_intervals = 0
    n_songs = 0

    for song_id in song_ids:
        records = records_by_song.get(song_id)
        if not records:
            continue
        gt = manifest.get(song_id)
        if gt is None:
            continue
        n_songs += 1
        for rec in records:
            for row in rec["evidence_summary"]["raw_global_rows"]:
                observations_by_id.setdefault(int(row["global_character_index"]), []).append(row)
        rows = sorted(committed_rows_from_records(records), key=lambda r: int(r["global_character_index"]))
        if not rows:
            continue
        per_row = extract_signal_features(rows)
        v_feats = cross_window_features(observations_by_id)
        for row, unit_feats in zip(rows, per_row, strict=True):
            cid = int(row["global_character_index"])
            feats = {**unit_feats, **v_feats.get(cid, {})}
            features.append(feats)
            pred = _num(row.get("fixed_global_start_sec"))
            g = gt.get(cid)
            if g is None or pred is None:
                labels.append(None)
            else:
                err = abs(pred - float(g["start_sec"]))
                labels.append(0 if err <= SAFE_MS else (1 if err <= GREY_MS else 2))
        # interval = 连续 cid run（gap>1 视为新 interval）
        cids = [int(r["global_character_index"]) for r in rows]
        n_intervals += sum(1 for a, b in zip(cids, cids[1:]) if b != a + 1) + 1
        for row in rows:
            meta_rows.append({"song_id": song_id, "cid": int(row["global_character_index"])})

    coverage = coverage_audit(features, meta_rows)
    meta = {
        "role": role, "n_songs": n_songs, "n_units": len(features), "n_intervals": n_intervals,
        "n_safe": sum(1 for l in labels if l == 0), "n_grey": sum(1 for l in labels if l == 1),
        "n_unsafe": sum(1 for l in labels if l == 2),
        "n_unlabeled": sum(1 for l in labels if l is None),
        "label_schema": LABEL_SCHEMA,
    }
    return meta, features, labels, coverage


def coverage_audit(features: list[dict], meta_rows: list[dict]) -> dict:
    """每信号族 availability/coverage；missing reason 由字段级缺失反推。"""
    n = max(len(features), 1)
    families = dict(SIGNAL_GROUPS)
    families["legacy8"] = LEGACY_FEATURE_NAMES
    out: dict[str, dict] = {}
    for fam, names in families.items():
        avail_rows = sum(1 for f in features if all(f.get(name) is not None for name in names))
        missing_fields = {name: sum(1 for f in features if f.get(name) is None) for name in names}
        field_cov = {name: 1.0 - missing_fields[name] / n for name in names}
        reasons: list[str] = []
        if fam == "H" and avail_rows == 0:
            reasons.append("row has no hidden_* fields (output_hidden_states not exported) -> blocked_api")
        if any(f.get(n) is None for f in features[:1] or [{}] for n in names if n.startswith("v_")):
            reasons.append("cid observed in only one window (no cross-window displacement)")
        out[fam] = {
            "n_units": len(features),
            "n_available_rows": avail_rows,
            "coverage": round(avail_rows / n, 4),
            "missing_fields": {k: v for k, v in missing_fields.items() if v},
            "row_song_coverage": {"n_units": len(features), "n_songs": len({r["song_id"] for r in meta_rows})},
            "field_coverage": field_cov,
            "missing_reasons": reasons,
        }
    return out


def grey_excluded_binary(labels: list[int | None]) -> tuple[list[float | None], dict]:
    """二元标签：0=safe, 1=unsafe；Grey(1) → None 排除；None 保留无 GT。"""
    bin_labels: list[float | None] = []
    for l in labels:
        if l is None:
            bin_labels.append(None)
        elif l == 1:
            bin_labels.append(None)
        else:
            bin_labels.append(float(l) / 2.0)
    return bin_labels, {"n_grey_excluded": sum(1 for l in labels if l == 1)}


def family_union(*families: str) -> tuple[str, ...]:
    names: list[str] = []
    for fam in families:
        if fam == "legacy8":
            src = LEGACY_FEATURE_NAMES
        else:
            src = SIGNAL_GROUPS[fam]
        for n in src:
            if n not in names:
                names.append(n)
    return tuple(names)


def evaluate_heldout(model, scaler, features: list[dict], labels: list[float | None],
                     feature_names: tuple[str, ...]) -> dict:
    """heldout AUC（有标签行，特征全齐）；返回 auc 与 n。"""
    from sklearn.metrics import roc_auc_score

    X, y = [], []
    for feats, label in zip(features, labels, strict=True):
        if label is None:
            continue
        row = [feats.get(n) for n in feature_names]
        if any(v is None for v in row):
            continue
        X.append([float(v) for v in row])
        y.append(int(label))
    if len(set(y)) < 2:
        return {"auc": None, "n": len(y), "reason": "single class or empty heldout"}
    Xs = scaler.transform(np.asarray(X, dtype=float))
    probs = model.predict_proba(Xs)[:, 1]
    return {"auc": float(roc_auc_score(y, probs)), "n": len(y)}


def select_working_points(scores: list[float | None], labels: list[int | None]) -> list[dict]:
    """仅 threshold_validation role 使用；SA60/SA80/R95。Grey 不进分母；无 UNCERTAIN 概念按
    accept/reject 二分（SA：p<t -> ACCEPT 否则 UNCERTAIN；R95：p>=t -> REJECT 否则 UNCERTAIN）。"""
    safe = [p for p, l in zip(scores, labels, strict=True) if l == 0 and p is not None]
    unsafe = [p for p, l in zip(scores, labels, strict=True) if l == 2 and p is not None]
    n_grey = sum(1 for l in labels if l == 1)
    out = []
    for target, kind in ((0.60, "SA60"), (0.80, "SA80")):
        if not safe:
            out.append({"point": kind, "threshold": None, "status": "no_safe_units"})
            continue
        t = float(np.quantile(safe, target))
        acc = sum(1 for p in safe if p < t) / len(safe)
        rej = sum(1 for p in unsafe if p >= t) / len(unsafe) if unsafe else None
        out.append({"point": kind, "threshold": t, "decision_rule": "ACCEPT if p_bad < t else UNCERTAIN",
                    "safe_accuracy": round(acc, 4), "unsafe_reject_rate": rej,
                    "n_safe": len(safe), "n_unsafe": len(unsafe), "n_grey_excluded": n_grey})
    if unsafe:
        t = float(np.quantile(unsafe, 0.05))
        rej = sum(1 for p in unsafe if p >= t) / len(unsafe)
        acc = sum(1 for p in safe if p < t) / len(safe) if safe else None
        out.append({"point": "R95", "threshold": t, "decision_rule": "REJECT if p_bad >= t else UNCERTAIN",
                    "safe_accuracy": acc, "unsafe_reject_rate": round(rej, 4),
                    "n_safe": len(safe), "n_unsafe": len(unsafe), "n_grey_excluded": n_grey})
    else:
        out.append({"point": "R95", "threshold": None, "status": "no_unsafe_units"})
    return out


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
