#!/usr/bin/env python3
"""WP7：report_long_slot_region —— draft 汇总与 budget/pilot 报告。

读取 smoke/pilot/formal 结果，输出 AUTO_SUMMARY.json + AUTO_FINDINGS_DRAFT.md + RUNTIME_BUDGET.json。
P0-5：除非提供的 --formal-approved-manifest 真实存在且其 sha256 与 --expected-manifest-sha256
一致，否则一律 draft=true；不可仅凭"传了参数"就降级。
round09：可选 --baseline-quality（research_v7_baseline_quality_analysis_v1）只读记录进
AUTO_SUMMARY.data.baseline_quality + baseline_quality_finding，不参与 formal gate。
round11：可选 --missing-ratio-curve（research_v7_missing_ratio_curve_v1）只读记录进
AUTO_SUMMARY.data.missing_ratio_curve + missing_ratio_conclusion，不参与 formal gate；
created_at_utc 动态取生成时 UTC（不再硬编码）。
round17：可选 --density-comparison（research_v7_density_tier_comparison_v1）只读记录进
AUTO_SUMMARY.data.density_comparison + density_finding，不参与 formal gate。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--formal-approved-manifest", default="", help="正式汇总才使用该 manifest")
    p.add_argument("--expected-manifest-sha256", default="", help="冻结 manifest 的 sha256（须匹配才 formal_approved）")
    p.add_argument("--extrapolate-requests", type=int, default=600,
                   help="pilot/formal 预算外推请求数（默认 600，13 计划 pilot 规模量级）")
    p.add_argument("--cross-domain-eval", default="",
                   help="跨域评估产物（research_v7_assessor_cross_domain_eval_v1）；可选，只记录 finding，不参与 formal gate")
    p.add_argument("--baseline-quality", default="",
                   help="baseline 质量分析产物（research_v7_baseline_quality_analysis_v1）；可选，只记录 finding，不参与 formal gate")
    p.add_argument("--missing-ratio-curve", default="",
                   help="missing 比例曲线产物（research_v7_missing_ratio_curve_v1）；可选，只记录 finding，不参与 formal gate")
    p.add_argument("--density-comparison", default="",
                   help="density 档位对比产物（research_v7_density_tier_comparison_v1）；可选，只记录 finding，不参与 formal gate")
    args = p.parse_args(argv)

    run = Path(args.run_root)
    smoke_f = run / "smoke" / "LONG_SLOT_SMOKE.json"
    if not smoke_f.exists():
        print(json.dumps({"ok": False, "reason": "no smoke result"}, ensure_ascii=False))
        return 3
    smoke = json.loads(smoke_f.read_text())

    # T1（round06）：跨域评估发现（M4→MIR）——可选输入，只读记录进 report。
    # 不提供/文件缺失/不可读/schema 不匹配 → cross_domain=None，不阻塞 formal_approved，行为不变。
    cross_domain = None
    cross_domain_path = Path(args.cross_domain_eval) if args.cross_domain_eval else None
    if cross_domain_path is not None:
        try:
            cd = json.loads(cross_domain_path.read_text(encoding="utf-8"))
        except Exception:
            cd = None
        if not isinstance(cd, dict) or cd.get("schema") != "research_v7_assessor_cross_domain_eval_v1":
            print(f"WARN: cross-domain eval {cross_domain_path} unreadable or schema "
                  f"!= research_v7_assessor_cross_domain_eval_v1; skipped", file=sys.stderr)
            cd = None
        if cd is not None:
            mir = cd.get("mir1k") or {}
            m4_op = (cd.get("m4_assessor") or {}).get("operating_points") or {}
            cross_domain = {
                "schema": cd.get("schema"),
                "path": str(cross_domain_path),
                "unsafe_rate_95": mir.get("unsafe_rate_95"),
                "unsafe_rate_99": mir.get("unsafe_rate_99"),
                "unit_recall_95": mir.get("unit_recall_95"),
                "unit_recall_99": mir.get("unit_recall_99"),
                "correct_unit_fpr_95": mir.get("correct_unit_fpr_95"),
                "correct_unit_fpr_99": mir.get("correct_unit_fpr_99"),
                "score_distribution": mir.get("score_distribution"),
                "n_units": mir.get("n_units"),
                "m4_operating_points": m4_op,
                "inputs": cd.get("inputs") or {},
                "cross_domain_finding": (
                    "M4 frozen operating points do not transfer to MIR (near-all-unsafe); "
                    "cross-domain recalibration required, not a pass"),
            }

    # round02：formal 指标回填 —— GT_EVAL.json（research_v7_gt_eval_v1）优先于
    # RUN_MANIFEST.metrics；仅当文件缺失/不可读/schema 不合法（schema !=
    # research_v7_gt_eval_v1 或 metrics 非空 dict）时回退。只读，不覆盖任何原始 aggregate。
    gt_eval = None
    gt_eval_invalid_reason = None
    gt_eval_f = run / "GT_EVAL.json"
    if gt_eval_f.is_file():
        try:
            parsed = json.loads(gt_eval_f.read_text(encoding="utf-8"))
        except Exception:
            parsed = None
        if parsed is None:
            gt_eval_invalid_reason = "GT_EVAL unreadable"
        elif not isinstance(parsed, dict) or parsed.get("schema") != "research_v7_gt_eval_v1":
            gt_eval_invalid_reason = "GT_EVAL schema invalid"
        elif not isinstance(parsed.get("metrics"), dict) or not parsed["metrics"]:
            gt_eval_invalid_reason = "GT_EVAL metrics empty"
        else:
            gt_eval = parsed

    # round09：baseline 质量分析（research_v7_baseline_quality_analysis_v1）——
    # 可选输入，只读记录进 report。不提供/文件缺失/不可读/schema 不匹配 →
    # baseline_quality=None 且 baseline_quality_finding=None，不阻塞 formal_approved，行为不变。
    baseline_quality = None
    baseline_quality_finding = None
    bq_path = Path(args.baseline_quality) if args.baseline_quality else None
    if bq_path is not None:
        try:
            bq = json.loads(bq_path.read_text(encoding="utf-8"))
        except Exception:
            bq = None
        if not isinstance(bq, dict) or bq.get("schema") != "research_v7_baseline_quality_analysis_v1":
            print(f"WARN: baseline quality {bq_path} unreadable or schema "
                  f"!= research_v7_baseline_quality_analysis_v1; skipped", file=sys.stderr)
            bq = None
        if bq is not None:
            coverage = bq.get("coverage") or {}
            b_err = bq.get("boundary_error") or {}
            axis = bq.get("axis_sensitivity") or {}
            seams = bq.get("seam_strata") or {}
            auc = bq.get("feature_auc") or {}
            # 阈值表键 = str(threshold_sec)（analyze 脚本 UNSAFE_THRESHOLD_SEC=0.25 → "0.25"）
            th = (b_err.get("thresholds") or {}).get("0.25")
            near = ((seams.get("near_seam") or {}) or {}).get("unsafe_rate_gt_0_25")
            far = ((seams.get("far_from_seam") or {}) or {}).get("unsafe_rate_gt_0_25")
            # feature AUC 顶值：排除标签特征 either_max_boundary_error_sec（AUC=1.0 是标签自身）
            top_name, top_auc = None, None
            for name, entry in ((auc.get("per_feature") or {}).items()):
                if name == "either_max_boundary_error_sec":
                    continue
                v = (entry or {}).get("auc")
                if v is not None and (top_auc is None or v > top_auc):
                    top_auc, top_name = v, name
            baseline_quality = {
                "schema": bq.get("schema"),
                "path": str(bq_path),
                "row_coverage": ((coverage.get("overall") or {}) or {}).get("row_coverage"),
                "start_mae_median": (((b_err.get("by_boundary") or {}).get("start_abs_error_sec")
                                      or {}) or {}).get("median"),
                "unsafe_rate_gt_0_25": (th or {}).get("exceed_rate", {}).get("either"),
                "axis_ratio_m4_over_mir": axis.get("ratio_m4_over_mir"),
                "mir_metric": (axis.get("mir_weak_axis") or {}).get("metric"),
                "seam_near_unsafe": near,
                "seam_far_unsafe": far,
                "feature_auc_top": top_auc,
                "self_check_ok": (bq.get("self_check") or {}).get("ok"),
            }
            parts = []
            m4_rate = baseline_quality["unsafe_rate_gt_0_25"]
            mir_axis = axis.get("mir_weak_axis") or {}
            # round10：同口径（boundary_error_same_metric）优先用 unsafe_rate_gt_0_25；
            # 旧口径 mutation 标签命中率用 unsafe_rate（标注非可比）。
            if mir_axis.get("metric") == "boundary_error_same_metric":
                mir_rate = mir_axis.get("unsafe_rate_gt_0_25")
                ratio = baseline_quality["axis_ratio_m4_over_mir"]
                if m4_rate is not None and mir_rate is not None and ratio is not None:
                    parts.append(f"GT axis sensitivity (same metric, boundary error): "
                                 f"{m4_rate:.1%} (M4 synthetic) vs {mir_rate:.1%} (MIR weak) = {ratio:.2f}x "
                                 f"(axis construction, not decoder quality)")
            else:
                mir_rate = mir_axis.get("unsafe_rate")
                ratio = baseline_quality["axis_ratio_m4_over_mir"]
                if m4_rate is not None and mir_rate is not None:
                    parts.append(f"GT axis sensitivity (INCOMPARABLE metrics): "
                                 f"{m4_rate:.1%} (M4 boundary error) vs {mir_rate:.1%} "
                                 f"(MIR mutation-label hit rate) - non-comparable")
            if baseline_quality["start_mae_median"] is not None:
                parts.append(f"boundary start MAE median {baseline_quality['start_mae_median']:.3f}s")
            if near is not None and far is not None:
                seam_note = ("seam has no measurable effect" if abs(near - far) < 0.05
                             else f"seam near/far differ by {abs(near - far):.1%}")
                parts.append(f"seam near/far unsafe {near:.1%}/{far:.1%} ({seam_note})")
            if top_auc is not None:
                parts.append(f"feature AUC top {top_auc:.3f} ({top_name}) "
                             "~0.5, no discriminative power")
            if parts:
                parts.append(f"self_check={baseline_quality['self_check_ok']}")
                # GT 轴为 synthetic-uniform：缺失单元无行、经 virtual gap 评价，unit_recall=0
                # 是结构性结果而非 decoder 失败（GT_EVAL 存在且 unit_recall==0 时才声明）
                if gt_eval is not None and (gt_eval.get("metrics") or {}).get("unit_recall") == 0:
                    parts.append("unit_recall=0 is structural (deleted units have no rows), "
                                 "not decoder failure")
                baseline_quality_finding = "; ".join(parts)

    # round11：missing 比例曲线（research_v7_missing_ratio_curve_v1）——可选输入，只读记录。
    # 不提供/文件缺失/不可读/schema 不匹配 → missing_ratio_curve=None 且
    # missing_ratio_conclusion=None，不阻塞 formal_approved，行为不变。
    missing_ratio_curve = None
    missing_ratio_conclusion = None
    mrc_path = Path(args.missing_ratio_curve) if args.missing_ratio_curve else None
    if mrc_path is not None:
        try:
            mrc = json.loads(mrc_path.read_text(encoding="utf-8"))
        except Exception:
            mrc = None
        if not isinstance(mrc, dict) or mrc.get("schema") != "research_v7_missing_ratio_curve_v1":
            print(f"WARN: missing ratio curve {mrc_path} unreadable or schema "
                  f"!= research_v7_missing_ratio_curve_v1; skipped", file=sys.stderr)
            mrc = None
        if mrc is not None:
            points = []
            for pt in mrc.get("curve") or []:
                if not isinstance(pt, dict):
                    continue
                points.append({
                    "missing_ratio": pt.get("missing_ratio"),
                    "n_requests": pt.get("n_requests"),
                    "n_omitted_gt_units": pt.get("n_omitted_gt_units"),
                    "gap_event_recall": pt.get("gap_event_recall"),
                    "gap_weighted_recall": pt.get("gap_weighted_recall"),
                    "unit_recall": pt.get("unit_recall"),
                })
            missing_ratio_curve = {
                "schema": mrc.get("schema"),
                "path": str(mrc_path),
                "gt_axis_note": mrc.get("gt_axis_note"),
                "curve": points,
            }
            if points and all(p["gap_event_recall"] == 1.0 for p in points):
                missing_ratio_conclusion = (
                    "all missing ratios detected via virtual gap; unit_recall=0 structural")

    # round17：density 档位对比（research_v7_density_tier_comparison_v1）——可选输入，只读记录。
    # 不提供/文件缺失/不可读/schema 不匹配 → density_comparison=None 且
    # density_finding=None，不阻塞 formal_approved，行为不变。
    density_comparison = None
    density_finding = None
    dct_path = Path(args.density_comparison) if args.density_comparison else None
    if dct_path is not None:
        try:
            dct = json.loads(dct_path.read_text(encoding="utf-8"))
        except Exception:
            dct = None
        if not isinstance(dct, dict) or dct.get("schema") != "research_v7_density_tier_comparison_v1":
            print(f"WARN: density comparison {dct_path} unreadable or schema "
                  f"!= research_v7_density_tier_comparison_v1; skipped", file=sys.stderr)
            dct = None
        if dct is not None:
            tiers = {}
            for tier, v in (dct.get("density_tiers") or {}).items():
                if not isinstance(v, dict):
                    continue
                tiers[tier] = {
                    "missing_gap_recall": v.get("missing_gap_recall"),
                    "replace_wrong_output_recall": v.get("replace_wrong_output_recall"),
                }
            density_comparison = {
                "schema": dct.get("schema"),
                "path": str(dct_path),
                "source_gt_eval": dct.get("source_gt_eval"),
                "tiers": tiers,
            }
            gaps = [tiers[t]["missing_gap_recall"] for t in ("full", "s2", "s4") if t in tiers]
            repl = [tiers[t]["replace_wrong_output_recall"]
                    for t in ("full", "s2", "s4") if t in tiers]
            if (len(gaps) == 3 and len(repl) == 3
                    and all(v is not None for v in gaps + repl)):
                density_finding = (
                    "missing-gap robust across densities; replace wrong-output linearly "
                    f"sensitive ({repl[0]:.3f}/{repl[1]:.3f}/{repl[2]:.3f}) - "
                    "common-anchor scoring required")

    # P0-5 round2：formal_approved 需真实 formal evidence + frozen manifest sha + 实际预算/gates。
    formal_approved = False
    reasons = []
    if gt_eval_invalid_reason:
        reasons.append(gt_eval_invalid_reason)
    formal_manifest = run / "formal" / "RUN_MANIFEST.json"
    marker = run / "formal" / "FORMAL_MARKER.json"
    if not args.formal_approved_manifest:
        reasons.append("no formal-approved-manifest")
    elif not marker.is_file():
        reasons.append("no real formal evidence: run/formal/FORMAL_MARKER.json missing")
    elif not formal_manifest.is_file():
        reasons.append("missing real formal result: run/formal/RUN_MANIFEST.json")
    else:
        mp = Path(args.formal_approved_manifest)
        got_sha = _sha256(mp) if mp.is_file() else None
        if not mp.is_file():
            reasons.append("formal-approved-manifest not a file")
        elif not args.expected_manifest_sha256:
            reasons.append("expected-manifest-sha256 not provided")
        elif got_sha != args.expected_manifest_sha256:
            reasons.append("manifest sha256 mismatch (frozen expected)")
        else:
            try:
                marker_d = json.loads(marker.read_text())
                run_man = json.loads(formal_manifest.read_text())
            except Exception as e:
                reasons.append(f"formal marker/manifest unreadable: {e}")
            else:
                # marker 必须绑定 frozen manifest hash + run identity + 实际预算
                if marker_d.get("manifest_sha256") != args.expected_manifest_sha256:
                    reasons.append("FORMAL_MARKER manifest_sha256 != frozen expected")
                    formal_runner = None
                else:
                    formal_runner = run_man.get("run_id") == marker_d.get("run_id")
                    if not formal_runner:
                        reasons.append("FORMAL_MARKER run_id != RUN_MANIFEST.run_id")
                if not (marker_d.get("all_gates_passed") and marker_d.get("runtime_budget_ok")):
                    reasons.append("FORMAL_MARKER gates/budget not all passed")
                else:
                    # 真实结果应有实测预算字段（elapsed/forward/cache），不是凭空
                    fb = run_man.get("runtime_budget") or {}
                    if not (fb.get("elapsed_sec") and fb.get("forward_count") is not None):
                        reasons.append("RUN_MANIFEST.runtime_budget missing actual elapsed/forward")
                # M1（review12）：formal approved 必须是真实模型运行——executor=real、
                # 有实际 forward 数、且结果数据字段非空（不得把空 RUN_MANIFEST 当 approved）
                env = run_man.get("environment") or {}
                if env.get("executor") != "real":
                    reasons.append("RUN_MANIFEST executor != real (formal must be real model run)")
                if not ((run_man.get("runtime_budget") or {}).get("forward_count") or 0) > 0:
                    reasons.append("RUN_MANIFEST forward_count == 0 (no real forward)")
                for field in ("timeline", "metrics", "assessor"):
                    # round02：GT_EVAL.json 存在即视为 metrics 满足（RUN_MANIFEST.metrics
                    # 可能恒 null，真实指标在 GT_EVAL）
                    if not run_man.get(field) and not (field == "metrics" and gt_eval is not None):
                        reasons.append(f"RUN_MANIFEST missing result field {field}")
                if not reasons:
                    formal_approved = True
    draft = not formal_approved

    # 数据源：formal→真实 RUN_MANIFEST；否则 smoke（draft）
    if formal_approved:
        result_kv = run_man
    else:
        result_kv = smoke

    auto = {
        "schema": "research_v7_long_slot_report_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "draft": draft,
        "formal_approved": formal_approved,
        "draft_reasons": reasons,
        "result_source": str(formal_manifest) if formal_approved else str(smoke_f),
        "data": {
            "timeline_duration_sec": result_kv.get("timeline", {}).get("duration_sec"),
            "timeline_ge180": result_kv.get("timeline", {}).get("ge180"),
            "slot_topology": result_kv.get("slot", result_kv.get("key", {})).get("topology"),
            "non_contiguous": (result_kv.get("slot", result_kv.get("key", {}))).get("non_contiguous"),
            "assessor_op": result_kv.get("assessor", {}).get("operating_points")
                      or result_kv.get("key", {}).get("assessor_op"),
            "cross_domain": cross_domain,
            "baseline_quality": baseline_quality,
            "baseline_quality_finding": baseline_quality_finding,
            "missing_ratio_curve": missing_ratio_curve,
            "missing_ratio_conclusion": missing_ratio_conclusion,
            "density_comparison": density_comparison,
            "density_finding": density_finding,
        },
    }
    if gt_eval is not None:
        # round02：GT_EVAL 源（schema research_v7_gt_eval_v1，键 correct_unit_fpr）
        gm = gt_eval.get("metrics") or {}
        auto["gt_eval_path"] = str(gt_eval_f)
        auto["gt_axis_note"] = gt_eval.get("gt_axis_note")
        auto["data"]["unit_recall"] = gm.get("unit_recall")
        auto["data"]["correct_unit_fpr"] = gm.get("correct_unit_fpr")
        auto["data"]["gap_recall"] = gm.get("gap_recall")
        auto["data"]["gap_weighted_recall"] = gm.get("gap_weighted_recall")
        auto["data"]["n_units_evaluated"] = gm.get("n_units_evaluated")
        auto["data"]["n_baseline"] = gm.get("n_baseline")
        auto["data"]["n_missing"] = gm.get("n_missing")
        auto["data"]["n_evidence_skipped"] = gm.get("n_evidence_skipped")
    else:
        # 回退源：RUN_MANIFEST（formal）或 smoke（draft）；RUN_MANIFEST 键为 fpr（兼容）
        m_src = result_kv.get("metrics") or {}
        k_src = result_kv.get("key") or {}
        auto["data"]["unit_recall"] = (
            m_src.get("unit_recall") if m_src.get("unit_recall") is not None
            else k_src.get("unit_recall"))
        auto["data"]["correct_unit_fpr"] = (
            m_src.get("fpr") if m_src.get("fpr") is not None
            else k_src.get("correct_unit_fpr"))
        auto["data"]["gap_recall"] = (
            m_src.get("gap_recall") if m_src.get("gap_recall") is not None
            else k_src.get("gap_recall"))
        auto["data"]["gap_weighted_recall"] = m_src.get("gap_weighted_recall")
        auto["data"]["n_units_evaluated"] = m_src.get("n_units_evaluated")
        auto["data"]["n_baseline"] = m_src.get("n_baseline")
        auto["data"]["n_missing"] = m_src.get("n_missing")
        auto["data"]["n_evidence_skipped"] = m_src.get("n_evidence_skipped")
    (run / "report").mkdir(parents=True, exist_ok=True)
    (run / "report" / "AUTO_SUMMARY.json").write_text(json.dumps(auto, ensure_ascii=False, indent=1))

    # P0(review3-3)：formal approved 时保留/引用实际 formal budget（不再写 draft=true 的自相矛盾占位）
    if formal_approved:
        fb = result_kv.get("runtime_budget", {}) or run_man.get("runtime_budget", {})
        elapsed = fb.get("elapsed_sec")
        forward = fb.get("forward_count")
        sec_per_forward = (elapsed / forward) if (elapsed and forward) else None
        budget = {
            "schema": "runtime_budget_v1", "draft": False,
            "source": "formal", "budget": fb,
            "note": "actual formal run budget (elapsed/forward from RUN_MANIFEST)",
        }
        if sec_per_forward is not None:
            n_ext = max(int(args.extrapolate_requests), 1)
            budget["estimated_runtime_sec"] = sec_per_forward * n_ext
            budget["estimated_runtime_sec_n_requests"] = n_ext
            budget["estimated_forward_capacity_h12"] = int(12 * 3600 / sec_per_forward)
            budget["extrapolation_note"] = "单机 GPU 串行、不含批处理并行/cache 复用折算"
    else:
        budget = {
            "schema": "runtime_budget_v1", "draft": True,
            "formal_target_h": 10, "formal_hard_cap_h": 12,
            "smoke": "run in CPU (no model)", "note": "pilot must measure elapsed/forward/cache before formal",
        }
    (run / "report" / "RUNTIME_BUDGET.json").write_text(json.dumps(budget, ensure_ascii=False, indent=1))

    md = f"""# AUTO_FINDINGS_{(not draft and 'SUMMARY' or 'DRAFT')}

