# -*- coding: utf-8 -*-
"""WP1 严格 request identity 单测（15 蓝图 §3）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.requests import AlignmentRequest

CTX = {"code": "test", "audio_hash": "h1", "mapping_schema": "v1"}


def _req(units=("春", "风", "绿"), slot=None, mutation="baseline", decoder="official"):
    return AlignmentRequest(
        request_id="rid", item_id="i1", parent_request_id=None,
        audio_source="demucs_vocal", audio_start_sec=0.0, audio_end_sec=60.0,
        text_source="labels", text_start_index=0, text_end_index=len(units),
        text_units=units, timestamp_slot_indices=slot, workflow_mode="behavior",
        mutation_type=mutation, mutation_parameters={}, model_id="Q",
        checkpoint_id="r2", input_variant="text",
    )


def test_identity_stable_same_input():
    assert _req().request_identity(context=CTX) == _req().request_identity(context=CTX)


def test_identity_text_sensitive():
    a = _req(units=("春", "风", "绿"))
    b = _req(units=("春", "风"))
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)


def test_identity_slot_sensitive():
    a = _req(slot=None)
    b = _req(slot=(0, 1))
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)


def test_identity_mutation_sensitive():
    assert _req(mutation="baseline").request_identity(context=CTX) != \
           _req(mutation="extra").request_identity(context=CTX)


def test_identity_context_sensitive():
    assert _req().request_identity(context=CTX) != _req().request_identity(context={"code": "x"})


def _creq(units=("乙", "女"), cstart=0, cend=2, cmap=None, tl_sha="tl1", tlfile="tlfile1",
          cids=None, sw=(40.0, 42.0), adapter="c3_text_adapter_v1"):
    return AlignmentRequest(
        request_id="rid", item_id="i1", parent_request_id=None,
        audio_source="demucs_vocal", audio_start_sec=0.0, audio_end_sec=2.0,
        text_source="canon", text_start_index=0, text_end_index=len(units),
        text_units=units, timestamp_slot_indices=None, workflow_mode="behavior",
        mutation_type="baseline", mutation_parameters={}, model_id="Q",
        checkpoint_id="r2", input_variant="text",
        canonical_text_start=cstart, canonical_text_end=cend,
        canonical_to_local=cmap if cmap is not None else {i: i for i in range(len(units))},
        canonical_ids=list(cids) if cids is not None else list(range(len(units))),
        canonical_timeline_row_sha=tl_sha,
        canonical_timeline_file_sha=tlfile, canonical_adapter_version=adapter,
        source_window_sec=sw,
    )


def test_identity_canonical_to_local_sensitive():
    # review9-2：仅 canonical mapping 不同 → identity 必须不同（同一音频/文本、不同原曲解释）
    a = _creq(cmap={0: 0, 1: 1})
    b = _creq(cmap={0: 1, 1: 0})
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)


def test_identity_canonical_range_sensitive():
    a = _creq(cstart=0, cend=2)
    b = _creq(cstart=40, cend=42)
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)


def test_identity_timeline_sha_sensitive():
    a = _creq(tl_sha="tl1")
    b = _creq(tl_sha="tl2")
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)


def test_identity_source_window_sensitive():
    a = _creq(sw=(40.0, 42.0))
    b = _creq(sw=(40.1, 42.0))
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)


def test_identity_canonical_ids_only_sensitive():
    # review10-1：仅 explicit canonical id list 改变（range/mapping 相同）→ identity 必须变
    a = _creq(cids=[2, 5])
    b = _creq(cids=[2, 6])
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)


def test_identity_timeline_file_sha_sensitive():
    # review10-3：文件级 SHA 与行级 SHA 分设且都敏感
    a = _creq(tlfile="f1")
    b = _creq(tlfile="f2")
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)


def test_identity_timeline_row_sha_sensitive():
    a = _creq(tl_sha="f1")
    b = _creq(tl_sha="f2")
    assert a.request_identity(context=CTX) != b.request_identity(context=CTX)
