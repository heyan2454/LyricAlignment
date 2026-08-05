# -*- coding: utf-8 -*-
"""Phase C matched common-unit view eval tests（22 §3.2/§8.1）：全空/配对/过滤语义。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))

from evaluate_matched_views import _items_map, _matched_comparison


def _label(rid, view, cid, label="safe"):
    return {"request_identity": rid, "view_id": view, "canonical_unit_id": cid,
            "label": label, "family": "baseline_legal", "target": "official",
            "song_id": "songA"}


def test_items_map_from_dir(tmp_path):
    it = tmp_path / "items"
    (it / "songA:0:baseline_legal:full").mkdir(parents=True)
    (it / "songA:0:baseline_legal:full" / "sha1.json").write_text("{}")
    (it / "songA:0:baseline_legal:sparse").mkdir()
    (it / "songA:0:baseline_legal:sparse" / "sha2.json").write_text("{}")
    m = _items_map(tmp_path)
    assert m == {"sha1": ("songA", "0", "baseline_legal"),
                 "sha2": ("songA", "0", "baseline_legal")}


def test_matched_common_units_only():
    """22 §3.3.4：matched 比较分母 = query-set 交集（full 4 / sparse 2 → 2）。"""
    labels = [
        _label("sha1", "full", 0), _label("sha1", "full", 1),
        _label("sha1", "full", 2), _label("sha1", "full", 3),
        _label("sha2", "sparse", 0), _label("sha2", "sparse", 2),
    ]
    items = {"sha1": ("songA", "0", "baseline_legal"), "sha2": ("songA", "0", "baseline_legal")}
    out = _matched_comparison(labels, "baseline_legal", "official", items)
    fp = out["view_pairs"]["full_vs_sparse"]
    assert fp["n_matched_units"] == 2  # units {0, 2}
    assert fp["agree_rate"] == 1.0
    assert fp["safe_accept_agree_rate"] == 1.0


def test_matched_gt_unavailable_excluded():
    """gt_unavailable 不参与 matched 分母。"""
    labels = [
        _label("sha1", "full", 0), _label("sha1", "full", 1),
        _label("sha2", "sparse", 0), _label("sha2", "sparse", 1),
    ]
    labels[1]["label"] = "gt_unavailable"
    items = {"sha1": ("songA", "0", "baseline_legal"), "sha2": ("songA", "0", "baseline_legal")}
    out = _matched_comparison(labels, "baseline_legal", "official", items)
    fp = out["view_pairs"]["full_vs_sparse"]
    assert fp["n_matched_units"] == 1  # unit 0 仅剩
    assert fp["transition_matrix"] == {"safe->safe": 1}


def test_matched_transition_matrix_and_agree():
    labels = [
        _label("sha1", "full", 0, "safe"), _label("sha1", "full", 1, "unsafe"),
        _label("sha2", "sparse", 0, "safe"), _label("sha2", "sparse", 1, "safe"),
    ]
    items = {"sha1": ("songA", "0", "baseline_legal"), "sha2": ("songA", "0", "baseline_legal")}
    out = _matched_comparison(labels, "baseline_legal", "official", items)
    fp = out["view_pairs"]["full_vs_sparse"]
    assert fp["n_matched_units"] == 2
    assert fp["agree_rate"] == 0.5
    assert fp["safe_accept_agree_rate"] == 1.0  # unit 0 双方 safe
    assert fp["transition_matrix"] == {"safe->safe": 1, "unsafe->safe": 1}
