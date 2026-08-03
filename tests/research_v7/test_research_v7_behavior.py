# -*- coding: utf-8 -*-
"""阶段 B：behavior manifest 与 run behavior suite 的 smoke 测试（纯 CPU）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def _labels(tmp_path, n=6):
    songs = ["水星记", "月半小夜曲", "红豆", "东风破", "晴天", "稻香"]
    rows = [
        {"item_id": f"Sky-1#{s}#{i}", "song_id": s, "duration_sec": str(3.0 + i * 0.4),
         "lyrics_normalized": "庭后天台风声借"[: 4 + i]}
        for i, s in enumerate(songs[:n])
    ]
    f = tmp_path / "labels.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    return f, len(rows)


def test_build_behavior_manifest(tmp_path):
    labels, n = _labels(tmp_path, n=4)
    out = tmp_path / "manifest.jsonl"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/build_behavior_manifest.py"),
         "--labels", str(labels), "--out", str(out), "--limit", "4"],
        capture_output=True, text=True, env=ENV,
    )
    assert r.returncode == 0, r.stderr
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    bytype = Counter(r["mutation_type"] for r in rows)
    assert bytype["baseline"] >= 1
    assert bytype["extra"] >= 1
    assert bytype["missing"] >= 1
    assert bytype["replace"] >= 1
    assert bytype["no_match"] >= 1


def test_run_behavior_suite_smoke(tmp_path):
    labels, _ = _labels(tmp_path, n=2)
    man = tmp_path / "manifest.jsonl"
    subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_behavior_manifest.py"),
                    "--labels", str(labels), "--out", str(man), "--limit", "2"],
                   capture_output=True, text=True, env=ENV, check=True)
    outroot = tmp_path / "suite"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
                        "--manifest", str(man), "--out-root", str(outroot), "--smoke"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    evs = list(outroot.glob("items/*/behavior-*.json"))
    assert len(evs) >= 1
    ev = json.loads(evs[0].read_text())
    assert ev["attempt"]["status"] == "ok"
    assert ev["attempt"]["request"]["mutation_type"] in {
        "baseline", "extra", "missing", "replace", "no_match",
    }
