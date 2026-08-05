# -*- coding: utf-8 -*-
"""P0-5 round2：report 真实 formal gate 的 CLI 正反向测试（smoke 不被伪标 formal）。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "scripts/research_v7/report_long_slot_region.py"


def _run_root(tmp):
    run = tmp / "run"; (run / "smoke").mkdir(parents=True)
    (run / "smoke" / "LONG_SLOT_SMOKE.json").write_text(json.dumps({
        "timeline": {"duration_sec": 400, "ge180": True}, "slot": {"topology": "three_regions"},
        "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0}}))
    return run


def _manifest(tmp):
    m = tmp / "frozen.jsonl"; m.write_text('{"a":1}\n')
    return m, hashlib.sha256(m.read_bytes()).hexdigest()


def _call(run, manifest, sha, extra=None):
    env = dict(os.environ, PYTHONPATH=str(REPO / "src") + ":" + str(REPO))
    cmd = [sys.executable, str(REPORT), "--run-root", str(run),
           "--formal-approved-manifest", str(manifest), "--expected-manifest-sha256", sha]
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _cross_domain_eval(tmp):
    # 合成跨域评估产物（research_v7_assessor_cross_domain_eval_v1），不引用真实 run 文件
    f = tmp / "cross_domain_eval.json"
    f.write_text(json.dumps({
        "schema": "research_v7_assessor_cross_domain_eval_v1",
        "m4_assessor": {"operating_points": {"high_recall_95": 0.172, "high_recall_99": 0.155}},
        "mir1k": {
            "n_units": 4592,
            "unsafe_rate_95": 0.9665, "unsafe_rate_99": 0.9972,
            "unit_recall_95": 0.9611, "unit_recall_99": 0.9949,
            "correct_unit_fpr_95": 0.9673, "correct_unit_fpr_99": 0.9975,
            "score_distribution": {"min": 0.100789, "p50": 0.187314, "p90": 0.198039, "max": 0.211158},
        },
        "inputs": {"mir1k_collection_sha256": "eba57b2fa4cb597abb2f1e10297b3a8b4abc01d7e5ff3c2cb2a160cda40c1941"},
    }))
    return f


def _formal_fixture(run, man, sha):
    (run / "formal").mkdir(exist_ok=True)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1",
         "environment": {"executor": "real"},
         "runtime_budget": {"elapsed_sec": 600, "forward_count": 120},
         "timeline": {"duration_sec": 400, "ge180": True},
         "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0},
         "assessor": {"operating_points": {"high_recall_95": 0.9}}}))


def test_forward_all_gates_approved(tmp_path):
    run = _run_root(tmp_path); (run / "formal").mkdir(exist_ok=True)
    man, sha = _manifest(tmp_path)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1",
         "environment": {"executor": "real"},
         "runtime_budget": {"elapsed_sec": 600, "forward_count": 120},
         # M1（review12）：formal approved 还需结果数据字段非空
         "timeline": {"duration_sec": 400, "ge180": True},
         "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0},
         "assessor": {"operating_points": {"high_recall_95": 0.9}}}))
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    assert "RUN_MANIFEST.json" in s["result_source"]
    # review3-3：formal approved 时 RUNTIME_BUDGET 必须非 draft 且引用实际 budget
    b = json.loads((run / "report" / "RUNTIME_BUDGET.json").read_text())
    assert b["draft"] is False and b["budget"].get("elapsed_sec") == 600  # 读真实 formal，不读 smoke


def test_reverse_fake_executor_never_approved(tmp_path):
    # M1（review12）：即使 marker/gates/预算齐全，executor 非 real（fake-smoke）不得 approved
    run = _run_root(tmp_path); (run / "formal").mkdir(exist_ok=True)
    man, sha = _manifest(tmp_path)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1",
         "environment": {"executor": "fake-smoke"},
         "runtime_budget": {"elapsed_sec": 600, "forward_count": 120},
         "timeline": {"duration_sec": 400, "ge180": True},
         "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0},
         "assessor": {"operating_points": {"high_recall_95": 0.9}}}))
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert any("executor != real" in x for x in s["draft_reasons"])


def test_reverse_zero_forward_never_approved(tmp_path):
    # M1（review12）：forward_count==0（无真实推理）不得 approved
    run = _run_root(tmp_path); (run / "formal").mkdir(exist_ok=True)
    man, sha = _manifest(tmp_path)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1",
         "environment": {"executor": "real"},
         "runtime_budget": {"elapsed_sec": 600, "forward_count": 0},
         "timeline": {"duration_sec": 400, "ge180": True},
         "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0},
         "assessor": {"operating_points": {"high_recall_95": 0.9}}}))
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert any("forward_count == 0" in x for x in s["draft_reasons"])


def test_reverse_missing_result_fields_never_approved(tmp_path):
    # M1（review12）：结果数据字段缺失（timeline/metrics/assessor 为空）不得 approved
    run = _run_root(tmp_path); (run / "formal").mkdir(exist_ok=True)
    man, sha = _manifest(tmp_path)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1",
         "environment": {"executor": "real"},
         "runtime_budget": {"elapsed_sec": 600, "forward_count": 120}}))
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert any("missing result field" in x for x in s["draft_reasons"])


def test_reverse_missing_budget_stays_draft(tmp_path):
    run = _run_root(tmp_path); (run / "formal").mkdir(exist_ok=True)
    man, sha = _manifest(tmp_path)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1", "runtime_budget": {}}))  # 缺实际 elapsed/forward
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert any("elapsed/forward" in x for x in s["draft_reasons"])


def test_reverse_gt_eval_wrong_schema_never_approved(tmp_path):
    # T1：GT_EVAL 存在但 schema 错（非 research_v7_gt_eval_v1）→ 视为无 GT_EVAL，
    # 不得 formal_approved，draft_reasons 记录原因；metrics 回退 RUN_MANIFEST。
    run = _run_root(tmp_path); (run / "formal").mkdir(exist_ok=True)
    man, sha = _manifest(tmp_path)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1",
         "environment": {"executor": "real"},
         "runtime_budget": {"elapsed_sec": 600, "forward_count": 120},
         "timeline": {"duration_sec": 400, "ge180": True},
         "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0},
         "assessor": {"operating_points": {"high_recall_95": 0.9}}}))
    (run / "GT_EVAL.json").write_text(json.dumps(
        {"schema": "research_v7_gt_eval_v2",  # schema 不匹配
         "metrics": {"unit_recall": 0.99, "correct_unit_fpr": 0.0, "gap_recall": 1.0}}))
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert any("GT_EVAL schema invalid" in x for x in s["draft_reasons"])
    assert "gt_eval_path" not in s  # 回退 RUN_MANIFEST.metrics
    assert s["data"]["unit_recall"] == 0.75


def test_reverse_gt_eval_empty_metrics_never_approved(tmp_path):
    # T1：GT_EVAL schema 对但 metrics 为空 dict → 同样视为无 GT_EVAL，不 approved 并记录原因。
    run = _run_root(tmp_path); (run / "formal").mkdir(exist_ok=True)
    man, sha = _manifest(tmp_path)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1",
         "environment": {"executor": "real"},
         "runtime_budget": {"elapsed_sec": 600, "forward_count": 120},
         "timeline": {"duration_sec": 400, "ge180": True},
         "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0},
         "assessor": {"operating_points": {"high_recall_95": 0.9}}}))
    (run / "GT_EVAL.json").write_text(json.dumps(
        {"schema": "research_v7_gt_eval_v1", "metrics": {}}))  # 空 dict
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert any("GT_EVAL metrics empty" in x for x in s["draft_reasons"])
    assert "gt_eval_path" not in s
    assert s["data"]["unit_recall"] == 0.75


def test_reverse_smoke_only_draft(tmp_path):
    run = _run_root(tmp_path)  # 无 formal/ 任何产物
    man, sha = _manifest(tmp_path)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert "smoke" in s["result_source"]  # 无 formal → 用 smoke 且 draft


def _baseline_quality_eval(tmp):
    # 合成 baseline 质量分析产物（research_v7_baseline_quality_analysis_v1），
    # 数值对齐真实 smoke_20260805_review12 formal 产物，不引用真实 run 文件
    f = tmp / "baseline_quality_analysis.json"
    f.write_text(json.dumps({
        "schema": "research_v7_baseline_quality_analysis_v1",
        "generated_at_utc": "2026-08-04T22:58:05+00:00",
        "inputs": {"gt_eval_path": "run/GT_EVAL.json",
                   "gt_axis_note": "synthetic_uniform_timeline_axis (not human GT)"},
        "coverage": {"overall": {"n_rows": 5521, "n_units_evaluated": 10330,
                                 "row_coverage": 0.534463}},
        "boundary_error": {
            "by_boundary": {"start_abs_error_sec": {"n": 5521, "median": 0.2723, "p90": 0.9703}},
            "thresholds": {"0.25": {"threshold_sec": 0.25,
                                    "exceed_rate": {"start": 0.5338, "end": 0.5296,
                                                    "either": 0.6664}}},
        },
        "axis_sensitivity": {
            "m4_synthetic_axis": {"unsafe_rate_gt_0_25": 0.6664},
            "mir_weak_axis": {"unsafe_rate_gt_0_25": 0.0139, "n_rows": 4592,
                              "metric": "boundary_error_same_metric",
                              "median_error_sec": 0.0001},
            "ratio_m4_over_mir": 47.94,
        },
        "seam_strata": {
            "near_seam": {"n_rows": 3273, "unsafe_rate_gt_0_25": 0.6612},
            "far_from_seam": {"n_rows": 2248, "unsafe_rate_gt_0_25": 0.6739},
        },
        "feature_auc": {"per_feature": {
            "has_repair": {"auc": 0.5, "n_valid": 5521},
            "official_duration_sec": {"auc": 0.5348, "n_valid": 5521},
            "raw_end_entropy": {"auc": 0.5779, "n_valid": 5521},
            "either_max_boundary_error_sec": {"auc": 1.0, "n_valid": 5521},
        }},
        "self_check": {"ok": True, "checks": {}},
    }))
    return f


def test_forward_baseline_quality_in_summary(tmp_path):
    # round09：提供 --baseline-quality（合成 json）→ AUTO_SUMMARY.data.baseline_quality 含
    # 8 个提取字段 + baseline_quality_finding；md 增加 Baseline quality 段；formal 判定不受影响。
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    bq = _baseline_quality_eval(tmp_path)
    r = _call(run, man, sha, extra=["--baseline-quality", str(bq)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    bq_out = s["data"]["baseline_quality"]
    assert bq_out["row_coverage"] == 0.534463
    assert bq_out["start_mae_median"] == 0.2723
    assert bq_out["unsafe_rate_gt_0_25"] == 0.6664
    assert bq_out["axis_ratio_m4_over_mir"] == 47.94
    assert bq_out["seam_near_unsafe"] == 0.6612
    assert bq_out["seam_far_unsafe"] == 0.6739
    assert bq_out["feature_auc_top"] == 0.5779  # 排除标签特征 either_max_boundary_error_sec
    assert bq_out["self_check_ok"] is True
    fnd = s["data"]["baseline_quality_finding"]
    assert "GT axis sensitivity (same metric, boundary error)" in fnd
    assert "boundary start MAE median 0.272s" in fnd
    assert "seam has no measurable effect" in fnd
    assert "feature AUC top 0.578 (raw_end_entropy)" in fnd
    assert "self_check=True" in fnd
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "## Baseline quality" in md
    assert "GT axis sensitivity" in md and "self_check=True" in md


def test_forward_baseline_quality_structural_note_with_gt_eval(tmp_path):
    # round09：GT_EVAL 存在且 unit_recall==0（synthetic 轴缺失单元无行）→ finding 追加结构性说明
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    (run / "GT_EVAL.json").write_text(json.dumps(
        {"schema": "research_v7_gt_eval_v1",
         "metrics": {"unit_recall": 0.0, "correct_unit_fpr": 0.0, "gap_recall": 1.0}}))
    bq = _baseline_quality_eval(tmp_path)
    r = _call(run, man, sha, extra=["--baseline-quality", str(bq)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert "unit_recall=0 is structural (deleted units have no rows), not decoder failure" \
        in s["data"]["baseline_quality_finding"]


def test_forward_baseline_quality_absent_is_none(tmp_path):
    # round09：不传 --baseline-quality → baseline_quality/finding 为 None，formal 判定与既有断言不变
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    assert s["data"]["baseline_quality"] is None
    assert s["data"]["baseline_quality_finding"] is None
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "## Baseline quality" not in md


def test_forward_baseline_quality_missing_or_bad_schema_is_none(tmp_path):
    # round09：路径缺失/schema 不匹配 → None（缺省），不阻塞 formal_approved
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    bad = tmp_path / "bad_baseline_quality.json"
    bad.write_text(json.dumps({"schema": "research_v7_baseline_quality_analysis_v2"}))
    r = _call(run, man, sha, extra=["--baseline-quality", str(bad)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert s["data"]["baseline_quality"] is None
    r2 = _call(run, man, sha, extra=["--baseline-quality", str(tmp_path / "nope.json")])
    s2 = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s2["formal_approved"] is True
    assert s2["data"]["baseline_quality"] is None


def test_forward_cross_domain_finding_in_summary(tmp_path):
    # T1：提供 --cross-domain-eval（合成 json）→ AUTO_SUMMARY.data.cross_domain 含
    # M4→MIR finding 与 inputs sha；formal_approved 不受影响；md 增加 Cross-domain assessor 段。
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    cd = _cross_domain_eval(tmp_path)
    r = _call(run, man, sha, extra=["--cross-domain-eval", str(cd)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    cd_out = s["data"]["cross_domain"]
    assert cd_out["unsafe_rate_95"] == 0.9665
    assert cd_out["unsafe_rate_99"] == 0.9972
    assert cd_out["unit_recall_95"] == 0.9611
    assert cd_out["unit_recall_99"] == 0.9949
    assert cd_out["correct_unit_fpr_95"] == 0.9673
    assert cd_out["correct_unit_fpr_99"] == 0.9975
    assert cd_out["score_distribution"] == {"min": 0.100789, "p50": 0.187314,
                                            "p90": 0.198039, "max": 0.211158}
    assert cd_out["n_units"] == 4592
    assert cd_out["m4_operating_points"] == {"high_recall_95": 0.172, "high_recall_99": 0.155}
    assert "cross-domain recalibration required" in cd_out["cross_domain_finding"]
    assert cd_out["inputs"]["mir1k_collection_sha256"] == \
        "eba57b2fa4cb597abb2f1e10297b3a8b4abc01d7e5ff3c2cb2a160cda40c1941"
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "## Cross-domain assessor" in md
    assert "cross-domain recalibration required, not a pass" in md


def test_forward_cross_domain_absent_is_none(tmp_path):
    # T1：不传 --cross-domain-eval → cross_domain 为 None，formal 判定与既有断言不变
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    assert s["data"]["cross_domain"] is None
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "Cross-domain assessor" not in md


def test_forward_cross_domain_missing_file_is_none(tmp_path):
    # T1：传了路径但文件不存在 → None（缺省），不阻塞 formal_approved
    run = _run_root(tmp_path); (run / "formal").mkdir(exist_ok=True)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    r = _call(run, man, sha, extra=["--cross-domain-eval", str(tmp_path / "nope.json")])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert s["data"]["cross_domain"] is None


def _missing_ratio_curve(tmp, full_recall=True):
    # 合成 missing 比例曲线产物（research_v7_missing_ratio_curve_v1），数值对齐真实
    # smoke_20260805_review12 ratio_real_run，不引用真实 run 文件
    f = tmp / "missing_ratio_curve.json"
    g = 1.0 if full_recall else 0.9
    f.write_text(json.dumps({
        "schema": "research_v7_missing_ratio_curve_v1",
        "gt_axis_note": "synthetic_uniform_timeline_axis (not human GT)",
        "curve": [
            {"missing_ratio": 0.1, "n_requests": 60, "n_omitted_gt_units": 588,
             "gap_event_recall": g, "gap_weighted_recall": g, "unit_recall": 0.0},
            {"missing_ratio": 0.25, "n_requests": 60, "n_omitted_gt_units": 1480,
             "gap_event_recall": g, "gap_weighted_recall": g, "unit_recall": 0.0},
            {"missing_ratio": 0.5, "n_requests": 60, "n_omitted_gt_units": 2950,
             "gap_event_recall": g, "gap_weighted_recall": g, "unit_recall": 0.0},
        ],
        "source_gt_eval": "run/GT_EVAL.json",
    }))
    return f


def test_forward_missing_ratio_curve_in_summary(tmp_path):
    # round11：提供 --missing-ratio-curve（合成 json）→ AUTO_SUMMARY.data.missing_ratio_curve
    # 含 6 字段曲线列表 + missing_ratio_conclusion（全 gap_recall=1.0 → 结构性结论）；
    # md 增加 Missing ratio curve 段；formal 判定不受影响。
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    mrc = _missing_ratio_curve(tmp_path)
    r = _call(run, man, sha, extra=["--missing-ratio-curve", str(mrc)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    curve_out = s["data"]["missing_ratio_curve"]
    assert curve_out["schema"] == "research_v7_missing_ratio_curve_v1"
    assert [p["missing_ratio"] for p in curve_out["curve"]] == [0.1, 0.25, 0.5]
    assert [p["n_omitted_gt_units"] for p in curve_out["curve"]] == [588, 1480, 2950]
    assert [p["gap_event_recall"] for p in curve_out["curve"]] == [1.0, 1.0, 1.0]
    assert [p["gap_weighted_recall"] for p in curve_out["curve"]] == [1.0, 1.0, 1.0]
    assert [p["unit_recall"] for p in curve_out["curve"]] == [0.0, 0.0, 0.0]
    assert [p["n_requests"] for p in curve_out["curve"]] == [60, 60, 60]
    assert s["data"]["missing_ratio_conclusion"] == \
        "all missing ratios detected via virtual gap; unit_recall=0 structural"
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "## Missing ratio curve" in md
    assert "all missing ratios detected via virtual gap" in md


def test_forward_missing_ratio_curve_partial_recall_no_structural_conclusion(tmp_path):
    # round11：gap_event_recall 未全 1.0 → missing_ratio_conclusion=None（不得误标结构性结论）
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    mrc = _missing_ratio_curve(tmp_path, full_recall=False)
    r = _call(run, man, sha, extra=["--missing-ratio-curve", str(mrc)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert s["data"]["missing_ratio_curve"]["curve"][0]["gap_event_recall"] == 0.9
    assert s["data"]["missing_ratio_conclusion"] is None


def test_forward_missing_ratio_curve_absent_is_none(tmp_path):
    # round11：不传 --missing-ratio-curve → 两字段为 None，formal 判定与既有断言不变
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    assert s["data"]["missing_ratio_curve"] is None
    assert s["data"]["missing_ratio_conclusion"] is None
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "Missing ratio curve" not in md


def test_forward_missing_ratio_curve_missing_or_bad_schema_is_none(tmp_path):
    # round11：路径缺失/schema 不匹配 → None（缺省），不阻塞 formal_approved
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    bad = tmp_path / "bad_missing_ratio_curve.json"
    bad.write_text(json.dumps({"schema": "research_v7_missing_ratio_curve_v2"}))
    r = _call(run, man, sha, extra=["--missing-ratio-curve", str(bad)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert s["data"]["missing_ratio_curve"] is None
    r2 = _call(run, man, sha, extra=["--missing-ratio-curve", str(tmp_path / "nope.json")])
    s2 = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s2["formal_approved"] is True
    assert s2["data"]["missing_ratio_curve"] is None


def _density_comparison(tmp):
    # 合成 density 档位对比产物（research_v7_density_tier_comparison_v1），数值对齐真实
    # smoke_20260805_review12 formal_v2_run_c DENSITY_TIER_COMPARISON.json，不引用真实 run 文件
    f = tmp / "density_tier_comparison.json"
    f.write_text(json.dumps({
        "schema": "research_v7_density_tier_comparison_v1",
        "source_gt_eval": "run/GT_EVAL.json",
        "density_tiers": {
            "full": {"missing_gap_recall": 1.0, "missing_weighted_recall": 1.0,
                     "replace_wrong_output_recall": 1.0, "n_missing": 60, "n_replace": 60},
            "s2": {"missing_gap_recall": 1.0, "missing_weighted_recall": 1.0,
                   "replace_wrong_output_recall": 0.5, "n_missing": 60, "n_replace": 60},
            "s4": {"missing_gap_recall": 1.0, "missing_weighted_recall": 1.0,
                   "replace_wrong_output_recall": 0.254, "n_missing": 60, "n_replace": 60},
        },
        "finding": "Slot density is robust for missing-gap detection but sensitive for replace.",
    }))
    return f


def test_forward_density_comparison_in_summary(tmp_path):
    # round17：提供 --density-comparison（合成 json）→ AUTO_SUMMARY.data.density_comparison
    # 含三档 missing_gap_recall/replace_wrong_output_recall + density_finding；
    # md 增加 Density tier comparison 段；formal 判定不受影响。
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    dct = _density_comparison(tmp_path)
    r = _call(run, man, sha, extra=["--density-comparison", str(dct)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    dc_out = s["data"]["density_comparison"]
    assert dc_out["schema"] == "research_v7_density_tier_comparison_v1"
    assert [dc_out["tiers"][t]["missing_gap_recall"] for t in ("full", "s2", "s4")] == [1.0, 1.0, 1.0]
    assert [dc_out["tiers"][t]["replace_wrong_output_recall"] for t in ("full", "s2", "s4")] == \
        [1.0, 0.5, 0.254]
    assert s["data"]["density_finding"] == \
        "missing-gap robust across densities; replace wrong-output linearly " \
        "sensitive (1.000/0.500/0.254) - common-anchor scoring required"
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "## Density tier comparison" in md
    assert "common-anchor scoring required" in md


def test_forward_density_comparison_absent_is_none(tmp_path):
    # round17：不传 --density-comparison → 两字段为 None，formal 判定与既有断言不变
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    assert s["data"]["density_comparison"] is None
    assert s["data"]["density_finding"] is None
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "Density tier comparison" not in md


def test_forward_density_comparison_missing_or_bad_schema_is_none(tmp_path):
    # round17：路径缺失/schema 不匹配 → None（缺省），不阻塞 formal_approved
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    bad = tmp_path / "bad_density_comparison.json"
    bad.write_text(json.dumps({"schema": "research_v7_density_tier_comparison_v2"}))
    r = _call(run, man, sha, extra=["--density-comparison", str(bad)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert s["data"]["density_comparison"] is None
    assert s["data"]["density_finding"] is None
    r2 = _call(run, man, sha, extra=["--density-comparison", str(tmp_path / "nope.json")])
    s2 = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s2["formal_approved"] is True
    assert s2["data"]["density_comparison"] is None


_REAL_SONG_LOO_OP95 = [
    0.10159042837473814, 0.10153889793107962, 0.102361589017688, 0.10170434633097908,
    0.10190850753068535, 0.10174160111273825, 0.10169745885115473, 0.10197790720740076,
    0.10192614761749769, 0.10212969586758405, 0.1012893576145071, 0.1021485860654057,
    0.10277150935410588, 0.10198650772538809, 0.10183838273383945, 0.1040845405316562,
    0.1027120978338226, 0.10175553961560063, 0.10196372846635192, 0.10175553961560063,
]


def _family_eval(tmp):
    # 合成 family eval 产物（research_v7_assessor_family_eval_v1），数值对齐真实
    # smoke_20260805_review12 formal_v2_run_c/family_eval/ASSESSOR_FAMILY_EVAL.json
    # （op95 baseline 1.0/missing 0.212/replace 0.261/mixed 0.102、transfer recall99
    # replace 0.177、song-LOO op95 std 0.0006），不引用真实 run 文件
    f = tmp / "family_eval.json"
    f.write_text(json.dumps({
        "schema": "research_v7_assessor_family_eval_v1",
        "family_table": {
            "baseline": {"op95": 1.0, "op99": 1.0, "n_units": 10266},
            "extra": {"op95": 1.0, "op99": 1.0, "n_units": 10266},
            "missing": {"op95": 0.212, "op99": 0.176, "n_units": 7685},
            "replace": {"op95": 0.261, "op99": 0.174, "n_units": 10266},
            "mixed": {"op95": 0.102, "op99": 0.096, "n_units": 38483},
        },
        "conclusions": {
            "family_changes_operating_point": {
                "flag": True, "threshold": 0.05, "max_abs_delta": 0.9042,
            },
            "baseline_missing_to_replace_extra_transfer": {
                "trained_on": ["baseline", "missing"],
                "out_of_family_recall99": {"replace": 0.177},
                "out_of_family_fpr99": {"replace": 0.8813},
            },
        },
        "transfer_baseline_missing": {
            "scored_families": {"replace": {"unit_recall_99": 0.177}},
        },
        "song_loo": {
            "n_songs": len(_REAL_SONG_LOO_OP95),
            "songs": [{"song": f"s{i}", "op95": v} for i, v in enumerate(_REAL_SONG_LOO_OP95)],
        },
    }))
    return f


def test_forward_family_eval_in_summary(tmp_path):
    # round19：提供 --family-eval（合成 json）→ AUTO_SUMMARY.data.family_eval 含
    # family_table（各 family op95/op99 + mixed）/family_changes_op_flag/
    # transfer_recall99_replace/song_loo_op95_std + family_finding（动态格式化）；
    # md 增加 Family / song LOO 段；formal 判定不受影响。
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    fe = _family_eval(tmp_path)
    r = _call(run, man, sha, extra=["--family-eval", str(fe)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    fe_out = s["data"]["family_eval"]
    assert fe_out["schema"] == "research_v7_assessor_family_eval_v1"
    assert fe_out["family_table"]["baseline"]["op95"] == 1.0
    assert fe_out["family_table"]["missing"]["op95"] == 0.212
    assert fe_out["family_table"]["replace"]["op95"] == 0.261
    assert fe_out["family_table"]["replace"]["op99"] == 0.174
    assert fe_out["family_table"]["mixed"]["op95"] == 0.102
    assert set(fe_out["family_table"]) == {"baseline", "extra", "missing", "replace", "mixed"}
    assert fe_out["family_changes_op_flag"] is True
    assert fe_out["transfer_recall99_replace"] == 0.177
    assert abs(fe_out["song_loo_op95_std"] - 0.0005861261581185001) < 1e-9
    assert s["data"]["family_finding"] == \
        "family changes operating point (max delta 0.904); " \
        "baseline+missing assessor does not transfer to replace (recall99 0.177); " \
        "song-LOO op stable (std 0.0006)"
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "## Family / song LOO" in md
    assert "family changes operating point (max delta 0.904)" in md
    assert "song-LOO op stable (std 0.0006)" in md


def test_forward_family_eval_absent_is_none(tmp_path):
    # round19：不传 --family-eval → 两字段为 None，formal 判定与既有断言不变
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    assert s["data"]["family_eval"] is None
    assert s["data"]["family_finding"] is None
    md = (run / "report" / "AUTO_FINDINGS_SUMMARY.md").read_text()
    assert "Family / song LOO" not in md


def test_forward_family_eval_missing_or_bad_schema_is_none(tmp_path):
    # round19：路径缺失/schema 不匹配 → None（缺省），不阻塞 formal_approved
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    bad = tmp_path / "bad_family_eval.json"
    bad.write_text(json.dumps({"schema": "research_v7_assessor_family_eval_v2"}))
    r = _call(run, man, sha, extra=["--family-eval", str(bad)])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert s["data"]["family_eval"] is None
    assert s["data"]["family_finding"] is None
    r2 = _call(run, man, sha, extra=["--family-eval", str(tmp_path / "nope.json")])
    s2 = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s2["formal_approved"] is True
    assert s2["data"]["family_eval"] is None


def test_created_at_utc_is_current_time(tmp_path):
    # round11：AUTO_SUMMARY.created_at_utc 动态取生成时 UTC，不再是硬编码旧值
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["created_at_utc"] != "2026-08-04T00:00:00Z"
    assert s["created_at_utc"].endswith("+00:00")
    from datetime import datetime as dt
    ts = dt.fromisoformat(s["created_at_utc"]).timestamp()
    assert abs(ts - dt.now().timestamp()) < 300
    assert s["schema"] == "research_v7_long_slot_report_v1"
