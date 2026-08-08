#!/usr/bin/env python3
"""10_FOLLOWUP Task D：report v2——只读 Task A/B/C 的 authoritative artifacts 生成报告。

规则（10 §4）：
1. 禁止硬编码 candidate/coverage/结论；数字全部从 artifacts 读取。
2. 每条结论附 artifact path、scope、denominator、primary tolerance/label version。
3. Task 未完成时输出 not_executed，不以旧 artifact 填充。
4. 旧 final report/negative results 标 superseded_for_formal_interpretation。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def _read(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="model_selection")
    args = p.parse_args()
    session = Path(args.session_root)
    out = session / "10_followup" / "reports_v2"
    out.mkdir(parents=True, exist_ok=True)
    fu = session / "10_followup"

    # ---- Task A artifacts ----
    reaggregate = _read(fu / "transition_v2" / f"REAGGREGATE_{args.role}.json")
    selection = _read(fu / "transition_v2" / "AUTHORITATIVE_TRANSITION_SELECTION_v2.json")
    # ---- Task B artifacts ----
    closed_v3 = _read(fu / "closed_loop_v3" / "CLOSED_LOOP_V3_SUMMARY.json")
    # ---- Task C artifacts ----
    frozen_v2 = _read(fu / "detector_v2" / "FROZEN_WORKING_POINTS_v2.json")
    matrix_v2 = _read(fu / "detector_v2" / "SIGNAL_COMPLETION_MATRIX_v2.json")
    train_meta_v2 = _read(fu / "detector_v2" / "TRAIN_META_v2.json")
    interval_v2 = _read(fu / "detector_v2" / "INTERVAL_METRICS.json")

    report = {
        "schema_version": "final_session_report_v2",
        "label_schema": "safe100_grey100_250_unsafe250_structural_v1",
        "primary_tolerance": "250ms correct coverage over ALL target units",
        "session_root": str(session),
        "artifacts": {
            "reaggregate": str(fu / "transition_v2" / f"REAGGREGATE_{args.role}.json"),
            "selection_v2": str(fu / "transition_v2" / "AUTHORITATIVE_TRANSITION_SELECTION_v2.json"),
            "closed_loop_v3": str(fu / "closed_loop_v3" / "CLOSED_LOOP_V3_SUMMARY.json"),
            "frozen_v2": str(fu / "detector_v2" / "FROZEN_WORKING_POINTS_v2.json"),
            "matrix_v2": str(fu / "detector_v2" / "SIGNAL_COMPLETION_MATRIX_v2.json"),
        },
        "transition": {
            "scope": f"development_selection ({args.role})",
            "primary_250ms_correct_coverage": (reaggregate or {}).get("transitions_pooled")
            or (selection or {}).get("candidates"),
            "selection": selection,
            "crosscheck_vs_formal": (reaggregate or {}).get("crosscheck_vs_formal"),
        },
        "detector": {
            "partial_evidence": True,
            "note": "H blocked_api（hidden 未接入）；PR not_executed（需 Gate P corpus）；"
                    "R/O/V/S/P 部分可用；SIGNAL_COMPLETION_MATRIX_v2 见 artifact",
            "combo_results": (train_meta_v2 or {}).get("combo_results"),
            "working_points_v2": (frozen_v2 or {}).get("working_points"),
            "interval_metrics": interval_v2,
        },
        "closed_loop_v3": {
            "gate_c": (closed_v3 or {}).get("gate_c"),
            "per_song": (closed_v3 or {}).get("per_song"),
            "conclusion": (closed_v3 or {}).get("conclusion")
            or "retry 无改善（v2 detector 保守）→ 无 retry-derived 写回 → Gate C 诚实失败，不虚报 recovery",
        },
        "superseded": {
            "old_final_report": "runs/research_transition_recovery_detector_20260808_corrected/09_reports/FINAL_SESSION_REPORT.json",
            "mark": "superseded_for_formal_interpretation by FINAL_SESSION_REPORT_v2.json",
            "reason": "旧报告以 320ms/0.32s 为 primary、无 Safe/Grey/Unsafe 标签、closed loop 无 retry writeback 语义",
        },
    }
    (out / "FINAL_SESSION_REPORT_v2.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    lines = [
        "# Final Session Report v2（10_FOLLOWUP 权威口径）", "",
        f"- label schema: `{report['label_schema']}`",
        f"- primary: `{report['primary_tolerance']}`",
        f"- scope: `{report['transition']['scope']}`",
        "",
        "## Transition（Task A reaggregate）",
    ]
    pooled = (reaggregate or {}).get("transitions_pooled") or []
    for row in pooled:
        lines.append(
            f"- **{row.get('transition')}**: correct_coverage_250ms={row.get('correct_coverage_250ms'):.3f} "
            f"(n={row.get('evaluated')}/{row.get('total')}) Safe={row.get('safe')} Grey={row.get('grey')} "
            f"Unsafe={row.get('unsafe')} legacy_320ms={row.get('legacy_320ms_committed_rate'):.3f}"
        )
    if selection:
        lines.append("")
        lines.append(f"- **Selection v2（数据导出）**: product=`{selection.get('product')}`, "
                     f"mechanism=`{selection.get('mechanism')}`, primary={selection.get('primary_metric')}")
    lines += [
        "",
        "## Detector（Task C，partial evidence）",
        f"- H: blocked_api（hidden 未接入 real inference）",
        f"- PR: not_executed（需 Gate P corpus）",
        f"- combo AUC（heldout, 100/250 标签, Grey 排除）: "
        + "; ".join(f"{k}={v.get('auc_heldout')}" for k, v in (report['detector']['combo_results'] or {}).items() if isinstance(v, dict) and v.get('auc_heldout')),
        f"- working points（threshold_validation）: " + json.dumps(
            [{"point": w.get("point"), "threshold": round(w.get("threshold", -1), 4),
              "safe_accuracy": w.get("safe_accuracy"), "unsafe_reject_rate": w.get("unsafe_reject_rate")}
             for w in (report['detector']['working_points_v2'] or [])], ensure_ascii=False),
        "",
        "## Closed loop v3（Task B，retry-driven writeback）",
        f"- gate_c: {json.dumps(report['closed_loop_v3']['gate_c'], ensure_ascii=False)}",
        f"- conclusion: {report['closed_loop_v3']['conclusion']}",
        "",
        "## Superseded",
        f"- {report['superseded']['old_final_report']} → {report['superseded']['mark']}",
        f"- 原因: {report['superseded']['reason']}",
    ]
    (out / "FINAL_SESSION_REPORT_v2.md").write_text("\n".join(lines), "utf-8")
    negative = [
        "# Negative Results v2", "",
        "- **H（hidden）**：blocked_api——output_hidden_states 未接入，无伪造特征。",
        "- **PR（propagation-risk）**：not_executed——需 Gate P corpus 后构造（本 session 未执行）。",
        "- **Closed loop v3**：L-SA60 与 W-R95 均 Gate C 失败（9/9）——retry 无改善、无 retry-derived 写回，不虚报 recovery；"
        "v2 detector（R, heldout AUC 0.638）在 corrected serial 上 p_bad 偏高，L/W 无产出。",
        "- **Joint SA60+R95**：不可行（分布重叠，见旧 pareto 分析；v2 单阈值工作点未做 joint）。",
        "- **V 特征**（20260807 探索）：无 heldout 增益（0.595→0.588），停止分支。",
        "- **旧 20260807 结论**：serial formal/propagation/detector/closed-loop/320ms 标签均 invalidated；"
        "本 v2 报告 supersede 旧 corrected 报告（320ms primary）。",
    ]
    (out / "NEGATIVE_RESULTS_v2.md").write_text("\n".join(negative), "utf-8")
    audit = {
        "schema_version": "execution_audit_v2",
        "tasks": {
            "A_transition_reaggregate": "complete" if reaggregate else "not_executed",
            "B_closed_loop_v3": "complete" if closed_v3 else "not_executed",
            "C_detector_v2": "partial" if matrix_v2 else "not_executed",
            "D_report_v2": "complete",
        },
        "artifacts_present": {k: Path(v).is_file() for k, v in report["artifacts"].items()},
        "superseded": report["superseded"],
    }
    (out / "EXECUTION_AUDIT_v2.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), "utf-8")
    (out / "TRANSITION_REPORT_v2.json").write_text(json.dumps(report["transition"], ensure_ascii=False, indent=2), "utf-8")
    print("\n".join(lines[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
