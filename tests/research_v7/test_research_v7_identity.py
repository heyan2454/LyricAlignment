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