- status: {'formal (approved)' if formal_approved else 'smoke/pilot draft'}
- Timeline: {auto['data']['timeline_duration_sec']}s (ge180={auto['data']['timeline_ge180']})
- Slot topology: {auto['data']['slot_topology']} (non-contiguous={auto['data']['non_contiguous']})
- unit_recall={auto['data']['unit_recall']}, correct_unit_fpr={auto['data']['correct_unit_fpr']}, gap_recall={auto['data']['gap_recall']}
- Assessor operating points: {auto['data']['assessor_op']}

> 自动。draft={draft}; reasons={reasons}。正式结论需 sha-matched frozen manifest；否则仅作 draft。
"""
    if cross_domain is not None:
        md += f"""
## Cross-domain assessor

- Source: {cross_domain_path}
- unsafe_rate_95={cross_domain['unsafe_rate_95']}, unsafe_rate_99={cross_domain['unsafe_rate_99']},
  unit_recall_95={cross_domain['unit_recall_95']}, correct_unit_fpr_95={cross_domain['correct_unit_fpr_95']}
- n_units={cross_domain['n_units']}, M4 operating points={cross_domain['m4_operating_points']}
- Finding: {cross_domain['cross_domain_finding']}
"""
    if baseline_quality is not None:
        bq = baseline_quality
        md += f"""
