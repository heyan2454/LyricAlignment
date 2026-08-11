#!/usr/bin/env python3
"""WP0 quick_correction_audit 纯函数快测（不跑实际扫描，不加载模型）。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from research_transition_recovery_detector import quick_correction_audit as qca


def test_synthetic_gt_hit_oracle_recovery_override():
    text = (
        "gt = {int(u['canonical_unit_id']): u for u in row['canonical_units']}\n"
        "wrong = [r for r in rows if abs(float(r['fixed_global_start_sec']) - gt[i]['start_sec']) > TOLERANCE]\n"
    )
    cls = qca.classify_synthetic_gt(text, "run_oracle_recovery.py")
    assert cls["gt_source"] == "LONG_TIMELINE_MANIFEST.canonical_units (start_sec/end_sec)"
    assert cls["synthetic"] is True
    assert cls["synthetic_kind"] == "synthetic_uniform_timeline"
    assert cls["used_for_correctness"] is True
    assert cls["valid_for_realgt_correctness"] is False
    assert cls["conclusion_affected"] is True
    assert cls["pattern_counts"]["canonical_units"] == 1


def test_synthetic_gt_heuristic_hit():
    text = (
        "canonical_units\n"
        "rows = infer(...)\n"
        "if abs(float(r['start_sec']) - gt[i]['start_sec']) <= TOLERANCE:\n"
        "    correct += 1\n"
    )
    cls = qca.classify_synthetic_gt(text, "synthetic_subwindow_demo.py")
    assert cls["used_for_correctness"] is True
    assert cls["method"] == "heuristic"
    assert cls["gt_source"] == "canonical_units (source context unknown)"


def test_synthetic_gt_known_overrides():
    """三个已知覆盖（含两个 subwindow 脚本）必须返回锁定结论。"""
    for fn in ("run_oracle_recovery.py", "eval_rule_subwindow.py", "eval_subwindow.py"):
        cls = qca.classify_synthetic_gt("canonical_units start_sec raw_global_start_sec <= 1.0", fn)
        assert cls["synthetic"] is True, fn
        assert cls["synthetic_kind"] == "synthetic_uniform_timeline", fn
        assert cls["used_for_correctness"] is True, fn
        assert cls["valid_for_realgt_correctness"] is False, fn
        assert cls["conclusion_affected"] is True, fn
        assert cls["method"] == "known_override", fn


def test_extract_candidates_f5_filters():
    """F5：非路径 token 不成为候选；docs/ 与 runs/ 路径被提取。"""
    line = (
        "用 `n_units / duration` 与 `0.901/0.857`、`gt=0/1` 表示比例；"
        "见 `docs/plan/07.md` 与 `runs/20260810/x.json` 和 [链接](scripts/demo/run.sh)"
    )
    recs = qca._extract_candidates(line)
    paths = [r["path"] for r in recs if r["path"]]
    filtered = [r for r in recs if r["path"] is None]
    for bad in ("n_units / duration", "0.901/0.857", "gt=0/1"):
        assert bad not in paths, bad
    assert "docs/plan/07.md" in paths
    assert "runs/20260810/x.json" in paths
    assert "scripts/demo/run.sh" in paths
    assert len(filtered) >= 3
    assert any("ratio" in r["classification"] or "math" in r["classification"]
               or "natural_lang" in r["classification"] for r in filtered)


def test_synthetic_gt_no_correctness():
    text = "window_start_sec = units[s].start_sec\nwindow_end_sec = units[e].end_sec\n"
    cls = qca.classify_synthetic_gt(text, "semantic_window_planning.py")
    assert cls["used_for_correctness"] is False
    assert cls["gt_source"] == "canonical units (start_sec/end_sec) consumed for window geometry"


def test_classify_reference_present(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "src" / "x.py").write_text("", encoding="utf-8")
    rec = qca.classify_reference("src/x.py", repo / "docs", repo)
    assert rec["present"] is True
    assert rec["missing"] is False


def test_classify_reference_missing(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    rec = qca.classify_reference("src/nothere.py", repo / "docs", repo)
    assert rec["present"] is False
    assert rec["missing"] is True
    assert rec["recovered"] is False
    assert "not present in current archive" in rec["notes"]


def test_classify_reference_missing_but_recovered_by_basename(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "src" / "elsewhere").mkdir(parents=True)
    (repo / "src" / "elsewhere" / "wanted.py").write_text("", encoding="utf-8")
    rec = qca.classify_reference("docs/20260807/wanted.py", repo / "docs", repo)
    assert rec["missing"] is True
    assert rec["recovered"] is True
    assert rec["recovery_source"].endswith("wanted.py")


def test_classify_reference_external(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    for cand in ("https://example.com/a", "/home/hyan/Data/x.py", "#section"):
        rec = qca.classify_reference(cand, repo / "docs", repo)
        assert rec["missing"] is False
        assert "external" in rec["notes"]
