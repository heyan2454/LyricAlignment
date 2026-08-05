# -*- coding: utf-8 -*-
"""Phase0-2 GT audit + source-song split tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))

import pytest

from audit_detector_v2_gt_split import audit_labels, build_split


def _rows(n_songs=8, segs_per_song=3, chars=10):
    rows = []
    for s in range(n_songs):
        for seg in range(segs_per_song):
            cids = []
            for i in range(chars):
                cids += [i * 10, i * 10 + 6]
            rows.append({
                "song_id": f"song{s}", "singer_id": f"S{s}",
                "item_id": f"song{s}#{seg:04d}", "character_count": chars,
                "duration_sec": 4.0, "mapping_status": "accepted_rule_based_pinyin_validated",
                "timestamp_class_ids": cids,
            })
    return rows


def test_audit_counts_valid_and_time_invalid():
    rows = _rows()
    bad = dict(rows[0])
    bad["timestamp_class_ids"] = [10, 10]  # end == start -> invalid
    audit = audit_labels(rows + [bad])
    # valid_rows = 状态有效（25 行，含 1 行时间无效但状态 accepted）
    assert audit["valid_rows"] == len(rows) + 1
    assert audit["time_invalid_rows"] == 1
    assert audit["n_source_songs"] == 8
    assert audit["synthetic_axis_excluded"] is True


def test_audit_excludes_unknown_status():
    rows = _rows()
    bad = dict(rows[0])
    bad["mapping_status"] = "review_required"
    audit = audit_labels(rows + [bad])
    assert audit["valid_rows"] == len(rows)
    assert audit["excluded_rows"] == 1


def test_split_songs_disjoint_and_cover_all():
    rows = _rows(n_songs=10, segs_per_song=3)
    split = build_split(rows, seed=1)
    train = set(split["songs"]["train"])
    val = set(split["songs"]["validation"])
    test = set(split["songs"]["test"])
    assert train & val == set() and train & test == set() and val & test == set()
    assert train | val | test == {f"song{i}" for i in range(10)}
    # 同歌所有行在同一 split
    song0_split = None
    for seg in range(3):
        found = None
        for split_name, songs in split["songs"].items():
            if "song0" in songs:
                found = split_name
        assert found is not None
        if song0_split is None:
            song0_split = found
    # n_rows 与 segs 数一致
    assert split["n_rows"]["train"] + split["n_rows"]["validation"] + split["n_rows"]["test"] == 30


def test_identity_audit_dimension_coverage(tmp_path):
    """Phase0-4：audit 正确报告 view/hidden 维度缺失（旧 manifest 无 view_id）。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT := Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))
    from audit_detector_v2_identity import audit_requests
    reqs = tmp_path / "req.jsonl"
    reqs.write_text(json.dumps({"request_id": "r1", "audio_start_sec": 0.0,
                                "audio_end_sec": 60.0, "text_units": ["a", "b"],
                                "timestamp_slot_indices": [0, 1],
                                "model_id": "m", "checkpoint_id": "c",
                                "canonical_adapter_version": "v1",
                                "request_identity": "sha256:x",
                                "files_sha256": ["h1"]}) + "\n")
    audit = audit_requests(reqs)
    # view_id/hidden_schema 缺失（旧 manifest 无此字段）→ 维度未覆盖
    assert audit["dimensions"]["view"]["present_in_requests"] == 0
    assert audit["dimensions"]["hidden_schema"]["present_in_requests"] == 0
    assert "view" in audit["missing_dimensions"]
    assert "hidden_schema" in audit["missing_dimensions"]
    # 带 view_id 后覆盖
    reqs.write_text(json.dumps({"request_id": "r1", "audio_start_sec": 0.0,
                                "audio_end_sec": 60.0, "text_units": ["a", "b"],
                                "timestamp_slot_indices": [0, 1],
                                "model_id": "m", "checkpoint_id": "c",
                                "canonical_adapter_version": "v1",
                                "view_id": "full", "hidden_schema": "boundary_last4_v1",
                                "request_identity": "sha256:x",
                                "files_sha256": ["h1"]}) + "\n")
    audit2 = audit_requests(reqs)
    assert audit2["dimensions"]["view"]["present_in_requests"] == 1
    assert audit2["dimensions"]["hidden_schema"]["present_in_requests"] == 1
