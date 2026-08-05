# -*- coding: utf-8 -*-
"""Detector V2 evidence schema + leak guard + hidden audit contract tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from lyricalign.research_v7.detector_v2_evidence import (
    EvidenceRow,
    HiddenView,
    OfficialView,
    RawView,
    assert_no_label_leak,
    hidden_blocked,
    hidden_ok,
)


def test_evidence_row_roundtrip():
    row = EvidenceRow(
        request_identity="sha256:x", view_id="full", canonical_unit_id=5,
        raw=RawView(start_sec=1.0, end_sec=1.4, start_entropy=0.5),
        official=OfficialView(start_sec=1.05, end_sec=1.35, repair_start_shift_sec=0.05),
        hidden=HiddenView(available=True, schema="boundary_last4_v1",
                          start={"norm": 1.2}, end={"norm": 0.8}),
        cross_view={"n_views": 2},
    )
    d = row.to_dict()
    assert d["canonical_unit_id"] == 5
    assert d["raw"]["start_entropy"] == 0.5
    assert d["official"]["repair_start_shift_sec"] == 0.05
    assert d["hidden"]["available"] is True
    assert d["cross_view"]["n_views"] == 2


def test_leak_guard_rejects_gt_and_family_fields():
    with pytest.raises(ValueError, match="forbidden label fields"):
        assert_no_label_leak({"raw_duration_sec": 0.4, "gt_start_sec": 1.0})
    with pytest.raises(ValueError, match="forbidden label fields"):
        assert_no_label_leak({"official_duration_sec": 0.3, "mutation_family": "replace"})
    with pytest.raises(ValueError, match="forbidden label fields"):
        assert_no_label_leak({"label": "unsafe"})


def test_leak_guard_passes_clean_features():
    out = assert_no_label_leak({"raw_duration_sec": 0.4, "official_duration_sec": 0.3,
                                "start_entropy": 0.5, "cross_view_diff": 0.01})
    assert out["ok"] is True and out["leak"] == []


def test_hidden_blocked_never_fabricates_zero():
    r = hidden_blocked("token->row mapping failed; hidden route blocked")
    assert r.ok is False
    assert "blocked" in r.reason
    assert r.evidence_sha256 is None


def test_hidden_ok_records_audit():
    r = hidden_ok(mapping={"token": "row", "row": "canonical"},
                  numerical_equivalence={"hook_off": True},
                  evidence_sha256="abc123")
    assert r.ok is True
    assert r.evidence_sha256 == "abc123"
