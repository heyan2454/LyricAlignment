# -*- coding: utf-8 -*-
"""analyze_stress_signal_gap.py 测试：rank-AUC/KS 计算与输出 schema
（backlog #6；合成可分离数据）。"""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research_v7" / "analyze_stress_signal_gap.py"
_spec = importlib.util.spec_from_file_location("analyze_stress_signal_gap", _SCRIPT)
MOD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MOD)


def test_rank_auc_and_ks():
    rng = np.random.RandomState(0)
    pos = 1.0 + rng.rand(50)
    neg = rng.rand(50)
    auc = MOD.rank_auc(pos, neg)
    assert auc is not None and auc > 0.9
    ks = MOD.ks_stat(pos, neg)
    assert ks is not None and ks > 0.5
    assert MOD.rank_auc(pos, np.array([])) is None
    assert MOD.ks_stat(np.array([]), neg) is None


def test_analyze_schema_with_separable_data(tmp_path):
    from lyricalign.research_v7.detector_v2_evidence import EvidenceRow, RawView

    (tmp_path / "evidence_v2").mkdir()
    rng = np.random.RandomState(1)
    rows = []
    fams = []
    for i in range(30):
        base = rng.rand(3)
        fam = rng.rand(3) + 2.0  # 可分离
        rows.append({"request_identity": f"sha256:r{i}", "view_id": "full",
                     "canonical_unit_id": 0,
                     "raw": {"start_sec": base[0], "end_sec": base[1],
                             "start_entropy": base[2]},
                     "official": {}, "hidden": {}, "cross_view": {}})
        fams.append("baseline_legal")
        rows.append({"request_identity": f"sha256:r{i}", "view_id": "full",
                     "canonical_unit_id": 1,
                     "raw": {"start_sec": fam[0], "end_sec": fam[1],
                             "start_entropy": fam[2]},
                     "official": {}, "hidden": {}, "cross_view": {}})
        fams.append("replace_1")
    with (tmp_path / "evidence_v2" / "sha256:abc.jsonl").open("w") as f:
        json.dump(rows, f)
    with (tmp_path / "LABELS.jsonl").open("w") as f:
        for r, fam in zip(rows, fams):
            f.write(json.dumps({"request_identity": r["request_identity"],
                                "view_id": "full", "canonical_unit_id": r["canonical_unit_id"],
                                "family": fam, "label": "safe", "split": "train"}) + "\n")
    out = MOD.analyze(run_root=tmp_path, min_samples=10)
    assert out["schema"] == "stress_signal_gap_v1"
    assert out["families_analyzed"] == ["replace_1"]
    fam = out["per_family"]["replace_1"]
    assert fam["best"] is not None and fam["best"]["discriminative_auc"] > 0.9
    assert len(fam["top_features"]) <= 5
    assert out["verdict"] in ("weak_signal", "some_signal")
    assert "contract_boundary" in out and "recommendation" in out
