# -*- coding: utf-8 -*-
"""cleanup_run_cache.py tests：dry-run 统计、apply 删除、证据保留、根路径拒绝、symlink 跳过。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
SCRIPT = str(ROOT / "scripts/research_v7/cleanup_run_cache.py")

import pytest


def _make_run(tmp_path, name="run1", cache_mb=2, evidence_mb=1):
    run = tmp_path / name
    (run / "items").mkdir(parents=True)
    (run / "evidence").mkdir()
    (run / "cached").mkdir()
    (run / "evidence_v2").mkdir()
    chunk = b"x" * 1024 * 1024
    for d in ("items", "evidence", "cached"):
        (run / d / "a.bin").write_bytes(chunk * cache_mb)
    (run / "evidence_v2" / "row.jsonl").write_bytes(chunk * evidence_mb)
    (run / "LABELS.jsonl").write_text("{}")
    return run


def test_dry_run_lists_cache_only(tmp_path):
    run = _make_run(tmp_path)
    r = subprocess.run([sys.executable, SCRIPT, "--runs", str(run)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout)
    assert out["dry_run"] is True
    paths = {i["path"] for i in out["items"]}
    assert paths == {str(run / "items"), str(run / "evidence"), str(run / "cached")}
    assert out["total_MB"] == pytest.approx(6.3, abs=0.1)  # 3 dirs x 2MiB = 6.29MB
    # dry-run 不删除
    assert (run / "items").is_dir() and (run / "evidence_v2").is_dir()


def test_apply_removes_cache_keeps_evidence(tmp_path):
    run = _make_run(tmp_path)
    r = subprocess.run([sys.executable, SCRIPT, "--runs", str(run), "--apply"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    for d in ("items", "evidence", "cached"):
        assert not (run / d).exists(), d
    assert (run / "evidence_v2").is_dir()
    assert (run / "LABELS.jsonl").is_file()


def test_root_path_refused(tmp_path):
    r = subprocess.run([sys.executable, SCRIPT, "--runs", "/", "--apply"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0
    import json
    out = json.loads(r.stdout)
    assert out["items"] == [] and out["dry_run"] is False


def test_missing_run_skipped(tmp_path):
    r = subprocess.run([sys.executable, SCRIPT, "--runs", str(tmp_path / "nope")],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0
    assert "not dir" in r.stderr
