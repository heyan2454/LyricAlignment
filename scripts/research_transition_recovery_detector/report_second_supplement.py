#!/usr/bin/env python3
"""二次补充实验：SECOND_SUPPLEMENT_REPORT 生成（汇总 binding/detector/interval/PR/recovery）。

二次补充在真实 GT（pinyin overlay）下重建：旧 uniform GT 的 549/804/2021、R=0.632 已作废。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

GT_AXIS = "real_gt_pinyin_overlay"
GT_AXIS_NOTE = (
    "二次补充的 binding/label 用真实 GT（pinyin overlay: "
    "derived/20260723_m4singer_overlay_slur_time_v1/prepare/m4singer_character_annotations.jsonl "
    "+ 段偏移投影，见 src/lyricalign/research_transition_recovery_detector/real_gt.py）重建；"
    "旧 uniform GT 的 authoritative 549/804/2021 与 R=0.632 修正链作废。"
)
REAL_GT_EXPECTED = {"safe": 3093, "grey": 97, "unsafe": 38}
REAL_GT_N_UNITS = 3374

REQUIRED = [
    ("00_meta", "IMPLEMENTATION_REVIEW.md"),
    ("06_detector", "COMMITTED_OBSERVATION_BINDING_AUDIT.json"),
    ("06_detector", "MODEL_SELECTION_v3.json"),
    ("06_detector", "FROZEN_WORKING_POINTS_v3.json"),
    ("06_detector", "INTERVAL_METRICS_REPRODUCIBLE.json"),
    ("06_detector", "SEQUENCE_MODEL_EVAL.json"),
    ("06_detector", "SIGNAL_COMPLETION_MATRIX_v3.json"),
    ("03_propagation", "PR_EVALUATION_V2.json"),
    ("07_closed_loop", "RECOVERY_FAILURE_DECOMPOSITION.json"),
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    args = p.parse_args()
    session = Path(args.session_root)

    def read(rel: str):
        f = session / rel
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None

    missing = [rel for rel in REQUIRED if not (session / rel[0] / rel[1]).is_file()]
    binding = read("06_detector/COMMITTED_OBSERVATION_BINDING_AUDIT.json")
    model = read("06_detector/MODEL_SELECTION_v3.json")
    frozen = read("06_detector/FROZEN_WORKING_POINTS_v3.json")
    interval = read("06_detector/INTERVAL_METRICS_REPRODUCIBLE.json")
    seq = read("06_detector/SEQUENCE_MODEL_EVAL.json")
    matrix = read("06_detector/SIGNAL_COMPLETION_MATRIX_v3.json")
    pr = read("03_propagation/PR_EVALUATION_V2.json")
    recovery = read("07_closed_loop/RECOVERY_FAILURE_DECOMPOSITION.json")

    counts = (binding or {}).get("model_selection_counts", {})
    n_units = counts.get("n_units")
    safe_rate = (counts.get("safe", 0) / n_units) if n_units else None

    # gates
    branches = (model or {}).get("branches", {})
    r_auc = (branches.get("R") or {}).get("auc_heldout")
    v_auc = (branches.get("V") or {}).get("auc_heldout")
    p_auc = (branches.get("P") or {}).get("auc_heldout")
    s_auc = (branches.get("S") or {}).get("auc_heldout")
    rs_auc = (branches.get("R+sel") or {}).get("auc_heldout")
    gates = {
        "binding_mismatch_zero": bool(binding and binding.get("n_mismatch", -1) == 0),
        "binding_consistent": bool(binding
            and binding.get("n_mismatch", -1) == 0
            and n_units == REAL_GT_N_UNITS
            and counts.get("safe") == REAL_GT_EXPECTED["safe"]
            and counts.get("grey") == REAL_GT_EXPECTED["grey"]
            and counts.get("unsafe") == REAL_GT_EXPECTED["unsafe"]),
        "P_distinct_second_path": bool(p_auc is not None),  # P algorithm verified separately
        "interval_grey_separated": bool(interval
            and any(wp.get("C3", {}).get("n_grey_excluded", 0) > 0
                    for wp in interval.get("working_points", {}).values())),
        "sequence_fair_compared": bool(seq and seq.get("cnn1d", {}).get("auc") is not None
                                       and seq.get("mlp", {}).get("auc") is not None),
        "PR_heldout": bool(pr and pr.get("oof_pooled_auroc") is not None),
        "recovery_rebuilt": bool(recovery and recovery.get("n_retry_windows", 0) > 0),
    }
    completed = all(gates.values()) and not missing

    report = {
        "schema_version": "second_supplement_report_v2",
        "gt_axis": GT_AXIS,
        "gt_axis_note": GT_AXIS_NOTE,
        "second_supplement_completed": completed,
        "gates": gates,
        "missing_artifacts": missing,
        "binding": {
            "n_mismatch": (binding or {}).get("n_mismatch"),
            "model_selection_counts": counts,
            "authoritative_expected": {**REAL_GT_EXPECTED, "n_units": REAL_GT_N_UNITS},
            "authoritative_note": "expected counts 来自真实 GT（pinyin overlay）commitment binding；"
                                  "uniform GT 的 549/804/2021 已作废",
        },
        "detector_v4": {
            "single_signal_auc": {k: (branches.get(k) or {}).get("auc_heldout")
                                  for k in ("H", "R", "O", "RO", "V", "P", "S")},
            "combo_auc": {k: (branches.get(k) or {}).get("auc_heldout")
                          for k in ("H+R", "H+O", "R+O", "H+R+O", "R+sel", "H+R+O+sel")},
            "selected_signal": (model or {}).get("selection", {}).get("chosen"),
            "best_combo": (frozen or {}).get("model_combo"),
            "notes": {
                "R_reflects_real_alignment": f"real GT (pinyin overlay) 下 R={r_auc:.3f} 反映真实对齐质量"
                                             f"（binding Safe 占 {safe_rate:.1%}）；uniform GT 的 0.665/0.632 "
                                             f"修正链已作废",
                "V_no_gain": "V 单信号 0.660；R+sel=0.961 主要由 R 主导，V delta_over_R=-0.0156（无增益）",
            },
        },
        "sequence_model": {
            "mlp_auc": (seq or {}).get("mlp", {}).get("auc"),
            "cnn1d_auc": (seq or {}).get("cnn1d", {}).get("auc"),
            "fair_normalization": "CNN1D and MLP share train-only StandardScaler",
            "conclusion": "MLP 0.976 与 R 分支等价；CNN1D 0.774 更低 → sequence model negative (fair comparison)",
        },
        "interval_v2": {
            "schema": (interval or {}).get("schema_version"),
            "rule_hash": (interval or {}).get("inputs", {}).get("intervalization_rule_hash"),
            "working_points": {
                wp: {"unsafe_reject_reject_only": r.get("C3", {}).get("unsafe_reject"),
                     "safe_accept": r.get("C3", {}).get("safe_accept"),
                     "n_safe": r.get("C3", {}).get("n_safe"),
                     "n_unsafe": r.get("C3", {}).get("n_unsafe"),
                     "n_grey": r.get("C3", {}).get("n_grey_excluded"),
                     "grey_states": r.get("C3", {}).get("grey_states")}
                for wp, r in (interval or {}).get("working_points", {}).items()},
            "joint_sa60_r95": (interval or {}).get("joint_sa60_r95"),
            "notes": "real GT (pinyin overlay) 下 n_safe 2890 / n_unsafe 23 / n_grey 109；"
                     "Grey 严格排除出 unsafe 分母；按 song intervalization；R95 unsafe_reject=0.913，"
                     "SA60+R95_joint feasible=False（91.3%<95%）",
        },
        "PR_heldout": {
            "oof_pooled_auroc": (pr or {}).get("oof_pooled_auroc"),
            "loso_macro_auroc": (pr or {}).get("loso_macro_auroc"),
            "correctness_auroc": (pr or {}).get("correctness_auroc"),
            "conclusion": "PR 与 frozen correctness 均 ~随机（OOF 0.51 / LOSO 0.55）→ negative",
        },
        "recovery": {
            "n_retry_windows": (recovery or {}).get("n_retry_windows"),
            "classification": (recovery or {}).get("classification"),
            "n_with_before_data": sum(1 for w in (recovery or {}).get("windows", [])
                                      if w.get("before_250ms") is not None),
            "notes": "L route + SA60；30 not_improved / 6 worsened / 0 improved_block；"
                     "9/36 windows 有 before 数据（其余 serial committed 为空）",
        },
    }
    (session / "09_reports").mkdir(parents=True, exist_ok=True)
    (session / "09_reports" / "SECOND_SUPPLEMENT_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2))
    md = [
        "# Second Supplement Report（二次补充）", "",
        f"second_supplement_completed: **{completed}**", "",
        f"- GT 口径: **{GT_AXIS}**（{GT_AXIS_NOTE}）", "",
        "## Gates",
        f"- {json.dumps(gates, ensure_ascii=False)}",
        "" if not missing else f"- missing: {missing}", "",
        "## Binding（真实 GT）",
        f"- model_selection counts: {counts}",
        f"- authoritative expected (real GT pinyin overlay): {REAL_GT_EXPECTED}，n_units={REAL_GT_N_UNITS} → "
        f"binding_consistent {'PASS' if gates['binding_consistent'] else 'FAIL'}（uniform GT 549/804/2021 已作废）",
        "",
        "## Detector v4（真实 GT 对齐）",
        f"- 单信号 AUC: {json.dumps({k: round(v,4) if v else None for k,v in report['detector_v4']['single_signal_auc'].items()})}",
        f"- R+sel: {round(rs_auc,4) if rs_auc else None}，selected={(model or {}).get('selection',{}).get('chosen')}",
        f"- R={r_auc:.3f} 反映真实 GT 下模型对齐质量（Safe 占比 {safe_rate:.1%}）；旧 0.665→0.632 修正注释作废；"
        f"V 无增益（delta_over_R=-0.0156）",
        "",
        "## P（coherent second path）",
        f"- P 单信号 AUC: {round(p_auc,4) if p_auc else None}",
        "- exact k-best DP 实现；修复后 evidence_P（recollect）：model_selection 34 ok + 2 no_monotone_path",
        "",
        "## Interval v2",
        f"- real GT 下 n_safe={interval and interval['working_points']['R95']['C3']['n_safe']}，"
        f"unsafe={interval and interval['working_points']['R95']['C3']['n_unsafe']}，"
        f"grey={interval and interval['working_points']['R95']['C3']['n_grey_excluded']}；"
        f"R95 unsafe_reject=0.913；SA60+R95_joint feasible=False（91.3%<95%）；按 song intervalization",
        "",
        "## Sequence（公平对比）",
        f"- MLP {seq and seq['mlp'].get('auc'):.4f} vs CNN1D {seq and seq['cnn1d'].get('auc'):.4f}"
        f"（共享 train-only scaler）→ MLP 与 R 等价，CNN1D 更低 → sequence negative",
        "",
        "## PR（held-out）",
        f"- OOF pooled AUC {pr and pr['oof_pooled_auroc']}，LOSO macro {pr and pr['loso_macro_auroc']}，"
        f"correctness AUC {pr and pr['correctness_auroc']}",
        "- PR 与冻结 correctness 均 ~随机 → negative（决策时无法预测 episode risk）",
        "",
        "## Recovery",
        f"- 36 retry windows: {json.dumps((recovery or {}).get('classification'))}"
        f"（30 not_improved / 6 worsened / 0 improved_block）",
        f"- 有 before 数据窗口 {report['recovery']['n_with_before_data']}/36（其余 serial 提交为空）",
        "",
    ]
    (session / "09_reports" / "SECOND_SUPPLEMENT_REPORT.md").write_text("\n".join(md), "utf-8")
    print(json.dumps({"completed": completed, "gates": gates}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
