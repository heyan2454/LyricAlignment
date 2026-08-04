# -*- coding: utf-8 -*-
"""T4：formal approved 时 RUNTIME_BUDGET 预算外推（estimated_runtime_sec / 12h 容量）正反向测试。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "scripts/research_v7/report_long_slot_region.py"

ELAPSED = 52.621
FORWARD = 120


def _run_root(tmp):
    run = tmp / "run"; (run / "smoke").mkdir(parents=True)
    (run / "smoke" / "LONG_SLOT_SMOKE.json").write_text(json.dumps({
        "timeline": {"duration_sec": 400, "ge180": True}, "slot": {"topology": "three_regions"},
        "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0}}))
    (run / "formal").mkdir(exist_ok=True)
    return run


def _manifest(tmp):
    m = tmp / "frozen.jsonl"; m.write_text('{"a":1}\n')
    return m, hashlib.sha256(m.read_bytes()).hexdigest()


def _approved_run(tmp):
    run = _run_root(tmp)
    man, sha = _manifest(tmp)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps(
        {"run_id": "r1",
         "environment": {"executor": "real"},
         "runtime_budget": {"elapsed_sec": ELAPSED, "forward_count": FORWARD,
                            "cache_hit": 0, "cache_miss": FORWARD},
         "timeline": {"duration_sec": 400, "ge180": True},
         "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0},
         "assessor": {"operating_points": {"high_recall_95": 0.9}}}))
    return run, man, sha


def _call(run, manifest, sha, extra=()):
    env = dict(os.environ, PYTHONPATH=str(REPO / "src") + ":" + str(REPO))
    return subprocess.run(
        [sys.executable, str(REPORT), "--run-root", str(run),
         "--formal-approved-manifest", str(manifest), "--expected-manifest-sha256", sha, *extra],
        capture_output=True, text=True, env=env)


def test_forward_budget_extrapolation(tmp_path):
    # 正向：formal approved 时 RUNTIME_BUDGET 含外推字段，数值 = elapsed/forward × N（默认 600）
    run, man, sha = _approved_run(tmp_path)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    b = json.loads((run / "report" / "RUNTIME_BUDGET.json").read_text())
    assert b["draft"] is False and b["source"] == "formal"
    assert b["estimated_runtime_sec"] == ELAPSED / FORWARD * 600
    assert b["estimated_runtime_sec_n_requests"] == 600
    assert b["estimated_forward_capacity_h12"] == int(12 * 3600 / (ELAPSED / FORWARD))
    assert b["extrapolation_note"] == "单机 GPU 串行、不含批处理并行/cache 复用折算"
    assert b["budget"]["elapsed_sec"] == ELAPSED  # 实际预算保留不动


def test_forward_budget_extrapolate_requests_override(tmp_path):
    # 正向：--extrapolate-requests 覆盖外推请求数
    run, man, sha = _approved_run(tmp_path)
    r = _call(run, man, sha, extra=["--extrapolate-requests", "3600"])
    assert r.returncode == 0, r.stderr
    b = json.loads((run / "report" / "RUNTIME_BUDGET.json").read_text())
    assert b["estimated_runtime_sec"] == ELAPSED / FORWARD * 3600
    assert b["estimated_runtime_sec_n_requests"] == 3600


def test_reverse_smoke_draft_has_no_extrapolation(tmp_path):
    # 负向：smoke draft 分支不含 estimated 字段（不回归破坏现有 draft 输出）
    run = _run_root(tmp_path)  # 无 formal/ 任何产物
    man, sha = _manifest(tmp_path)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["draft"] is True and s["formal_approved"] is False
    b = json.loads((run / "report" / "RUNTIME_BUDGET.json").read_text())
    assert b["draft"] is True
    assert "estimated_runtime_sec" not in b
    assert "estimated_forward_capacity_h12" not in b
    assert "extrapolation_note" not in b
