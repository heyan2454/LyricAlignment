"""real_gt.py 安全投影单元测试（Stage 1 of Doc 19）。

全部使用内联合成 fixture，不依赖真实 overlay/annotations 数据。
"""
import json

import pytest

from lyricalign.research_transition_recovery_detector.real_gt import (
    EXCLUSION_REASONS,
    load_real_gt,
    load_real_gt_with_audit,
    write_real_gt_outputs,
)

ACC = "accepted_rule_based_pinyin_validated"
HELD = "accepted_rule_validated_held_vowel"
REVIEW = "review_required_pinyin_parse_ambiguous"


def _unit(cid, seg, idx, text, start=0.0, end=10.0):
    return {
        "canonical_unit_id": str(cid),
        "source_segment_id": seg,
        "source_unit_index": idx,
        "start_sec": start,
        "end_sec": end,
        "text": text,
    }


def _ann(song, item, idx, start, end, status=ACC, char="x"):
    return {
        "song_id": song,
        "item_id": item,
        "character_index": idx,
        "start_sec": start,
        "end_sec": end,
        "mapping_status": status,
        "normalized_character": char,
        "raw_character": char,
    }


def _write_manifest(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _write_annotations(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _manifest_row(song, units, offsets):
    return {"song_id": song, "canonical_units": units, "segment_offsets": offsets}


@pytest.fixture
def paths(tmp_path):
    man = tmp_path / "LONG_TIMELINE_MANIFEST.jsonl"
    ann = tmp_path / "m4singer_character_annotations.jsonl"
    return man, ann


def test_both_boundaries_projected_with_offset_multi_segment(paths):
    man, ann = paths
    _write_manifest(man, [
        _manifest_row("S1", [
            _unit(0, "A", 0, "x"),
            _unit(1, "B", 0, "y"),
        ], [
            {"source_segment_id": "A", "global_start_sec": 100.0},
            {"source_segment_id": "B", "global_start_sec": 200.0},
        ]),
    ])
    _write_annotations(ann, [
        _ann("S1", "A", 0, 5.0, 8.0),
        _ann("S1", "B", 0, 1.0, 2.5, char="y"),
    ])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert real_gt["S1"][0] == {"start_sec": 105.0, "end_sec": 108.0, "text": "x",
                                "status": ACC, "source_segment_id": "A", "source_unit_index": 0}
    assert real_gt["S1"][1]["start_sec"] == 201.0
    assert real_gt["S1"][1]["end_sec"] == 202.5
    assert all(v == 0 for v in audit["S1"].values())


def test_repeated_text_binds_segment_local_index(paths):
    man, ann = paths
    _write_manifest(man, [
        _manifest_row("S1", [
            _unit(0, "A", 0, "hao"),
            _unit(1, "B", 0, "hao"),
        ], [
            {"source_segment_id": "A", "global_start_sec": 0.0},
            {"source_segment_id": "B", "global_start_sec": 50.0},
        ]),
    ])
    _write_annotations(ann, [
        _ann("S1", "A", 0, 1.0, 2.0, char="hao"),
        _ann("S1", "B", 0, 7.0, 9.0, char="hao"),
    ])
    real_gt, _ = load_real_gt_with_audit(ann, man)
    assert real_gt["S1"][0]["start_sec"] == 1.0
    assert real_gt["S1"][0]["end_sec"] == 2.0
    assert real_gt["S1"][1]["start_sec"] == 57.0
    assert real_gt["S1"][1]["end_sec"] == 59.0


def test_review_row_with_timestamps_still_excluded(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "x")],
                                        [{"source_segment_id": "A", "global_start_sec": 0.0}])])
    _write_annotations(ann, [_ann("S1", "A", 0, 1.0, 2.0, status=REVIEW)])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert 0 not in real_gt["S1"]
    assert audit["S1"]["review_status"] == 1


def test_no_synthetic_end_leakage(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "x", start=1.0, end=9999.0)],
                                        [{"source_segment_id": "A", "global_start_sec": 10.0}])])
    _write_annotations(ann, [_ann("S1", "A", 0, 5.0, 8.0)])
    real_gt, _ = load_real_gt_with_audit(ann, man)
    assert real_gt["S1"][0]["start_sec"] == 15.0
    assert real_gt["S1"][0]["end_sec"] == 18.0
    assert real_gt["S1"][0]["end_sec"] != 9999.0


def test_text_mismatch_excluded(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "hao")],
                                        [{"source_segment_id": "A", "global_start_sec": 0.0}])])
    _write_annotations(ann, [_ann("S1", "A", 0, 1.0, 2.0, char="ha")])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert 0 not in real_gt["S1"]
    assert audit["S1"]["text_or_index_mismatch"] == 1


