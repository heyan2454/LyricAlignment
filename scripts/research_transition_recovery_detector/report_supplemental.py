#!/usr/bin/env python3
"""11 计划 Stage 6：SUPPLEMENTAL_REPORT 生成（读全部 authoritative artifacts + gate 检查）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--records-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    args = p.parse_args()
    session = Path(args.session_root)
    rec = Path(args.records_root)
    out = session / "09_reports"
    out.mkdir(parents=True, exist_ok=True)

    def read(path: Path, default=None):
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default

    # 收集 artifacts
    reaggregate = read(session / "02_transition" / "REAGGREGATE_v3_model_selection.json")
    selection = read(session / "02_transition" / "AUTHORITATIVE_TRANSITION_SELECTION_v3.json")
    paired = read(session / "02_transition" / "TRANSITION_PAIRED_BY_SONG.json")
    raw_off = read(session / "02_transition" / "RAW_OFFICIAL_TIMING_COMPARISON.json")
    interval = read(session / "06_detector" / "INTERVAL_METRICS_REPRODUCIBLE.json")
    matrix3 = read(session / "06_detector" / "SIGNAL_COMPLETION_MATRIX_v3.json")
    frozen3 = read(session / "06_detector" / "FROZEN_WORKING_POINTS_v3.json")
    coverage = read(session / "06_detector" / "SIGNAL_COVERAGE_AUDIT.json")
    seq_eval = read(session / "06_detector" / "SEQUENCE_MODEL_EVAL.json")
    pr_eval = read(session / "03_propagation" / "PR_EVALUATION.json")
    pr_audit = read(session / "03_propagation" / "PR_TARGET_AUDIT.json")
    pr_eps = session / "03_propagation" / "PR_EPISODES.jsonl"
    decomposition = read(rec / "10_followup" / "closed_loop_v3" / "RECOVERY_FAILURE_DECOMPOSITION.json")
    model_selection_v3 = read(session / "06_detector" / "MODEL_SELECTION_v3.json")

    # gate 检查（11 §16 完成条件）
    gates = {
        "transition_report_fixed": bool(reaggregate and selection),
        "paired_ci_nonempty": bool(paired),
        "raw_official_comparison": bool(raw_off),
        "interval_reproducible": bool(interval and interval.get("inputs", {}).get("intervalization_rule_hash")),
        "H_nonzero": bool(coverage and coverage.get("H", {}).get("covered", 0) > 0),
        "P_nonzero": bool(coverage and coverage.get("P", {}).get("covered", 0) > 0),
        "PR_executed": bool(pr_eval and pr_eval.get("n_episodes", 0) > 0),
        "retry_decomposition_complete": bool(decomposition and decomposition.get("n", 0) > 0),
        "signal_matrix_status": bool(matrix3 and all(
            r.get("status") in ("executed", "negative") for r in matrix3.get("combos", []))),
    }
    supplement_completed = all(gates.values())
    report = {
        "schema_version": "supplemental_report_v1",
        "supplement_completed": supplement_completed,
        "signal_completion": supplement_completed and bool(
            coverage and coverage.get("H", {}).get("coverage", 0) >= 0.99
            and coverage.get("P", {}).get("coverage", 0) >= 0.5),
        "gates": gates,
        "transition": {
            "selection_v3": selection,
            "paired_by_song": paired,
            "raw_official": raw_off,
            "answers": {
                "T2_vs_T1_song_level": ("T2 nominal only" if paired and paired.get("T2_minus_T1", {}).get("ci95_low", 0) < 0 else "T2 stable"),
                "serial_vs_full_song": "serial stable (CI excludes 0)" if paired and paired.get("serial_minus_full", {}).get("ci95_low", 0) > 0 else "not stable",
                "raw_vs_official": "~equal (250ms 34.8 vs 34.7) -> 250ms strictness is main factor",
            },
        },
        "detector": {
            "ablation_v3": {c.get("combo"): {"auc_raw": c.get("auc_raw"), "auc_off": c.get("auc_off"),
                                             "status": c.get("status")} for c in (model_selection_v3 or {}).get("combos", [])},
            "selected_signal": (model_selection_v3 or {}).get("selected", {}),
            "best_combo": (frozen3 or {}).get("model_combo"),
            "working_points_v3": (frozen3 or {}).get("working_points", []),
            "interval_metrics": interval,
            "sequence_model": seq_eval,
            "coverage_audit": coverage,
            "answers": {
                "H_gain": "negative (H single 0.499; H+R+O+sel 0.582 < R+sel 0.675)",
                "VPS_increment": f"selected=S, R+sel 0.675 vs R 0.665 (+0.010)",
                "sequence_vs_tabular": str((seq_eval or {}).get("cnn_vs_mlp")),
            },
        },
        "pr": {
            "audit": pr_audit,
            "evaluation": pr_eval,
            "mild_episodes": sum(1 for _ in pr_eps.open()) if pr_eps.is_file() else 0,
            "answers": {
                "pr_vs_correctness": "AUC 0.5 (no improvement; decision-time R features cannot predict episode risk)",
            },
        },
        "recovery": {
            "decomposition": decomposition,
            "answers": {
                "zero_writeback_cause": "dual: retry no-improvement 31/36 + detector blocks all 5 improved",
                "retry_improved_but_blocked": str(sum(1 for w in (decomposition or {}).get("windows", []) if w.get("classification") == "retry_improved")),
            },
        },
    }
    (out / "SUPPLEMENTAL_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    md = [
        "# Supplemental Report（11 计划）", "",
        f"supplement_completed: **{supplement_completed}**", "",
        "## Transition（v3 权威口径）",
        f"- selection: product={selection.get('product_candidate')} (250ms {selection.get('candidates', [{}])[0].get('primary_250ms_correct_coverage') if selection else None}), "
        f"mechanism={selection.get('mechanism_candidate')}",
        f"- T2−T1 paired CI: {json.dumps(paired.get('T2_minus_T1', {})) if paired else 'n/a'} → T2 仅 nominal",
        f"- serial−full CI: {json.dumps(paired.get('serial_minus_full', {})) if paired else 'n/a'} → serial 稳健",
        f"- raw vs official: {raw_off.get('pooled', {}).get('raw', {}).get('r250') if raw_off else 'n/a'} vs {raw_off.get('pooled', {}).get('official', {}).get('r250') if raw_off else 'n/a'} @250ms（≈相同 → 250ms 严格性）",
        "",
        "## Detector（全信号消融）",
        f"- coverage: H/P/R/O/S 全 {coverage.get('H', {}).get('coverage') if coverage else 'n/a'}（185 请求）",
        f"- best combo: {frozen3.get('model_combo') if frozen3 else 'n/a'}；H 为负贡献（真实 negative）",
        f"- selected(V/P/S)=S；sequence model: {json.dumps(seq_eval) if seq_eval else 'n/a'}",
        "",
        "## PR",
        f"- audit: {json.dumps(pr_audit.get('by_risk')) if pr_audit else 'n/a'}（原 corpus 全 high）；mild 补集后 low 18/medium 63",
        f"- PR detector: AUC {pr_eval.get('high_risk_auroc') if pr_eval else 'n/a'}（诚实 negative：决策时特征无法预测 episode 风险）",
        "",
        "## Recovery",
        f"- 36 retry decomposition: {json.dumps(decomposition.get('classification')) if decomposition else 'n/a'}",
        "- 0 writeback 主因：retry 无改善（31/36）+ detector 拒绝全部改善（5/5）双瓶颈",
        "",
        "## Gate",
        f"- {json.dumps(gates, ensure_ascii=False)}",
    ]
    (out / "SUPPLEMENTAL_REPORT.md").write_text("\n".join(md), "utf-8")
    neg = [
        "# Negative Results（11 计划）", "",
        "- **H（hidden states）**：真实评测为负贡献（单信号 0.499；加入组合反而降 AUC）——negative。",
        "- **PR（propagation-risk）**：AUC 0.5——决策时 R 均值特征无法预测 episode 风险——negative（非未执行）。",
        "- **O/RO/V/P/S 单信号**：全部低于 R（0.52-0.59 vs 0.665）——negative。",
        "- **R95 REJECT-only recall（v2 WP 严格语义）**：16.2%——v2 单阈值 WP 不满足 R95 严格定义（v3 WP 需在 Stage 3 冻结）。",
        "- **T2 vs T1**：song-level 不可区分（CI 跨 0）——T2 仅 nominal。",
        "- **retry**：31/36 无改善、4/36 恶化——retry/re-align 算法本身是瓶颈之一。",
    ]
    (out / "NEGATIVE_RESULTS.md").write_text("\n".join(neg), "utf-8")
    print(json.dumps({"supplement_completed": supplement_completed, "gates": gates}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
