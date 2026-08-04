# -*- coding: utf-8 -*-
"""round02：formal 指标回填 —— report 优先读 run/GT_EVAL.json（research_v7_gt_eval_v1）。

覆盖：
- 有 GT_EVAL：formal_approved=true，AUTO_SUMMARY.metrics 取 GT_EVAL 值（unit_recall=0.0 等），
  含 gt_eval_path/gt_axis_note；RUN_MANIFEST.metrics 为 null 不阻塞 formal gate。
- 无 GT_EVAL：回退 RUN_MANIFEST.metrics（fpr 键兼容 correct_unit_fpr）。
- smoke draft 分支不受影响（无 GT_EVAL、无 formal 产物）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "scripts/research_v7/report_long_slot_region.py"

GT_EVAL_METRICS = {
    "unit_recall": 0.0,
    "correct_unit_fpr": 0.0,
    "gap_recall": 1.0,
    "gap_event_recall": 1.0,
    "gap_weighted_recall": 1.0,
    "n_units_evaluated": 10330,
    "n_baseline": 60,
    "n_missing": 60,
    "n_evidence_skipped": 0,
}
GT_AXIS_NOTE = "synthetic_uniform_timeline_axis (not human GT)"


def _run_root(tmp) -> Path:
    run = tmp / "run"; (run / "smoke").mkdir(parents=True)
    (run / "smoke" / "LONG_SLOT_SMOKE.json").write_text(json.dumps({
        "timeline": {"duration_sec": 400, "ge180": True}, "slot": {"topology": "three_regions"},
        "metrics": {"unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0}}))
    (run / "formal").mkdir(exist_ok=True)
    return run


def _manifest(tmp) -> tuple[Path, str]:
    m = tmp / "frozen.jsonl"; m.write_text('{"a":1}\n')
    return m, hashlib.sha256(m.read_bytes()).hexdigest()


def _approved_run(tmp, metrics: dict | None) -> tuple[Path, Path, str]:
    """formal 产物 + RUN_MANIFEST（executor=real、forward>0、timeline/slot/assessor 齐全）。"""
    run = _run_root(tmp)
    man, sha = _manifest(tmp)
    (run / "formal" / "FORMAL_MARKER.json").write_text(json.dumps(
        {"manifest_sha256": sha, "run_id": "r1", "all_gates_passed": True, "runtime_budget_ok": True}))
    (run / "formal" / "RUN_MANIFEST.json").write_text(json.dumps({
        "run_id": "r1",
        "environment": {"executor": "real"},
        "runtime_budget": {"elapsed_sec": 600, "forward_count": 120},
        "timeline": {"duration_sec": 400, "ge180": True},
        "metrics": metrics,
        "assessor": {"operating_points": {"high_recall_95": 0.9}},
        "slot": {"topology": "full+strided", "non_contiguous": True}}))
    return run, man, sha


def _call(run, manifest, sha) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(REPO / "src") + ":" + str(REPO))
    return subprocess.run(
        [sys.executable, str(REPORT), "--run-root", str(run),
         "--formal-approved-manifest", str(manifest), "--expected-manifest-sha256", sha],
        capture_output=True, text=True, env=env)


def test_forward_gt_eval_backfills_metrics_and_gate(tmp_path):
    """有 GT_EVAL：metrics 取 GT_EVAL 值（含 0.0 不回退成 null）、gate 不再因
    RUN_MANIFEST.metrics null 被拒。"""
    run, man, sha = _approved_run(tmp_path, metrics={
        "unit_recall": None, "fpr": None, "gap_recall": None, "n_units": 10330})
    (run / "GT_EVAL.json").write_text(json.dumps({
        "schema": "research_v7_gt_eval_v1",
        "gt_axis_note": GT_AXIS_NOTE,
        "metrics": GT_EVAL_METRICS}, ensure_ascii=False))
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True and s["draft"] is False
    assert s["draft_reasons"] == []
    assert s["gt_eval_path"] == str(run / "GT_EVAL.json")
    assert s["gt_axis_note"] == GT_AXIS_NOTE
    d = s["data"]
    assert d["unit_recall"] == 0.0
    assert d["correct_unit_fpr"] == 0.0
    assert d["gap_recall"] == 1.0
    assert d["gap_weighted_recall"] == 1.0
    assert d["n_units_evaluated"] == 10330
    assert d["n_baseline"] == 60
    assert d["n_missing"] == 60
    assert d["n_evidence_skipped"] == 0


def test_reverse_no_gt_eval_falls_back_to_manifest_fpr(tmp_path):
    """无 GT_EVAL：回退 RUN_MANIFEST.metrics，correct_unit_fpr 兼容 fpr 键。"""
    run, man, sha = _approved_run(tmp_path, metrics={
        "unit_recall": 0.75, "fpr": 0.1, "gap_recall": 1.0})
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is True
    assert "gt_eval_path" not in s
    d = s["data"]
    assert d["unit_recall"] == 0.75
    assert d["correct_unit_fpr"] == 0.1
    assert d["gap_recall"] == 1.0


def test_reverse_gt_eval_absent_metrics_null_stays_draft(tmp_path):
    """负向（gate 语义保留）：无 GT_EVAL 且 RUN_MANIFEST.metrics 为空 → 仍拒绝 approved。"""
    run, man, sha = _approved_run(tmp_path, metrics=None)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert any("missing result field metrics" in x for x in s["draft_reasons"])


def test_smoke_draft_branch_unaffected(tmp_path):
    """smoke draft 分支不受影响：无 GT_EVAL、无 formal 产物 → 用 smoke、draft。"""
    run = _run_root(tmp_path)
    man, sha = _manifest(tmp_path)
    r = _call(run, man, sha)
    assert r.returncode == 0, r.stderr
    s = json.loads((run / "report" / "AUTO_SUMMARY.json").read_text())
    assert s["formal_approved"] is False and s["draft"] is True
    assert "smoke" in s["result_source"]
    assert "gt_eval_path" not in s
    assert s["data"]["unit_recall"] == 0.75  # smoke 源不受影响
    assert s["data"]["correct_unit_fpr"] == 0.1
