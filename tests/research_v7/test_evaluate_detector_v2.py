# -*- coding: utf-8 -*-
"""Phase3 evaluate_detector_v2 tests（合成 fixture，纯内存）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))

import pytest

from evaluate_detector_v2 import _family_map, _load_frozen_op


def _make_by_target(tmp_path, n_songs=3):
    """3 歌：train 2 / test 1；2 family（crop_late/end_early）；已知 unsafe 块。"""
    from train_detector_v2 import build_matrix
    # 直接用 build_matrix 需要 evidence_v2 + LABELS 文件；这里手工构造 by_target 结构
    import numpy as np
    by_target = {
        "hidden_available_any": False,
        "raw": {"train": [], "validation": [], "test": []},
        "official": {"train": [], "validation": [], "test": []},
    }
    for target in ("raw", "official"):
        for si, song in enumerate(("song_a", "song_b", "song_c")):
            split = "train" if si < 2 else "test"
            fam = "crop_late" if si % 2 == 0 else "end_early"
            for u in range(12):
                label = "unsafe" if (u >= 5 and u <= 7) else "safe"
                feats = {"raw_duration_sec": 0.4, "raw_end_entropy": 0.5 + (0.1 if label == "unsafe" else 0.0),
                         "official_duration_sec": 0.4, "ro_start_shift_sec": 0.0,
                         "ro_end_shift_sec": 0.0, "has_repair": 0, "repair_run_length": 0}
                by_target[target][split].append({
                    "request_identity": f"{song}:req", "canonical_unit_id": u,
                    "target": target, "label": label, "features": feats,
                    "family": fam})
    return by_target


def test_family_map():
    p = Path("/tmp/fam.jsonl")
    p.write_text(json.dumps({"request_identity": "r", "canonical_unit_id": 1,
                             "target": "raw", "family": "crop_late"}) + "\n")
    m = _family_map(p)
    assert m[("r", 1, "raw")] == "crop_late"


def test_load_frozen_op_single_and_dual():
    p = Path("/tmp/fop.json")
    p.write_text(json.dumps({"best_combo": "O", "operating_points": {
        "T_accept": 0.5, "T_reject": 0.8}}))
    d = _load_frozen_op(p)
    assert d["raw"]["operating_points"]["T_accept"] == 0.5
    p2 = Path("/tmp/fop2.json")
    p2.write_text(json.dumps({"raw": {"best_combo": "O", "operating_points": {"T_accept": 0.4, "T_reject": 0.7}},
                              "official": {"best_combo": "O", "operating_points": {"T_accept": 0.3, "T_reject": 0.6}}}))
    d2 = _load_frozen_op(p2)
    assert d2["raw"]["operating_points"]["T_accept"] == 0.4
    assert d2["official"]["operating_points"]["T_accept"] == 0.3