def test_missing_row_at_index_is_text_or_index_mismatch(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 3, "x")],
                                        [{"source_segment_id": "A", "global_start_sec": 0.0}])])
    _write_annotations(ann, [_ann("S1", "A", 0, 1.0, 2.0)])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert 0 not in real_gt["S1"]
    assert audit["S1"]["text_or_index_mismatch"] == 1


def test_bad_interval_end_before_start_and_equal(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "x"), _unit(1, "A", 1, "y")],
                                        [{"source_segment_id": "A", "global_start_sec": 0.0}])])
    _write_annotations(ann, [
        _ann("S1", "A", 0, 5.0, 2.0),
        _ann("S1", "A", 1, 3.0, 3.0),
    ])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert 0 not in real_gt["S1"] and 1 not in real_gt["S1"]
    assert audit["S1"]["bad_interval"] == 2


def test_missing_segment_offset(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "x")], [])])
    _write_annotations(ann, [_ann("S1", "A", 0, 1.0, 2.0)])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert 0 not in real_gt["S1"]
    assert audit["S1"]["missing_segment_offset"] == 1


def test_missing_overlay(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "x")],
                                        [{"source_segment_id": "A", "global_start_sec": 0.0}])])
    _write_annotations(ann, [])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert 0 not in real_gt["S1"]
    assert audit["S1"]["missing_overlay"] == 1


def test_missing_time_excluded(paths):
    man, ann = paths
    row = _ann("S1", "A", 0, 1.0, None)
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "x")],
                                        [{"source_segment_id": "A", "global_start_sec": 0.0}])])
    _write_annotations(ann, [row])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert 0 not in real_gt["S1"]
    assert audit["S1"]["missing_time"] == 1


def test_held_vowel_status_accepted(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "x")],
                                        [{"source_segment_id": "A", "global_start_sec": 10.0}])])
    _write_annotations(ann, [_ann("S1", "A", 0, 1.0, 2.0, status=HELD)])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert real_gt["S1"][0]["start_sec"] == 11.0
    assert real_gt["S1"][0]["status"] == HELD
    assert all(v == 0 for v in audit["S1"].values())


def test_load_real_gt_wrapper_backward_compat(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [_unit(0, "A", 0, "x")],
                                        [{"source_segment_id": "A", "global_start_sec": 5.0}])])
    _write_annotations(ann, [_ann("S1", "A", 0, 1.0, 2.0)])
    real_gt, audit = load_real_gt_with_audit(ann, man)
    assert load_real_gt(ann, man) == real_gt


def test_uniform_fallback_refused(paths):
    man, ann = paths
    _write_manifest(man, [_manifest_row("S1", [], [])])
    _write_annotations(ann, [])
    with pytest.raises(ValueError, match="uniform fallback is forbidden"):
        load_real_gt(ann, man, allow_uniform=True)


def test_runner_writes_outputs(paths, tmp_path):
    man, ann = paths
    _write_manifest(man, [
        _manifest_row("S1", [_unit(0, "A", 0, "x"), _unit(1, "B", 0, "y")],
                      [{"source_segment_id": "A", "global_start_sec": 100.0},
                       {"source_segment_id": "B", "global_start_sec": 200.0}]),
        _manifest_row("S2", [_unit(0, "A", 0, "z")],
                      [{"source_segment_id": "A", "global_start_sec": 0.0}]),
    ])
    _write_annotations(ann, [
        _ann("S1", "A", 0, 5.0, 8.0),
        _ann("S1", "B", 0, 1.0, 2.5, char="y"),
        _ann("S2", "A", 0, 1.0, 2.0, status=REVIEW),
    ])
    out_root = tmp_path / "out"
    outputs = write_real_gt_outputs(ann, man, out_root)

    audit_doc = json.loads((out_root / "REAL_GT_PROJECTION_AUDIT.json").read_text(encoding="utf-8"))
    assert audit_doc["summary"]["total_canonical_units"] == 3
    assert audit_doc["summary"]["accepted_gt_units"] == 2
    assert audit_doc["summary"]["unlabeled_total"] == 1
    assert audit_doc["summary"]["unlabeled_by_reason"]["review_status"] == 1
    assert audit_doc["per_song"]["S1"]["accepted"] == 2
    assert audit_doc["per_song"]["S2"]["unlabeled"] == 1

    inv = [json.loads(l) for l in (out_root / "REAL_GT_PROJECTION_INVENTORY.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    assert len(inv) == 2
    assert inv[0]["song_id"] == "S1"
    assert inv[0]["accepted_units"][0]["end_sec"] == 108.0
    assert inv[1]["song_id"] == "S2"
    assert inv[1]["accepted_units"] == []

    sha = json.loads((out_root / "REAL_GT_PROJECTION_SHA256.json").read_text(encoding="utf-8"))
    assert "inputs" in sha and "outputs" in sha
    for p in (outputs["audit"], outputs["inventory"]):
        assert sha["outputs"][str(p)] == __import__("hashlib").sha256(
            p.read_bytes()).hexdigest()
