# -*- coding: utf-8 -*-
"""Phase3-3b evaluate_stress_detector_v2 tests（合成 fixture，纯内存）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))

import pytest

from evaluate_stress_detector_v2 import _score_stress, GT_FAMILIES


def _rows(target, n, label_frac, family, label="safe"):
    out = []
    for u in range(n):
        unsafe = u < int(n * label_frac)
        feats = {"raw_duration_sec": 0.4, "raw_end_entropy": 1.0 if unsafe else 0.1,
                 "official_duration_sec": 0.4, "ro_start_shift_sec": 1.0 if unsafe else 0.0,
                 "ro_end_shift_sec": 0.0, "has_repair": 0, "repair_run_length": 0}
        out.append({"request_identity": f"r:{u}", "canonical_unit_id": u,
                    "target": target,
                    "label": ("unsafe" if unsafe else "safe") if label == "mix"
                             else label,
                    "features": feats, "family": family})
    return out


def _frozen_op():
    return {"raw": {"best_combo": "O",
                    "operating_points": {"T_accept": 0.5, "T_reject": 0.8}},
            "official": {"best_combo": "O",
                         "operating_points": {"T_accept": 0.5, "T_reject": 0.8}}}


def _by_target():
    m4_train = {t: _rows(t, 200, 0.5, "baseline_legal", label="mix")
                for t in ("raw", "official")}
    stress = {"raw": [], "official": []}
    for t in ("raw", "official"):
        stress[t].extend(_rows(t, 40, 0.5, "baseline_legal", label="mix"))
        stress[t].extend(_rows(t, 30, 1.0, "replace_2", label="ambiguous"))
        stress[t].extend(_rows(t, 25, 1.0, "missing_4", label="ambiguous"))
        stress[t].extend(_rows(t, 20, 1.0, "acoustic_difficulty", label="ambiguous"))
    return {"m4_train": m4_train, "stress": stress}


def test_stress_gt_family_metrics():
    out = _score_stress(_by_target(), _frozen_op())
    for t in ("raw", "official"):
        v = out["targets"][t]
        assert v["n_train"] == 200
        assert v["n_score"] == 40 + 30 + 25 + 20
        fv = v["by_family"]["baseline_legal"]
        assert fv["gt_kind"] == "labels"
        assert fv["tri_unit_metrics"]["protected_recall"] == pytest.approx(1.0)


def test_stress_ambiguous_family_no_gt_kind():
    out = _score_stress(_by_target(), _frozen_op())
    for t in ("raw", "official"):
        v = out["targets"][t]
        for fam in ("replace_2", "missing_4", "acoustic_difficulty"):
            fv = v["by_family"][fam]
            assert fv["gt_kind"] == "no_occurrence_gt_ambiguity"
            assert fv["n_units"] > 0
            rates = fv["accept_rate"] + fv["reject_rate"] + fv["uncertain_rate"]
            assert rates == pytest.approx(1.0)
            assert fv["accept_rate"] <= 0.05  # 压力口径：detector 不得大量 accept


def test_stress_insufficient_data():
    out = _score_stress({"m4_train": {"raw": [], "official": []}, "stress": {"raw": [], "official": []}},
                        _frozen_op())
    for t in ("raw", "official"):
        assert out["targets"][t]["status"] == "insufficient_data"


def test_build_matrix_keep_labels(tmp_path):
    """keep_labels 扩展：ambiguous/grey 行保留（默认行为不变）。"""
    import numpy as np
    from train_detector_v2 import build_matrix
    from lyricalign.research_v7.detector_v2_evidence import EvidenceRow
    ev = tmp_path / "evidence_v2"
    ev.mkdir()
    rows = []
    for u in range(6):
        d = {"request_identity": "rid", "view_id": "full", "canonical_unit_id": u,
             "raw": {"start_sec": u, "end_sec": u + 0.5, "start_entropy": 1.0,
                     "end_entropy": 1.0, "start_margin": 0.5, "end_margin": 0.5,
                     "topk": [1, 2, 3]},
             "official": {"start_sec": 0.0, "end_sec": 0.5,
                          "repair_start_shift_sec": 0.0, "repair_end_shift_sec": 0.0},
             "hidden": {}, "cross_view": {}}
        rows.append(d)
    (ev / "rid.jsonl").write_text(json.dumps(rows) + "\n")
    labels = tmp_path / "labels.jsonl"
    lab = []
    for u in range(6):
        label = ["safe", "unsafe", "ambiguous", "grey", "safe", "unsafe"][u]
        lab.append(json.dumps({"request_identity": "rid", "canonical_unit_id": u,
                               "target": "official", "label": label, "split": "train"}))
    labels.write_text("\n".join(lab) + "\n")
    bt_default = build_matrix(ev, labels)
    bt_keep = build_matrix(ev, labels, keep_labels=("safe", "unsafe", "ambiguous", "grey"))
    assert len(bt_default["official"]["train"]) == 4  # 默认只 safe/unsafe
    assert len(bt_keep["official"]["train"]) == 6  # 扩展保留全部
