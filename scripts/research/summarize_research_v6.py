#!/usr/bin/env python3
"""Generate a grounded Markdown report from completed pilot/formal artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PHASE_PURPOSE = {
    "E0": "同一 logits 下比较 raw、official 与新 decoder。",
    "E1": "评价自然错误的风险、安全边界和可修复区检测。",
    "E2": "用歌词/音频错配腐化测试 Detector 鲁棒性。",
    "E3": "评价 oracle/Detector 困难区的局部 decoder 修复。",
    "E4": "评价歌词剂量、自动选择和 96→3×32。",
    "E5": "评价 safe exact/-2/-4 音频与歌词同步动态分窗。",
    "E6": "评价 hard-core soft-context 与静音 cap。",
    "E7": "用状态注入和 GT reset 判断串行传播因果。",
    "E8": "评价 Detector 请求下的主/备输入 realign 及真实下游串行传播。",
    "E9": "评价模型支持的跨窗 cursor/window/text-budget beam 与独立行级粗定位 pilot。",
}


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def metric_macro(payload: dict[str, Any] | None, key: str) -> Any:
    return (((payload or {}).get("macro") or {}).get(key))


def grouped_rows(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((payload or {}).get("groups") or [])


def add_grouped_metric_table(
    lines: list[str], title: str, payload: dict[str, Any] | None, *, metric_key: str = "all_penalized_boundary_mae_sec",
) -> None:
    groups = grouped_rows(payload)
    if not groups:
        return
    group_keys = list((payload or {}).get("group_by") or [])
    lines += ["", f"### {title}", "", f"| {' / '.join(group_keys)} | items | MAE | coverage |", "|---|---:|---:|---:|"]
    for row in groups:
        group = row.get("group") or {}
        summary = row.get("summary") or {}
        label = " / ".join(str(group.get(key)) for key in group_keys)
        lines.append(
            f"| {label} | {summary.get('item_count', 0)} | {fmt(metric_macro(summary, metric_key))} | "
            f"{fmt(metric_macro(summary, 'coverage'))} |"
        )


def add_detector(lines: list[str], detector: dict[str, Any]) -> None:
    lines += ["", "## Detector 汇总", "", f"- 有 GT 的单位数：{detector.get('labelled_unit_count', 0)}"]
    formal = detector.get("formal_evaluation") or {}
    if formal:
        unit = formal.get("binary_metrics") or {}
        event = formal.get("event_metrics") or {}
        repairable = formal.get("repairable_binary_metrics") or {}
        safe = formal.get("safe_boundary_binary_metrics") or {}
        lines += [
            f"- 冻结 Detector：`{formal.get('selected_detector')}`；score=`{formal.get('active_score_key')}`；threshold={fmt(formal.get('fixed_threshold'))}",
            "",
            "| 口径 | Precision | Recall | F1 | FPR |",
            "|---|---:|---:|---:|---:|",
            f"| unit error | {fmt(unit.get('precision'))} | {fmt(unit.get('recall'))} | {fmt(unit.get('f1'))} | {fmt(unit.get('false_positive_rate'))} |",
            f"| event error | {fmt(event.get('precision'))} | {fmt(event.get('recall'))} | {fmt(event.get('f1'))} | — |",
            f"| repairable unit | {fmt(repairable.get('precision'))} | {fmt(repairable.get('recall'))} | {fmt(repairable.get('f1'))} | {fmt(repairable.get('false_positive_rate'))} |",
            f"| safe boundary | {fmt(safe.get('precision'))} | {fmt(safe.get('recall'))} | {fmt(safe.get('f1'))} | {fmt(safe.get('false_positive_rate'))} |",
        ]
        bootstrap = formal.get("source_song_cluster_bootstrap") or {}
        if bootstrap:
            lines.append(
                f"- source-song cluster bootstrap：clusters={bootstrap.get('cluster_count', 0)}，"
                f"F1 95% CI={fmt((bootstrap.get('ci95') or {}).get('f1'))}。"
            )
    else:
        lines += [
            f"- Pilot train/calibration split：{json.dumps(detector.get('data_split') or {}, ensure_ascii=False)}",
            f"- Rule / Logistic / Stump threshold points：{len(detector.get('rule_threshold_curve') or [])} / "
            f"{len(detector.get('logistic_threshold_curve') or [])} / {len(detector.get('stump_threshold_curve') or [])}",
        ]


def add_experiments(lines: list[str], experiments: dict[str, Any]) -> None:
    e2 = experiments.get("E2") or {}
    lines += ["", "## E2 人工腐化", "", f"- records：{e2.get('record_count', 0)}"]
    unit = e2.get("detector_micro") or {}; event = e2.get("event_micro") or {}
    lines += [
        f"- Detector unit F1={fmt(unit.get('f1'))}，event F1={fmt(event.get('f1'))}，clean risk spans/case={fmt(e2.get('clean_risk_span_mean'))}。"
    ]
    add_grouped_metric_table(lines, "按腐化类别", e2.get("alignment_by_category"))

    e3 = experiments.get("E3") or {}
    lines += ["", "## E3 Decoder 困难区修复", "", f"- candidates：{e3.get('candidate_count', 0)}"]
    add_grouped_metric_table(lines, "按 span 来源与方法", e3.get("by_span_source_method"))

    e4 = experiments.get("E4") or {}
    lines += ["", "## E4 歌词输入与少量多次", ""]
    selectors = e4.get("selectors") or {}
    if selectors:
        lines += ["| selector | items | MAE | coverage |", "|---|---:|---:|---:|"]
        for name, summary in sorted(selectors.items()):
            lines.append(f"| {name} | {summary.get('item_count', 0)} | {fmt(metric_macro(summary, 'all_penalized_boundary_mae_sec'))} | {fmt(metric_macro(summary, 'coverage'))} |")
    add_grouped_metric_table(lines, "96 vs 3×32", e4.get("chunks"))
    if e4.get("chunk_cost"):
        lines.append(f"- 调用与 RTF：`{json.dumps(e4['chunk_cost'], ensure_ascii=False, sort_keys=True)}`")

    for phase, title in (("E5", "动态安全边界分窗"), ("E6", "静音机制")):
        payload = experiments.get(phase) or {}
        lines += ["", f"## {phase} {title}", ""]
        add_grouped_metric_table(lines, "主指标", payload.get("by_variant"))
        diagnostics = payload.get("serial_diagnostics_by_variant") or {}
        if diagnostics:
            lines += ["", "| variant | cursor MAE(units) | missing | extra | recovery(units) | persistent failure |", "|---|---:|---:|---:|---:|---:|"]
            for name, row in sorted(diagnostics.items()):
                lines.append(
                    f"| {name} | {fmt(row.get('cursor_distance_mean_abs_units'))} | {fmt(row.get('missing_unit_count_mean'))} | "
                    f"{fmt(row.get('extra_unit_count_mean'))} | {fmt(row.get('recovery_character_distance_mean'))} | {fmt(row.get('persistent_failure_rate'))} |"
                )
        if phase == "E6":
            lines.append(f"- 有静音、可评价的 item：{payload.get('applicable_item_count', 0)}；按静音长度分组数：{len(payload.get('silence_boundary_by_variant_and_duration') or {})}。")

    e7 = experiments.get("E7") or {}
    lines += ["", "## E7 串行累计因果", "", f"- records：{e7.get('record_count', 0)}；满足“持续恶化且 reset 恢复”比例：{fmt(e7.get('causal_cascade_supported_rate'))}"]
    if e7.get("by_injection_kind"):
        lines += ["", "| injection | post MAE Δ | coverage Δ | degradation rate |", "|---|---:|---:|---:|"]
        for name, row in sorted(e7["by_injection_kind"].items()):
            lines.append(f"| {name} | {fmt(row.get('mean_post_mae_delta_sec'))} | {fmt(row.get('mean_coverage_delta'))} | {fmt(row.get('persistent_degradation_rate'))} |")
    if e7.get("reset_recovery"):
        lines.append(f"- Reset 恢复：`{json.dumps(e7['reset_recovery'], ensure_ascii=False, sort_keys=True)}`")

    e8 = experiments.get("E8") or {}
    lines += [
        "", "## E8 简化 Realign", "",
        f"- cases={e8.get('case_count', 0)}；clean cases={e8.get('clean_case_count', 0)}；alternate-input candidates={e8.get('alternate_input_candidate_count', 0)}。",
        f"- selected improvement={fmt(e8.get('selected_improvement_rate'))}；harm={fmt(e8.get('selected_harm_rate'))}；clean harm={fmt(e8.get('selected_clean_harm_rate'))}；oracle match={fmt(e8.get('oracle_match_rate'))}。",
        f"- 后续区域 MAE Δ={fmt(e8.get('downstream_mae_delta_mean_sec'))}，coverage Δ={fmt(e8.get('downstream_coverage_delta_mean'))}；"
        f"complete={e8.get('candidate_propagation_complete_count', 0)}，failed={e8.get('candidate_propagation_failure_count', 0)}，"
        f"continuation failure={fmt(e8.get('candidate_propagation_failure_rate'))}。",
        f"- 下游效应统计条件：`{e8.get('downstream_effect_conditioning', '—')}`；失败候选只保留 static diagnostic，不进入传播效应均值。",
    ]
    add_grouped_metric_table(lines, "Local candidate", e8.get("local_by_candidate"))

    e9 = experiments.get("E9") or {}
    lines += [
        "", "## E9 系统级 Pilot", "",
        f"- items={e9.get('item_count', 0)}；beam width={fmt(e9.get('beam_width_mean'))}；"
        f"平均多 hypothesis 窗数={fmt(e9.get('multi_hypothesis_window_count_mean'))}；"
        f"平均 fallback 窗数={fmt(e9.get('fallback_window_count_mean'))}。",
        f"- selected complete rate={fmt(e9.get('selected_complete_rate'))}；"
        f"selected/final-beam oracle match={fmt(e9.get('selected_matches_final_beam_oracle_rate'))}；"
        f"selected MAE Δ={fmt(e9.get('selected_mae_delta_mean_sec'))}；"
        f"line boundary MAE={fmt(e9.get('line_boundary_mae_sec'))}。",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--pilot-root", type=Path)
    parser.add_argument("--frozen-params", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    formal = json.loads((args.formal_root / "research_summary.json").read_text(encoding="utf-8"))
    frozen = json.loads(args.frozen_params.read_text(encoding="utf-8")) if args.frozen_params and args.frozen_params.is_file() else {}
    lines = [
        "# Alignment Research v6 正式实验报告", "", "## 运行与数据完整性", "",
        f"- Manifest 条目：{formal.get('manifest_item_count')}",
        f"- 实际选择：{formal.get('selected_item_count')}",
        f"- 完成：{formal.get('completed_item_count')}",
        f"- 失败：{formal.get('failed_item_count')}",
        f"- Formal 数据政策：{formal.get('full_data_policy')}",
        f"- Case 执行政策：`{json.dumps(formal.get('case_execution_policy') or {}, ensure_ascii=False, sort_keys=True)}`",
        f"- Case-level subsampling：{fmt((formal.get('case_execution_policy') or {}).get('case_level_subsampling'))}",
        f"- Inference cache：`{json.dumps(formal.get('inference_cache_summary') or {}, ensure_ascii=False, sort_keys=True)}`", "",
        "## 参数冻结", "",
        f"- Freeze effectiveness：{(frozen.get('selection_effectiveness') or {}).get('level', '—')}",
        f"- Freeze warnings：`{json.dumps((frozen.get('selection_effectiveness') or {}).get('warnings') or [], ensure_ascii=False)}`",
        f"- Detector：{frozen.get('selected_detector', '—')}",
        f"- Detector threshold：{fmt((frozen.get('selected_detector_threshold') or {}).get('threshold') if isinstance(frozen.get('selected_detector_threshold'), dict) else None)}",
        f"- Recommended thresholds：`{json.dumps(frozen.get('recommended_parameters') or {}, ensure_ascii=False, sort_keys=True)}`",
        f"- Decoder：{frozen.get('selected_decoder', '—')}",
        f"- Formal decoder execution：`{json.dumps(formal.get('frozen_decoder_execution') or {}, ensure_ascii=False, sort_keys=True)}`", "",
        "## E0 Decoder 汇总", "", "| 方法 | all MAE | non-training MAE | coverage | raw harm | raw repair |", "|---|---:|---:|---:|---:|---:|",
    ]
    for name, payload in formal.get("decoder_summary", {}).items():
        all_summary = payload.get("all") or {}
        generalization = payload.get("main_generalization_nontraining") or {}
        paired = payload.get("paired_transition_from_raw") or {}
        lines.append(
            f"| {name} | {fmt(metric_macro(all_summary, 'all_penalized_boundary_mae_sec'))} | "
            f"{fmt(metric_macro(generalization, 'all_penalized_boundary_mae_sec'))} | {fmt(metric_macro(all_summary, 'coverage'))} | "
            f"{fmt(paired.get('raw_correct_harm_rate_macro'))} | {fmt(paired.get('raw_error_repair_rate_macro'))} |"
        )
    for name, payload in formal.get("decoder_summary", {}).items():
        add_grouped_metric_table(lines, f"{name}：按 dataset/split", payload.get("by_dataset_split"))
    add_detector(lines, formal.get("detector_summary") or {})
    add_experiments(lines, formal.get("experiment_summary") or {})
    lines += ["", "## 失败与 negative results", ""]
    failures = formal.get("failures") or []
    if not failures:
        lines.append("- Formal 未记录 item failure。")
    else:
        for failure in failures:
            lines.append(f"- `{failure.get('item_id')}`：{failure.get('error_type')} — {failure.get('error')}")
    lines += [
        "", "## 结论使用限制", "",
        "- 无 GT test demo 只能用于结构、稳定性、跨输入一致性和人工视听，不用于声称 accuracy 提升。",
        "- M4Singer train/validation/test 与 MIR-1K selection role 独立汇报；主泛化口径排除 training_exposure。",
        "- Synthetic-long 按 source_song_id 聚类，seam-near 与 seam-far 分开解释。",
        "- 参数仅由 pilot train/calibration 冻结；formal/held-out 不用于回调阈值。best-effort/default freeze 会降低结论效力，但不阻断 formal。",
        "- 本报告只汇总实际存在的结果字段，不补写未运行或失败实验。", "",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
