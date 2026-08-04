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


def _call(run, manifest, sha):
    env = dict(os.environ, PYTHONPATH=str(REPO / "src") + ":" + str(REPO))
    return subprocess.run(
        [sys.executable, str(REPORT), "--run-root", str(run),
         "--formal-approved-manifest", str(manifest), "--expected-manifest-sha256", sha],
        capture_output=True, text=True, env=env)


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


def test_reverse_smoke_only_draft(tmp_path):
    run = _run_root(tmp_path)  # 无 formal/ 任何产物
    man, sha = _manifest(tmp_path)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert "smoke" in s["result_source"]  # 无 formal → 用 smoke 且 draft
