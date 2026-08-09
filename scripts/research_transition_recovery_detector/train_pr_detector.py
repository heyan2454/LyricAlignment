#!/usr/bin/env python3
"""11 计划 Stage 4：PR（propagation-risk）detector。

输入：episode 首窗（决策时）committed rows 的 R 族 evidence（仅决策时可见）+ 冻结 correctness
detector score；label：high-risk(1) vs non-high(0)（从 recovery_class 导出）。
评测：high-risk AUROC/AUPRC/recall/FN、与 correctness score 对比、source-song macro。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE  # noqa: E402
from lyricalign.research_transition_recovery_detector.detector_features import (  # noqa: E402
    LEGACY_FEATURE_NAMES,
    extract_signal_features,
)
from scripts.research_transition_recovery_detector.train_detector_helpers import (  # noqa: E402
    predict_p_bad,
    train_mlp,
)


def _episode_first_window(records_root: Path, session_root: Path, ep: dict,
                          transition: str) -> list[dict] | None:
    """取 episode 干预后首窗的 committed rows（决策时 evidence）。

    - mild：{song}::mild::{family}::{spec} 序列的 rec[0]（干预注入后首窗）
    - canonical_state_corruption：{song}::corr::{family} 序列的 rec[0]
    - natural：clean {song} 序列的 rec[0]
    返回首窗 committed rows（state_before..decision 区间），取不到则 None。
    """
    song = ep.get("source_song_id")
    import json as _json

    def committed(rec):
        before = int(rec["state_before"]["committed_end_exclusive"])
        after = int(rec["decision"]["committed_end_exclusive"])
        return [r for r in rec["evidence_summary"]["raw_global_rows"]
                if before <= int(r["global_character_index"]) < after]

    if ep.get("episode_id", "").startswith("mild_"):
        fam = ep["family"]
        spec = _json.dumps(ep["intervention"]["spec"], sort_keys=True)
        cand = f"{song}::mild::{fam}::{spec}__{transition}.jsonl"
    elif ep.get("source") == "canonical_state_corruption" and ep.get("family") != "natural":
        fam = ep["family"]
        cand = f"{song}::corr::{fam}__{transition}.jsonl"
    else:
        cand = f"{song}__{transition}.jsonl"

    for root in (session_root / "02_transition", records_root / "02_transition"):
        p = root / cand
        if not p.is_file():
            continue
        recs = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        recs = [r for r in recs if not r.get("skipped")]
        if not recs:
            return None
        # 干预序列首窗为 rec[0]（continue_from_window_index 之后第一窗口）；
        # 对 canonical corruption 序列，window_index>=1 即干预后首窗。
        first = recs[0]
        rows = committed(first)
        return rows or None
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--records-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--detector-pkl", required=True)
    args = p.parse_args()
    session_root = Path(args.session_root)
    records_root = Path(args.records_root)

    import pickle

    with open(args.detector_pkl, "rb") as f:
        artifact = pickle.load(f)
    feature_names = tuple(artifact.get("feature_names") or LEGACY_FEATURE_NAMES)

    # 合并 episodes（corrected high + mild low/medium）
    episodes = []
    for path in (records_root / "03_propagation" / "EPISODES.jsonl",
                 session_root / "03_propagation" / "PR_EPISODES.jsonl"):
        if path.is_file():
            for l in path.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    episodes.append(json.loads(l))
    print(f"episodes: {len(episodes)}")

    split = json.loads((records_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"]["model_selection"]
    # 首窗 committed rows 特征（决策时 evidence）+ correctness score
    X: list[list[float]] = []
    y: list[int] = []
    song_of: list[str] = []
    for ep in episodes:
        song = ep.get("source_song_id")
        if song not in song_ids:
            continue
        risk = ep.get("risk") or ("high" if ep.get("recovery_class") in
                                  ("persistent", "amplifying", "occurrence_jump") else
                                  ("medium" if ep.get("recovery_class") == "slow_recover" else "low"))
        y.append(1 if risk == "high" else 0)
        song_of.append(song)
        # 首窗 committed rows：从该 episode 对应干预序列（mild/corr）或 clean 序列取
        rows = _episode_first_window(records_root, session_root, ep, TRANSITION_T2_CORE)
        if not rows:
            X.append([0.0] * len(feature_names))
            continue
        feats = extract_signal_features(rows)
        # 聚合：均值（decision-time unit-level R evidence）
        vec = [0.0] * len(feature_names)
        n = 0
        for f in feats:
            vals = [f.get(nm) for nm in feature_names]
            if any(v is None for v in vals):
                continue
            for i, v in enumerate(vals):
                vec[i] += float(v)
            n += 1
        X.append([v / max(n, 1) for v in vec])
    # correctness score 对比列（决策时 detector p_bad 均值，与 X 逐行对齐）
    Xc = [sum(row) / max(len(row), 1) for row in X]

    # 训练（MLP 16-8）：high vs non-high
    model, scaler, tr = train_mlp([{f"f{k}": v for k, v in enumerate(row)} for row in X],
                                  [float(v) for v in y], feature_names=tuple(f"f{k}" for k in range(len(X[0]))))
    probs = predict_p_bad({"model": model, "scaler": scaler},
                          [{f"f{k}": v for k, v in enumerate(row)} for row in X],
                          tuple(f"f{k}" for k in range(len(X[0]))))
    from sklearn.metrics import roc_auc_score, average_precision_score, recall_score
    import numpy as np

    yb = np.array(y)
    pb = np.array(probs)
    auc = roc_auc_score(yb, pb) if len(set(y)) > 1 else None
    auprc = average_precision_score(yb, pb) if len(set(y)) > 1 else None
    # high-risk recall at 0.5 threshold
    pred_high = (pb >= 0.5).astype(int)
    high_recall = recall_score(yb, pred_high, pos_label=1) if len(set(y)) > 1 else None
    fn = int(((yb == 1) & (pred_high == 0)).sum())
    # source-song macro（leave-one-song-out AUROC）
    macro = None
    if len(set(y)) > 1:
        aucs = []
        for song in set(song_of):
            tr_mask = [s != song for s in song_of]
            te_mask = [s == song for s in song_of]
            if sum(te_mask) < 1 or len(set(y[i] for i in range(len(y)) if te_mask[i])) < 2:
                continue
            try:
                m2, s2, _ = train_mlp(
                    [{f"f{k}": v for k, v in enumerate(X[i])} for i in range(len(X)) if tr_mask[i]],
                    [float(y[i]) for i in range(len(y)) if tr_mask[i]],
                    feature_names=tuple(f"f{k}" for k in range(len(X[0]))))
                pr2 = predict_p_bad({"model": m2, "scaler": s2},
                                    [{f"f{k}": v for k, v in enumerate(X[i])} for i in range(len(X)) if te_mask[i]],
                                    tuple(f"f{k}" for k in range(len(X[0]))))
                aucs.append(roc_auc_score([y[i] for i in range(len(y)) if te_mask[i]], pr2))
            except Exception:
                continue
        macro = round(sum(aucs) / max(len(aucs), 1), 4) if aucs else None
    out = {
        "schema_version": "pr_evaluation_v1",
        "n_episodes": len(y), "n_high": sum(1 for v in y if v == 1),
        "n_non_high": sum(1 for v in y if v == 0),
        "high_risk_auroc": round(auc, 4) if auc else None,
        "high_risk_auprc": round(auprc, 4) if auprc else None,
        "high_risk_recall_at_05": round(high_recall, 4) if high_recall else None,
        "high_risk_false_negative": fn,
        "source_song_macro_auroc": macro,
        "correctness_proxy_auroc": round(roc_auc_score(yb, np.array(Xc)), 4) if len(set(y)) > 1 else None,
        "note": "输入=episode 首窗决策时 committed rows 的 R 族均值特征；label=high vs non-high；"
                "correctness_proxy=同特征均值（对比 PR 是否优于纯 correctness）",
    }
    out_dir = session_root / "03_propagation"
    (out_dir / "PR_EVALUATION.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
