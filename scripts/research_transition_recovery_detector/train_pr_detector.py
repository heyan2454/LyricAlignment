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
        corr_after_intervention = False
    elif ep.get("source") == "canonical_state_corruption" and ep.get("family") != "natural":
        fam = ep["family"]
        cand = f"{song}::corr::{fam}__{transition}.jsonl"
        corr_after_intervention = True
    else:
        cand = f"{song}__{transition}.jsonl"
        corr_after_intervention = False

    external = Path("/root/autodl-tmp/lyricalign_sessions")
    for root in (session_root / "02_transition", records_root / "02_transition",
                 external / "20260809_signal_completion" / "02_transition",
                 external / "20260809_signal_completion" / "cache"):
        p = root / cand
        if not p.is_file():
            continue
        recs = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        recs = [r for r in recs if not r.get("skipped")]
        if not recs:
            return None
        # mild 序列 rec[0] 即干预后首窗；canonical corruption 序列需取首个 window_index>=1
        first = next((r for r in recs if r.get("window_index", 0) >= 1), None) \
            if corr_after_intervention else recs[0]
        if first is None:
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
    import numpy as np

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
    first_rows: list[list[dict]] = []
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
            first_rows.append([])
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
        # 保留每 episode 首窗 committed rows 供冻结 detector p_bad 计算
        first_rows.append(rows)
    # correctness 对比：用冻结 correctness detector p_bad（不再是 feature mean）
    correctness_scores: list[float] = []
    det_model = artifact.get("model")
    det_scaler = artifact.get("scaler")
    for rows in first_rows:
        if not rows or det_model is None or det_scaler is None:
            correctness_scores.append(0.0)
            continue
        det_feats = extract_signal_features(rows)
        try:
            pbs = predict_p_bad({"model": det_model, "scaler": det_scaler},
                                det_feats, feature_names)
            correctness_scores.append(float(np.mean(pbs)))
        except Exception:  # noqa: BLE001
            correctness_scores.append(0.0)

    from sklearn.metrics import roc_auc_score, average_precision_score
    import numpy as np

    yb = np.array(y)
    n = len(X)
    # OOF：leave-one-song-out，每 fold 在其余歌上训练，在 held-out 歌上 predict
    oof_probs = np.zeros(n, dtype=np.float64)
    loso_aucs: list[dict] = []
    for song in sorted(set(song_of)):
        tr_mask = np.array([s != song for s in song_of])
        te_mask = ~tr_mask
        if tr_mask.sum() < 5 or te_mask.sum() < 2:
            continue
        if len(set(int(v) for v in np.array(y)[tr_mask])) < 2:
            continue
        try:
            m2, s2, _ = train_mlp(
                [{f"f{k}": v for k, v in enumerate(X[i])} for i in range(n) if tr_mask[i]],
                [float(y[i]) for i in range(n) if tr_mask[i]],
                feature_names=tuple(f"f{k}" for k in range(len(X[0]))))
            pr2 = predict_p_bad({"model": m2, "scaler": s2},
                                [{f"f{k}": v for k, v in enumerate(X[i])} for i in range(n) if te_mask[i]],
                                tuple(f"f{k}" for k in range(len(X[0]))))
            te_idx = [i for i in range(n) if te_mask[i]]
            for j, i in enumerate(te_idx):
                oof_probs[i] = float(pr2[j])
            te_y = [int(y[i]) for i in range(n) if te_mask[i]]
            if len(set(te_y)) >= 2:
                loso_aucs.append({"song": song, "auc": roc_auc_score(te_y, pr2)})
        except Exception:  # noqa: BLE001
            continue

    valid = oof_probs > 0  # 有 OOF prediction 的样本
    oof_pooled_auc = roc_auc_score(yb[valid], oof_probs[valid]) if valid.sum() >= 4 and len(set(yb[valid])) >= 2 else None
    oof_pooled_auprc = average_precision_score(yb[valid], oof_probs[valid]) if valid.sum() >= 4 and len(set(yb[valid])) >= 2 else None
    macro = round(float(np.mean([d["auc"] for d in loso_aucs])), 4) if loso_aucs else None
    correctness_auroc = (
        roc_auc_score(yb, np.array(correctness_scores))
        if len(set(y)) > 1 and len(set(correctness_scores)) > 1 else None
    )

    out = {
        "schema_version": "pr_evaluation_v2",
        "n_episodes": len(y), "n_high": sum(1 for v in y if v == 1),
        "n_non_high": sum(1 for v in y if v == 0),
        "oof_pooled_auroc": round(oof_pooled_auc, 4) if oof_pooled_auc is not None else None,
        "oof_pooled_auprc": round(oof_pooled_auprc, 4) if oof_pooled_auprc is not None else None,
        "loso_macro_auroc": macro,
        "loso_song_aucs": [{"song": d["song"], "auc": round(d["auc"], 4)} for d in loso_aucs],
        "correctness_auroc": round(correctness_auroc, 4) if correctness_auroc is not None else None,
        "pr_vs_correctness": ("PR OOF AUROC vs frozen correctness detector AUROC; "
                              "held-out source-song-disjoint evaluation"),
        "note": "输入=episode 首窗决策时 committed rows 的 R 族均值特征；label=high vs non-high；"
                "correctness=冻结 correctness detector p_bad 聚合（max/mean）",
    }
    out_dir = session_root / "03_propagation"
    out_dir.mkdir(parents=True, exist_ok=True)
    # 兼容字段（report_supplemental / train_detector_v3 matrix PR 行读取）
    compat = {
        "schema_version": "pr_evaluation_v1",
        "n_episodes": out["n_episodes"], "n_high": out["n_high"], "n_non_high": out["n_non_high"],
        "high_risk_auroc": out["oof_pooled_auroc"],
        "high_risk_auprc": out["oof_pooled_auprc"],
        "source_song_macro_auroc": macro,
        "correctness_proxy_auroc": correctness_auroc,
        "correctness_auroc": correctness_auroc,
        "note": out["note"],
    }
    (out_dir / "PR_EVALUATION.json").write_text(json.dumps(compat, ensure_ascii=False, indent=2))
    (out_dir / "PR_EVALUATION_V2.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
