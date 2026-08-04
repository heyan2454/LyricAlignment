# -*- coding: utf-8 -*-
"""T3：hidden 特征正式声明停用 —— 消费侧拒绝全零占位 hidden 特征训练。

背景（17 复审更新3 #4 / 更新4 #1）：features.row_hidden_features 读 row["hidden"]，
而 real_executor 从不产 hidden → 所有 evidence 的 hidden 特征恒为全零占位，
`assessor_train_eval --include-hidden` 实际喂零向量，属虚假特征声明。
本轮只做声明停用（方案 a）：提取侧保持全零占位现状，消费侧确定性拒绝，
除非显式 `--allow-zero-hidden` 逃逸（兼容旧 smoke）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = str(ROOT / "scripts/research_v7/assessor_train_eval.py")
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False))


def _make_run(tmp_path):
    """guarded run + 1 个 trainable evidence（结构同 evidence_collection 测试 fixture）。"""
    run = tmp_path / "run"; run.mkdir()
    ev_dir = run / "evidence"; ev_dir.mkdir()
    idn = "sha256:hidden_gate_idn"
    _write(ev_dir / f"{idn}.json", {
        "content_identity": idn,
        "attempt": {"status": "ok", "request": {
            "item_id": "song1", "canonical_timeline_file_sha": "tlf1",
            "canonical_timeline_row_sha": "tl1", "canonical_ids": [0, 1],
            "source_window_sec": [40.0, 42.0], "canonical_to_local": {"0": 0, "1": 1}}},
    })
    guard = {
        "trainable_identity_count": 1,
        "trainable": [{"request_identity": idn, "item_id": "song1", "request_id": "r1"}],
        "rejected": [], "rejected_count": 0,
        "denominator": {"all": 1, "trainable": 1, "rejected": 0},
    }
    _write(run / "RUN_MANIFEST.json", {
        "schema": "v1", "run_id": "rl-hidden-gate",
        "code_identity": {"imports_inventory": []},
        "train_filter": guard, "row_audit": [], "cache_keys": [], "evidence_inventory": [],
        "failures": [],
        "requests_identity": [{"evaluation_role": "lyrics_aligned", "text_window_aligned": True}],
    })
    return run, idn


def _make_evidence_with_rows(tmp_path, run, idn, n_units=4, gt_unsafe=(0, 1)):
    """给 evidence 补 decoder official rows + gt_eval（consumer 消费所需）。"""
    ev_path = run / "evidence" / f"{idn}.json"
    ev = json.loads(ev_path.read_text())
    rows = [{"raw_start_sec": i * 0.5, "raw_end_sec": i * 0.5 + 0.4,
             "raw_global_start_sec": i * 0.5, "raw_global_end_sec": i * 0.5 + 0.4,
             "fixed_global_start_sec": i * 0.5, "fixed_global_end_sec": i * 0.5 + 0.4}
            for i in range(n_units)]
    ev["attempt"]["decoder_outputs"] = {"official": {"rows": rows}}
    ev["attempt"]["gt_eval"] = {"unsafe_unit_indices": list(gt_unsafe)}
    ev_path.write_text(json.dumps(ev))
    return run


def _make_guarded_collection(tmp_path):
    """完整 guarded collection（1 evidence / 4 units / 带标签），返回 collection 路径。"""
    sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection
    run, idn = _make_run(tmp_path)
    _make_evidence_with_rows(tmp_path, run, idn, n_units=4, gt_unsafe=(0, 1))
    finalize_collection(collect(run / "RUN_MANIFEST.json", tmp_path / "c.json"),
                        tmp_path / "c.json")
    return tmp_path / "c.json"


def test_hidden_features_disabled_and_zero_placeholder():
    """提取侧现状保持：HIDDEN_FEATURES_ENABLED=False；无 hidden 行 → 全零占位，不伪造非零。"""
    from lyricalign.research_v7.features import (
        HIDDEN_FEATURES_ENABLED, row_hidden_features, unit_features,
    )
    assert HIDDEN_FEATURES_ENABLED is False
    row = {"raw_global_start_sec": 0.5, "raw_global_end_sec": 0.9}
    f = row_hidden_features(row)
    assert set(f) == {"hidden_start_norm", "hidden_end_norm", "hidden_start_end_cosine"}
    assert all(v == 0.0 for v in f.values())
    # include_hidden 只引入全零占位键，绝不产出非零 hidden 值
    u = unit_features(row, include_hidden=True)
    assert u["hidden_start_norm"] == 0.0 and u["hidden_end_norm"] == 0.0
    assert u["hidden_start_end_cosine"] == 0.0


def test_cli_include_hidden_without_escape_fails(tmp_path):
    """17 #4：--include-hidden 无 --allow-zero-hidden → 非零退出且说明原因（不喂零向量）。"""
    c = _make_guarded_collection(tmp_path)
    r = subprocess.run([sys.executable, CLI, "--collection", str(c),
                        "--out", str(tmp_path / "asr"), "--include-hidden"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode != 0
    assert "hidden extraction not enabled" in r.stderr
    assert "zero-placeholder hidden features" in r.stderr
    # 失败是确定性的、且未产出任何产物
    assert not (tmp_path / "asr" / "ASSESSOR_RUN_MANIFEST.json").exists()


def test_cli_include_hidden_with_allow_zero_hidden_runs(tmp_path):
    """--allow-zero-hidden 是显式逃逸：兼容路径可跑通，manifest 记录 hidden 未启用。"""
    c = _make_guarded_collection(tmp_path)
    r = subprocess.run([sys.executable, CLI, "--collection", str(c),
                        "--out", str(tmp_path / "asr"), "--include-hidden",
                        "--allow-zero-hidden"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    m = json.loads((tmp_path / "asr" / "ASSESSOR_RUN_MANIFEST.json").read_text())
    assert m["hidden"] == {"enabled": False,
                           "note": "zero-placeholder rejected unless --allow-zero-hidden"}
    # 即使逃逸，喂进特征矩阵的仍是全零占位（不伪装真实抽取）
    rows = [json.loads(l) for l in (tmp_path / "asr" / "UNIT_FEATURES.jsonl").read_text().splitlines()]
    assert len(rows) == 4
    assert all(fr["features"]["hidden_start_norm"] == 0.0 for fr in rows)
    assert all(fr["features"]["hidden_start_end_cosine"] == 0.0 for fr in rows)


def test_consume_api_refuses_hidden_without_escape(tmp_path):
    """API 层同样确定性拒绝：consume(include_hidden=True) 抛错，除非显式逃逸。"""
    sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from assessor_train_eval import consume
    c = _make_guarded_collection(tmp_path)
    with pytest.raises(ValueError, match="hidden extraction not enabled"):
        consume(c, tmp_path / "out", include_hidden=True)
    # 显式逃逸 → 正常消费，manifest 带 hidden 声明
    m = consume(c, tmp_path / "out2", include_hidden=True, allow_zero_hidden=True)
    assert m["hidden"]["enabled"] is False
    assert isinstance(m["assessor"]["operating_points"], dict)
