# -*- coding: utf-8 -*-
"""review9-6：evidence collection CLI（唯一 train/eval 入口）单测。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False))


def _make_run(tmp_path, with_guard=True):
    run = tmp_path / "run"; run.mkdir()
    ev_dir = run / "evidence"; ev_dir.mkdir()
    # 两个 evidence：一个 trainable(lyrics_aligned)、一个 probe(被拒)
    train_idn = "sha256:trainable_idn"
    _write(ev_dir / f"{train_idn}.json", {
        "content_identity": train_idn,
        "attempt": {"status": "ok", "request": {
            "item_id": "song1", "canonical_timeline_file_sha": "tlf1",
            "canonical_timeline_row_sha": "tl1", "canonical_ids": [0, 1],
            "source_window_sec": [40.0, 42.0], "canonical_to_local": {"0": 0, "1": 1}}},
    })
    guard = {
        "trainable_identity_count": 1,
        "trainable": [{"request_identity": train_idn, "item_id": "song1", "request_id": "r1"}],
        "rejected": [{"item_id": "pr", "reason": "role_not_lyrics_aligned"}],
        "rejected_count": 1,
        "denominator": {"all": 2, "trainable": 1, "rejected": 1},
    }
    _write(run / "RUN_MANIFEST.json", {
        "schema": "v1", "run_id": "rl-test",
        "code_identity": {"imports_inventory": []},
        "train_filter": guard if with_guard else {"error": "none"},
        "row_audit": [], "cache_keys": [], "evidence_inventory": [], "failures": [],
        "requests_identity": [{"evaluation_role": "lyrics_aligned", "text_window_aligned": True}],
    })
    return run, train_idn


def test_collect_returns_only_trainable_evidence(tmp_path):
    run, train_idn = _make_run(tmp_path)
    out = tmp_path / "collection.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/collect_trainable_evidence.py"),
                        "--run-manifest", str(run / "RUN_MANIFEST.json"), "--out", str(out)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    c = json.loads(out.read_text())
    assert len(c["trainable_evidence"]) == 1
    assert c["trainable_evidence"][0]["request_identity"] == train_idn
    assert c["guard"]["rejected_count"] == 1
    # canonical lineage 从 evidence.request 带入 collection
    assert c["trainable_evidence"][0]["canonical_timeline_row_sha"] == "tl1"
    assert c["trainable_evidence"][0]["canonical_timeline_file_sha"] == "tlf1"
    assert c["trainable_evidence"][0]["canonical_ids"] == [0, 1]
    assert c["trainable_evidence"][0]["source_window_sec"] == [40.0, 42.0]


def test_collect_refuses_un_guarded_manifest(tmp_path):
    run, _ = _make_run(tmp_path, with_guard=False)
    out = tmp_path / "collection.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/collect_trainable_evidence.py"),
                        "--run-manifest", str(run / "RUN_MANIFEST.json"), "--out", str(out)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 1
    assert "not guarded" in r.stderr
    assert not out.exists()


def test_collect_importable():
    sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    import importlib
    m = importlib.import_module("collect_trainable_evidence")
    assert callable(m.collect)


def test_collection_has_sha_and_verified_load(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection, load_verified
    run, train_idn = _make_run(tmp_path)
    c = collect(run / "RUN_MANIFEST.json", tmp_path / "c.json")
    c = finalize_collection(c, tmp_path / "c.json")
    # 带 collection_sha256
    assert c["collection_sha256"]
    # 消费者唯一入口：校验 guard + evidence 存在
    loaded, sha = load_verified(tmp_path / "c.json")
    assert sha == c["collection_sha256"]
    assert loaded["trainable_evidence"][0]["request_identity"] == train_idn


def test_verified_load_rejects_un_guarded_collection(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import load_verified
    # 手工构造缺 guard 的 collection
    run, _ = _make_run(tmp_path, with_guard=False)
    c = {"collection_sha256": "x", "trainable_evidence": [], "guard": {}}
    (tmp_path / "bad.json").write_text(json.dumps(c)) if isinstance(tmp_path, object) else None
    # guard present is False → 拒绝
    import pytest as _pt
    with _pt.raises(ValueError):
        load_verified(tmp_path / "bad.json")
