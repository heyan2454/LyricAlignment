"""Task C：detector Phase 4 重建（CPU）。

- v2 evidence adapter（helpers_v2）→ detector_train 训练 / model_selection heldout / threshold_validation 阈值
- 矩阵 H/R/O/H+R/H+O/R+O/H+R+O + legacy8 baseline + extended(=legacy8+V/S)
- H 无 hidden 数据 → blocked_api；PR 无 Gate P corpus → not_executed
- 输出 <session>/10_followup/detector_v2/{TRAIN_META_v2,SIGNAL_COMPLETION_MATRIX_v2,FROZEN_WORKING_POINTS_v2}.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from train_detector_helpers_v2 import (
    LABEL_SCHEMA,
    build_v2_dataset,
    evaluate_heldout,
    family_union,
    grey_excluded_binary,
    select_working_points,
)
from train_detector_helpers import train_mlp, predict_p_bad

HIDDEN_HELD = "no hidden_* fields in records (output_hidden_states not exported) -> blocked_api"

# 特征组合 -> (信号族列表, 说明)
MATRIX = [
    ("H", ("H",), "hidden 特征"),
    ("R", ("R",), "raw 几何"),
    ("O", ("O",), "official 几何"),
    ("H+R", ("H", "R"), "hidden+raw"),
    ("H+O", ("H", "O"), "hidden+official"),
    ("R+O", ("R", "O", "RO"), "raw+official(+交互)"),
    ("H+R+O", ("H", "R", "O", "RO"), "hidden+raw+official(+交互)"),
]
LEGACY8 = ("legacy8",)
EXTENDED = ("legacy8", "V", "S")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-root", default="runs/research_transition_recovery_detector_20260808_corrected")
    ap.add_argument("--timeline-manifest", default=None)
    ap.add_argument("--train-role", default="detector_train")
    ap.add_argument("--heldout-role", default="model_selection")
    ap.add_argument("--threshold-role", default="threshold_validation")
    ap.add_argument("--auc-gain-positive", type=float, default=0.005)
    args = ap.parse_args()

    session_root = Path(args.session_root).resolve()
    out_dir = session_root / "10_followup" / "detector_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[v2] building datasets (roles: {args.train_role}/{args.heldout_role}/{args.threshold_role})")
    train_meta, train_feats, train_labels, train_cov = build_v2_dataset(
        session_root, args.train_role, timeline_manifest=args.timeline_manifest)
    hold_meta, hold_feats, hold_labels, hold_cov = build_v2_dataset(
        session_root, args.heldout_role, timeline_manifest=args.timeline_manifest)
    th_meta, th_feats, th_labels, th_cov = build_v2_dataset(
        session_root, args.threshold_role, timeline_manifest=args.timeline_manifest)
    print(f"[v2] train {train_meta} | heldout {hold_meta} | threshold {th_meta}")

    train_bin, _ = grey_excluded_binary(train_labels)
    hold_bin, hold_grey = grey_excluded_binary(hold_labels)

    combo_results: dict[str, dict] = {}
    artifacts: list[dict] = []
    # 先跑 legacy8 与 extended 拿到 baseline 比较，再跑矩阵
    for combo, fams, note in MATRIX + [("legacy8", LEGACY8, "旧 8 特征 baseline"), ("extended", EXTENDED, "legacy8+V+S")]:
        names = family_union(*fams)
        # 动态特征集：只保留训练集字段级覆盖率 >=0.9 的特征
        # （records 缺 official_fixed_global_end_sec 等 end 类字段时 O 族部分特征不可用）
        field_cov = {}
        for _fam, _cov in train_cov.items():
            if isinstance(_cov, dict):
                field_cov.update(_cov.get("field_coverage", {}))
        names = tuple(n for n in names if field_cov.get(n, 0.0) >= 0.9)
        if "H" in fams and train_cov.get("H", {}).get("n_available_rows", 0) == 0:
            combo_results[combo] = {
                "status": "blocked_api", "families": list(fams),
                "reason": "hidden extraction 未接入 real inference（output_hidden_states 未导出），"
                          "覆盖审计见 detector_v2/COVERAGE_AUDIT.json", "features_used": list(names), "note": note,
            }
            artifacts.append({"combo": combo, "status": "blocked_api",
                              "reason": "hidden extraction unavailable (blocked_api, evidence in coverage audit)"})
            print(f"[v2] {combo}: blocked_api (H unavailable)")
            continue
        if not names:
            combo_results[combo] = {"status": "failed", "reason": "no features with coverage>=0.9",
                                    "families": list(fams), "features_used": [], "note": note}
            artifacts.append({"combo": combo, "status": "failed", "reason": "no features coverage>=0.9"})
            print(f"[v2] {combo}: failed (no features coverage>=0.9)")
            continue
            combo_results[combo] = {
                "status": "blocked_api", "families": list(fams),
                "reason": HIDDEN_HELD, "features_used": list(names), "note": note,
            }
            artifacts.append({"combo": combo, "status": "blocked_api", "reason": HIDDEN_HELD})
            print(f"[v2] {combo}: blocked_api (H unavailable)")
            continue
        try:
            model, scaler, tr = train_mlp(train_feats, train_bin, feature_names=names)
        except ValueError as e:
            combo_results[combo] = {"status": "failed", "reason": str(e), "families": list(fams),
                                    "features_used": list(names), "note": note}
            artifacts.append({"combo": combo, "status": "failed", "reason": str(e)})
            print(f"[v2] {combo}: failed ({e})")
            continue
        ho = evaluate_heldout(model, scaler, hold_feats, hold_bin, names)
        th_scores = predict_p_bad({"model": model, "scaler": scaler}, th_feats, names)
        combo_results[combo] = {
            "status": "executed", "families": list(fams), "features_used": list(names), "note": note,
            "auc_train": tr["auc_train"], "n_train": tr["n_train"],
            "auc_heldout": ho["auc"], "n_heldout": ho["n"],
            "n_grey_excluded": hold_grey["n_grey_excluded"],
            "threshold_role_n": sum(1 for l in th_labels if l is not None),
        }
        artifact = {
            "combo": combo, "status": "executed", "families": list(fams),
            "n_features": len(names), "features_used": list(names),
            "auc_train": tr["auc_train"], "n_train": tr["n_train"],
            "auc_heldout": ho["auc"], "n_heldout": ho["n"],
            "note": note,
        }
        artifacts.append(artifact)
        print(f"[v2] {combo}: train_auc={tr['auc_train']:.4f} heldout_auc={ho['auc']} n={ho['n']}")

    legacy_auc = combo_results["legacy8"].get("auc_heldout")
    for combo in list(combo_results):
        r = combo_results[combo]
        if r.get("status") == "executed" and combo != "legacy8":
            r["judgement"] = ("positive" if (r["auc_heldout"] is not None and legacy_auc is not None
                                             and r["auc_heldout"] >= legacy_auc + args.auc_gain_positive)
                              else "negative")

    # 阈值：选 heldout AUC 最优 executed combo（legacy8 除外）在 threshold_validation 上选点
    executed = {c: r for c, r in combo_results.items() if r.get("status") == "executed" and c != "legacy8"}
    best = max(executed, key=lambda c: executed[c]["auc_heldout"] or -1)
    best_r = executed[best]
    names = family_union(*best_r["families"])
    model, scaler, tr = train_mlp(train_feats, train_bin, feature_names=names)
    th_scores = predict_p_bad({"model": model, "scaler": scaler}, th_feats, names)
    working_points = select_working_points(th_scores, th_labels)
    for wp in working_points:
        wp["model_combo"] = best
        wp["role"] = args.threshold_role
    frozen = {
        "schema_version": LABEL_SCHEMA,
        "model_combo": best,
        "features_used": names,
        "train_role": args.train_role,
        "working_points": working_points,
        "transfer_note": "M4/MIR transfer 只读执行，不重调（未在此阶段运行）",
        "320ms_note": "所有标签/阈值/interval metrics 均用 100/250ms 边界，320ms 不影响任一结果",
    }

    train_meta_json = {
        "label_schema": LABEL_SCHEMA,
        "roles": {args.train_role: train_meta, args.heldout_role: hold_meta, args.threshold_role: th_meta},
        "coverage_by_role": {args.train_role: train_cov, args.heldout_role: hold_cov, args.threshold_role: th_cov},
        "combo_results": combo_results,
    }
    matrix_json = {
        "label_schema": LABEL_SCHEMA,
        "note": "8 信号族 + legacy8/extended 组合；blocked 分支不算 executed",
        "families": {
            f: {
                "status": ("blocked_api" if f == "H" and train_cov["H"]["n_available_rows"] == 0 else
                           ("not_executed" if f == "PR" else "executed")),
                "reason": (HIDDEN_HELD if f == "H" else
                           ("PR label requires Gate P corpus; not executed in this session" if f == "PR" else None)),
                "split": args.train_role, "n_units": train_meta["n_units"],
                "n_intervals": train_meta["n_intervals"],
                "coverage": train_cov.get(f, {}).get("coverage"),
                "metrics_artifact": str(out_dir / f"matrix_{f}.json") if f != "H" and f != "PR" else None,
            }
            for f in list(train_cov)
        },
        "combos": artifacts,
    }
    (out_dir / "TRAIN_META_v2.json").write_text(json.dumps(train_meta_json, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "SIGNAL_COMPLETION_MATRIX_v2.json").write_text(json.dumps(matrix_json, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "FROZEN_WORKING_POINTS_v2.json").write_text(json.dumps(frozen, indent=2, ensure_ascii=False), encoding="utf-8")
    for f, names in family_names_map().items():
        if f in ("H", "PR"):
            continue
        (out_dir / f"matrix_{f}.json").write_text(
            json.dumps({"family": f, "coverage": train_cov.get(f, {})}, indent=2), encoding="utf-8")
    for c, r in combo_results.items():
        if r.get("status") == "executed":
            (out_dir / f"combo_{c}.json").write_text(
                json.dumps({"combo": c, **r}, indent=2, ensure_ascii=False), encoding="utf-8")

    partial = "H blocked_api; PR not_executed"
    print(f"[v2] done -> {out_dir}")
    print(f"[v2] partial evidence: {partial} (仅 R/O/V/S/P 部分可用)")


def family_names_map():
    from lyricalign.research_transition_recovery_detector.detector_features import SIGNAL_GROUPS
    return {f: tuple(n) for f, n in SIGNAL_GROUPS.items()}


if __name__ == "__main__":
    main()
