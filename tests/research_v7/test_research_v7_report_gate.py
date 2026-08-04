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
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    _formal_fixture(run, man, sha)
    r = _call(run, man, sha, extra=["--cross-domain-eval", str(tmp_path / "nope.json")])
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert s["data"]["cross_domain"] is None
