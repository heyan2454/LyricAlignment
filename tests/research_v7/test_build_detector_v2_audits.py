# -*- coding: utf-8 -*-
"""build_detector_v2_audits.py 测试：三交付物审计 schema 与对账逻辑
（backlog #5；合成数据含 1 个故意不一致项）。"""
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research_v7" / "build_detector_v2_audits.py"
_spec = importlib.util.spec_from_file_location("build_detector_v2_audits", _SCRIPT)
MOD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MOD)


def _make_run(tmp_path):
    (tmp_path / "run2" / "evidence_v2").mkdir(parents=True)
    (tmp_path / "manifests").mkdir()
    # 三个交付物存在 + 一个故意缺失
    (tmp_path / "RUNTIME_BUDGET.json").write_text(
        json.dumps({"target": 10.0, "hard_cap": 12.0, "total_est": 9.5, "budget_ok": True}))
    (tmp_path / "run2" / "SIGNAL_ATLAS.json").write_text("{}")
    (tmp_path / "manifests" / "ANOMALY_MANIFEST.jsonl").write_text(
        json.dumps({"request_id": "always_online:baseline_legal:full"}) + "\n"
        + json.dumps({"request_id": "always_online:baseline_legal:sparse"}) + "\n")
    (tmp_path / "run2" / "manifests").mkdir()
    (tmp_path / "run2" / "manifests" / "ANOMALY_MANIFEST.jsonl").write_text(
        json.dumps({"request_identity": "sha256:runreq0"}) + "\n"
        + json.dumps({"request_identity": "sha256:runreq1"}) + "\n")
    (tmp_path / "manifests" / "MULTIVIEW_MANIFEST.jsonl").write_text("{}")
    # LABELS：20/5/5 歌 + 故意 1 个重复 request_identity + 1 个 manifest 对不上
    lines = []
    for split, n in (("train", 20), ("validation", 5), ("test", 5)):
        for i in range(n):
            for j in range(3):
                lines.append({"request_identity": f"sha256:{split}{i}:{j}",
                              "view_id": "full", "canonical_unit_id": j,
                              "song_id": f"song_{split}_{i}", "split": split,
                              "label": "safe" if j else "unsafe", "target": "raw"})
    lines.append({"request_identity": "sha256:train0:0", "view_id": "full",
                  "canonical_unit_id": 9, "song_id": "song_train_0",
                  "split": "train", "label": "safe", "target": "raw"})
    with (tmp_path / "run2" / "LABELS.jsonl").open("w") as f:
        for r in lines:
            f.write(json.dumps(r) + "\n")
    return tmp_path


def test_precheck_schema_and_split(tmp_path):
    root = _make_run(tmp_path)
    out = MOD.build_precheck(root)
    assert out["schema"] == "precheck_detector_v2_v1"
    items = {i["item"]: i for i in out["deliverables"]}
    assert items["RUNTIME_BUDGET.json"]["exists"]
    assert items["SIGNAL_ATLAS.json"]["exists"]
    assert not items["FROZEN_OPERATING_POINTS.json"]["exists"]
    s = out["checks"]["split_song_grouped"]
    assert s["checked"] and s["train_songs"] == 20 and s["validation_songs"] == 5
    assert s["disjoint"] is True
    assert out["checks"]["runtime_budget"]["budget_ok"] is True


def test_hidden_audit(tmp_path):
    root = _make_run(tmp_path)
    ev_dir = root / "run2" / "evidence_v2"
    (ev_dir / "sha256:abc.jsonl").write_text(json.dumps([
        {"canonical_unit_id": 1, "hidden": {"available": True, "schema": "h1",
                                            "start": {}, "end": {}}},
        {"canonical_unit_id": 2, "hidden": {"available": False}},
        {"schema_version": "x", "counts": {}},  # header 无 canonical_unit_id → 跳过
    ]))
    out = MOD.build_hidden_audit(root, max_rows=100)
    assert out["schema"] == "hidden_extraction_audit_v1"
    assert out["rows_checked"] == 2
    assert out["hidden_available"] == 1
    assert out["hidden_available_rate"] == pytest.approx(0.5)


def test_identity_audit_finds_inconsistency(tmp_path):
    root = _make_run(tmp_path)
    out = MOD.build_identity_audit(root)
    assert out["schema"] == "request_identity_audit_v1"
    # 故意重复：sha256:train0:0 出现 2 次（原 3 行 + 追加 1 行）
    assert out["labels"]["dup_quadruple_rid_view_unit_target"] == 0
    assert out["evidence_files"]["sha256_stems_matched_in_labels"] == 0
    assert out["consistency"]["labels_vs_evidence_files"] == "MISMATCH"
