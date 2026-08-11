"""Unit tests for synthetic-GT provenance payloads (no model / no GPU)."""

import json

from lyricalign.research_transition_recovery_detector import gt_provenance


def test_base_payload():
    p = gt_provenance.synthetic_uniform_timeline_provenance()
    assert p["gt_kind"] == "synthetic_uniform_timeline"
    assert p["valid_for_realgt_correctness"] is False
    assert p["result_status"] == "historical_synthetic_gt_diagnostic"
    assert "gt_used_for_routing" not in p
    assert "mode" not in p
    json.dumps(p)


def test_oracle_payload_modes():
    for mode in ("O0", "O1", "O2"):
        p = gt_provenance.synthetic_uniform_timeline_provenance(
            gt_used_for_routing=True, mode=mode
        )
        assert p["gt_used_for_routing"] is True
        assert p["mode"] == mode
        assert p["gt_kind"] == "synthetic_uniform_timeline"
        json.dumps(p)


def test_warning_stderr():
    import io

    buf = io.StringIO()
    gt_provenance.warn_synthetic_gt(stream=buf)
    text = buf.getvalue()
    assert "historical synthetic-GT oracle diagnostic" in text
    assert "not real-GT/no-GT capability" in text