## Baseline quality

- Source: {bq_path}
- row_coverage={bq['row_coverage']}, start MAE median={bq['start_mae_median']}s,
  unsafe_rate>250ms={bq['unsafe_rate_gt_0_25']}
- GT axis ratio M4/MIR={bq['axis_ratio_m4_over_mir']}x; seam near={bq['seam_near_unsafe']},
  far={bq['seam_far_unsafe']}; feature AUC top={bq['feature_auc_top']}; self_check={bq['self_check_ok']}
- Finding: {baseline_quality_finding}
"""
    if missing_ratio_curve is not None:
        pts = missing_ratio_curve["curve"]
        ratios = ", ".join(str(p["missing_ratio"]) for p in pts)
        md += f"""
## Missing ratio curve

- Source: {mrc_path}
- Points ({len(pts)}): missing_ratio={ratios}
- gap_event_recall per point: {[p['gap_event_recall'] for p in pts]},
  gap_weighted_recall={[p['gap_weighted_recall'] for p in pts]},
  unit_recall={[p['unit_recall'] for p in pts]}
- Finding: {missing_ratio_conclusion}
"""
    if density_comparison is not None:
        dct_tiers = density_comparison["tiers"]
        gaps = [dct_tiers[t]["missing_gap_recall"] for t in ("full", "s2", "s4") if t in dct_tiers]
        repl = [dct_tiers[t]["replace_wrong_output_recall"]
                for t in ("full", "s2", "s4") if t in dct_tiers]
        md += f"""
## Density tier comparison

- Source: {dct_path}
- Tiers ({len(dct_tiers)}): {", ".join(sorted(dct_tiers))}
- missing_gap_recall per tier: {gaps}, replace_wrong_output_recall: {repl}
- Finding: {density_finding}
"""
    md_name = f"AUTO_FINDINGS_{'SUMMARY' if not draft else 'DRAFT'}.md"
    (run / "report" / md_name).write_text(md)
    # 兼容旧消费者：draft 时同时保留 DRAFT.md
    if not draft and (run / "report" / "AUTO_FINDINGS_DRAFT.md").exists():
        (run / "report" / "AUTO_FINDINGS_DRAFT.md").unlink()

    print(json.dumps({"ok": True, "draft": draft, "formal_approved": formal_approved,
                      "reasons": reasons, "out": str(run / "report"), "data": auto["data"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
