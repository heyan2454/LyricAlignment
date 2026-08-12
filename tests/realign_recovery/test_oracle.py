"""E1/E2 oracle tests: catastrophic region selection, no-GT REQUESTS build,
and offline real-GT evaluation (C2).

Pure CPU. Synthetic fixtures live under /tmp/opencode/c2_fixtures/; the last
test is a real-data smoke against the cohort_b expansion handoff, skipped when
the run files are not present on this machine.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request
from lyricalign.realign_recovery.oracle import (
    build_oracle_requests,
    evaluate_oracle_runs,
    select_catastrophic_regions,
)

FIXTURES_DIR = Path("/tmp/opencode/c2_fixtures")

SONGS = {
    "songA": {
        "duration_sec": 10.0,
        "audio_path": "/fake/audio/songA.wav",
        "units": [{"canonical_unit_id": i, "start_sec": float(i),
                   "end_sec": i + 0.6, "text": chr(97 + i)} for i in range(10)],
    },
    "songB": {
        "duration_sec": 4.0,
        "audio_path": "/fake/audio/songB.wav",
        "units": [{"canonical_unit_id": i, "start_sec": i * 0.5,
                   "end_sec": i * 0.5 + 0.3, "text": f"b{i}"} for i in range(8)],
    },
    "songC": {
        "duration_sec": 2.0,
        "audio_path": "/fake/audio/songC.wav",
        "units": [{"canonical_unit_id": i, "start_sec": float(i),
                   "end_sec": i + 1.0, "text": f"c{i}"} for i in range(2)],
    },
}

LABEL_ROWS = [
    {"song_id": "songA", "canonical_unit_id": 2, "label": "unsafe",
     "gt_unavailable": False, "split": "validation", "family": "m4",
     "audit": {"reason": "synthetic_unsafe"}},
    {"song_id": "songA", "canonical_unit_id": 3, "label": "unsafe",
     "gt_unavailable": False, "split": "validation", "family": "m4"},
    {"song_id": "songA", "canonical_unit_id": 5, "label": "unsafe",
     "gt_unavailable": False, "split": "validation", "family": "m4"},
    {"song_id": "songA", "canonical_unit_id": 6, "label": "unsafe",
     "gt_unavailable": False, "split": "validation", "family": "m4"},
    {"song_id": "songA", "canonical_unit_id": 7, "label": "unsafe",
     "gt_unavailable": False, "split": "validation", "family": "m4"},
    {"song_id": "songA", "canonical_unit_id": 7, "label": "unsafe",
     "gt_unavailable": False},  # duplicate id -> dedup
    {"song_id": "songA", "canonical_unit_id": 9, "label": "safe",
     "gt_unavailable": False},
    {"song_id": "songB", "canonical_unit_id": 1, "label": "unsafe",
     "gt_unavailable": False},
    {"song_id": "songB", "canonical_unit_id": 3, "label": "unsafe",
     "gt_unavailable": True},
    {"song_id": "songB", "canonical_unit_id": 4, "label": "unsafe",
     "gt_unavailable": False},
    {"song_id": "songB", "canonical_unit_id": 6, "label": "safe",
     "gt_unavailable": False},
    {"song_id": "songC", "canonical_unit_id": 0, "label": "unsafe",
     "gt_unavailable": False},
    {"song_id": "songC", "canonical_unit_id": 1, "label": "unsafe",
     "gt_unavailable": False},
    {"song_id": "no_timeline", "canonical_unit_id": 0, "label": "unsafe",
     "gt_unavailable": False},
]

_REAL_LABELS = Path(
    "/home/hyan/Data/lyricalign/runs/"
    "research_transition_recovery_detector_20260810_realgt_expansion_handoff/"
    "stage3b_cohort_b_dev/LABELS.jsonl")
_REAL_TIMELINE = Path(
    "/home/hyan/Data/lyricalign/runs/"
    "research_transition_recovery_detector_20260810_realgt_expansion_handoff/"
    "manifest_cohort_b/LONG_TIMELINE_MANIFEST.jsonl")


@pytest.fixture(scope="module", autouse=True)
def synthetic_fixtures():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    labels_path = FIXTURES_DIR / "LABELS.jsonl"
    timeline_path = FIXTURES_DIR / "TIMELINE_MANIFEST.jsonl"
    with labels_path.open("w", encoding="utf-8") as fh:
        for r in LABEL_ROWS:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    with timeline_path.open("w", encoding="utf-8") as fh:
        for song, meta in SONGS.items():
            fh.write(json.dumps({
                "song_id": song,
                "canonical_units": meta["units"],
                "concat_audio_path": meta["audio_path"],
                "duration_sec": meta["duration_sec"],
                "source_split": "validation",
                "timeline_id": f"syn:{song}:v1",
            }, ensure_ascii=False, sort_keys=True) + "\n")
    return {"labels": labels_path, "timeline": timeline_path}


def _region_ids(regions):
    return [r.region_id for r in regions]


def test_select_regions_aggregates_consecutive_unsafe_runs(synthetic_fixtures):
    regions = select_catastrophic_regions(
        str(synthetic_fixtures["labels"]), str(synthetic_fixtures["timeline"]))
    assert _region_ids(regions) == [
        "songA:2-3", "songA:5-7", "songB:1-1", "songB:4-4", "songC:0-1"]

    r23 = regions[0]
    assert r23.song_id == "songA"
    assert r23.unit_ids == (2, 3)
    assert r23.texts == ("c", "d")
    assert r23.audio_start_sec == 2.0
    assert r23.audio_end_sec == 3.6
    assert r23.duration_sec == 10.0
    assert r23.family == "m4"
    assert r23.split == "validation"
    assert r23.audit_reasons == ("unit2", "unit3")

    r57 = regions[1]
    assert r57.unit_ids == (5, 6, 7)
    assert r57.audio_start_sec == 5.0
    assert r57.audio_end_sec == 7.6

    rc = regions[4]
    assert rc.region_id == "songC:0-1"
    assert rc.audio_start_sec == 0.0
    assert rc.audio_end_sec == 2.0


def test_select_excludes_safe_gt_unavailable_and_no_timeline(synthetic_fixtures):
    regions = select_catastrophic_regions(
        str(synthetic_fixtures["labels"]), str(synthetic_fixtures["timeline"]))
    # unit ids are per-song, not globally unique: always scope by song_id
    songA_units = {cid for r in regions if r.song_id == "songA" for cid in r.unit_ids}
    songB_units = {cid for r in regions if r.song_id == "songB" for cid in r.unit_ids}
    assert 9 not in songA_units  # safe row excluded (songA)
    assert songB_units == {1, 4}  # unit3 gt_unavailable + unit6 safe excluded (songB)
    assert all(r.song_id != "no_timeline" for r in regions)


def test_select_min_units_per_region_filter(synthetic_fixtures):
    regions = select_catastrophic_regions(
        str(synthetic_fixtures["labels"]), str(synthetic_fixtures["timeline"]),
        min_units_per_region=2)
    assert _region_ids(regions) == ["songA:2-3", "songA:5-7", "songC:0-1"]


def test_build_oracle_requests_modes_and_audio_expansion(synthetic_fixtures, tmp_path):
    regions = select_catastrophic_regions(
        str(synthetic_fixtures["labels"]), str(synthetic_fixtures["timeline"]))
    out = tmp_path / "requests.jsonl"
    rows, out_path = build_oracle_requests(
        regions, str(synthetic_fixtures["timeline"]), str(out))
    assert out_path == str(out)
    assert len(rows) == len(regions) * 4

    rids = [r["request_id"] for r in rows]
    assert len(rids) == len(set(rids))
    for r in rows:
        assert validate_no_gt_request(r) == []
        assert set(r).isdisjoint({"gt", "gt_path", "timeline_gt", "gt_timestamps"})
        assert r["workflow_mode"] == "recovery_e1_oracle"
        assert r["mutation_type"] == "oracle_repair"
        assert r["evaluation_role"] is None
        assert r["provenance"]["realign_recovery_stage"] == "E1_oracle"

    span = lambda r: (r["audio_start_sec"], r["audio_end_sec"])
    by_region_mode = {(r["provenance"]["region_id"], r["provenance"]["mode"]): r
                      for r in rows}
    assert span(by_region_mode[("songA:2-3", "O0")]) == (2.0, 3.6)
    assert span(by_region_mode[("songA:2-3", "O1")]) == (0.0, 5.6)
    assert span(by_region_mode[("songA:2-3", "O2")]) == (0.0, 8.6)
    # clip 上限为 duration 减 0.001s 安全余量（manifest 4 位小数时长 vs 实际解码
    # 长度可能有 ±几 sample 偏差，避免 O+ 扩展窗在解码音频外被 executor 拒绝）
    assert span(by_region_mode[("songA:2-3", "O3")]) == (0.0, 9.999)  # clipped to duration - margin
    assert span(by_region_mode[("songB:4-4", "O3")]) == (0.0, 3.999)  # clipped to duration - margin
    assert by_region_mode[("songA:5-7", "O1")]["provenance"]["unit_ids"] == [5, 6, 7]


def test_build_oracle_requests_audio_extra_override(synthetic_fixtures, tmp_path):
    regions = select_catastrophic_regions(
        str(synthetic_fixtures["labels"]), str(synthetic_fixtures["timeline"]))
    rows, _ = build_oracle_requests(
        regions, str(synthetic_fixtures["timeline"]),
        str(tmp_path / "requests.jsonl"), audio_extra_sec=3.0)
    for r in rows:
        if r["provenance"]["region_id"] != "songA:2-3":
            continue
        assert (r["audio_start_sec"], r["audio_end_sec"]) == (0.0, 6.6)
        assert r["mutation_parameters"]["audio_extra_sec"] == 3.0


def test_build_oracle_requests_text_extra_units(synthetic_fixtures, tmp_path):
    regions = select_catastrophic_regions(
        str(synthetic_fixtures["labels"]), str(synthetic_fixtures["timeline"]))
    rows, _ = build_oracle_requests(
        regions, str(synthetic_fixtures["timeline"]),
        str(tmp_path / "requests.jsonl"), text_extra_units=2)
    by_region = {}
    for r in rows:
        by_region.setdefault(r["provenance"]["region_id"], []).append(r)
    for r in by_region["songA:2-3"]:
        assert r["text_units"] == ["a", "b", "c", "d", "e", "f"]
        assert (r["text_start_index"], r["text_end_index"]) == (0, 6)
        assert r["provenance"]["unit_ids"] == [2, 3]
        assert r["mutation_parameters"]["text_extra_units"] == 2
    for r in by_region["songB:1-1"]:
        assert r["text_units"] == ["b0", "b1", "b2", "b3"]
    for r in by_region["songC:0-1"]:  # whole song already covered -> unchanged
        assert r["text_units"] == ["c0", "c1"]


def _write_evidence(evidence_dir: Path, request_id: str, rows: list[dict]):
    payload = {
        "attempt": {
            "request": {"request_id": request_id},
            "decoder_outputs": {"raw": {"rows": rows}},
        }
    }
    (evidence_dir / f"{request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_evaluate_oracle_runs_metrics(synthetic_fixtures, tmp_path):
    regions = select_catastrophic_regions(
        str(synthetic_fixtures["labels"]), str(synthetic_fixtures["timeline"]))
    rows, req_path = build_oracle_requests(
        regions, str(synthetic_fixtures["timeline"]), str(tmp_path / "requests.jsonl"))
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    # O0 songA:2-3 -> units [2,3], errors [0.0, 0.5] (out-of-range gci ignored)
    _write_evidence(evidence_dir, "oracle-songA:2-3-O0", [
        {"global_character_index": 0, "raw_global_start_sec": 2.0,
         "raw_global_end_sec": 2.6},
        {"global_character_index": 1, "raw_global_start_sec": 2.5,
         "raw_global_end_sec": 4.1},
        {"global_character_index": 5, "raw_global_start_sec": 0.0,
         "raw_global_end_sec": 1.0},
    ])
    # O1 songA:5-7 -> units [5,6,7], errors [0.5, 0.0, 2.0]
    _write_evidence(evidence_dir, "oracle-songA:5-7-O1", [
        {"global_character_index": 0, "raw_global_start_sec": 5.5,
         "raw_global_end_sec": 6.1},
        {"global_character_index": 1, "raw_global_start_sec": 6.0,
         "raw_global_end_sec": 6.6},
        {"global_character_index": 2, "raw_global_start_sec": 9.0,
         "raw_global_end_sec": 9.6},
    ])
    # O2 songB:1-1 -> unit [1], error exactly 1.0 -> boundary counts repaired at 1s
    _write_evidence(evidence_dir, "oracle-songB:1-1-O2", [
        {"global_character_index": 0, "raw_global_start_sec": 1.5,
         "raw_global_end_sec": 1.8},
    ])
    # O3 songB:4-4 has evidence but no real GT for unit 4 -> skipped
    _write_evidence(evidence_dir, "oracle-songB:4-4-O3", [
        {"global_character_index": 0, "raw_global_start_sec": 2.0,
         "raw_global_end_sec": 2.3},
    ])
    # Unmatched request_id -> ignored
    _write_evidence(evidence_dir, "does-not-exist", [
        {"global_character_index": 0, "raw_global_start_sec": 0.0,
         "raw_global_end_sec": 1.0},
    ])

    real_gt = {
        "songA": {
            2: {"start_sec": 2.0, "end_sec": 2.6},
            3: {"start_sec": 3.0, "end_sec": 3.6},
            5: {"start_sec": 5.0, "end_sec": 5.6},
            6: {"start_sec": 6.0, "end_sec": 6.6},
            7: {"start_sec": 7.0, "end_sec": 7.6},
        },
        "songB": {1: {"start_sec": 0.5, "end_sec": 0.8}},
    }
    summary_path = tmp_path / "summary.json"
    summary = evaluate_oracle_runs(
        req_path, evidence_dir, real_gt, str(synthetic_fixtures["timeline"]),
        str(summary_path))

    assert summary_path.exists()
    assert summary["schema_version"] == "realign_recovery_oracle_eval_v1"
    assert summary["total_units"] == 6

    pm = summary["per_mode"]
    assert pm["O0"] == {"n_units": 2, "n_repaired": {"1": 2, "2": 2, "5": 2, "10": 2}}
    assert pm["O1"] == {"n_units": 3, "n_repaired": {"1": 2, "2": 3, "5": 3, "10": 3}}
    assert pm["O2"] == {"n_units": 1, "n_repaired": {"1": 1, "2": 1, "5": 1, "10": 1}}
    assert "O3" not in pm

    ps = summary["per_song"]
    assert ps["songA"]["n_units"] == 5
    assert ps["songA"]["mae"] == pytest.approx(0.6)
    assert ps["songA"]["n_repaired"] == {"1": 4, "2": 5, "5": 5, "10": 5}
    assert ps["songB"]["n_units"] == 1
    assert ps["songB"]["mae"] == pytest.approx(1.0)
    assert ps["songB"]["n_repaired"] == {"1": 1, "2": 1, "5": 1, "10": 1}

    pr = summary["per_region"]
    assert pr["songA:2-3"]["mode"] == "O0"
    assert pr["songA:2-3"]["n_units"] == 2
    assert pr["songA:2-3"]["mae"] == pytest.approx(0.25)
    assert pr["songA:2-3"]["n_repaired"] == {"1": 2, "2": 2, "5": 2, "10": 2}
    assert pr["songA:5-7"]["mode"] == "O1"
    assert pr["songA:5-7"]["mae"] == pytest.approx(2.5 / 3)
    assert pr["songA:5-7"]["n_repaired"] == {"1": 2, "2": 3, "5": 3, "10": 3}
    assert pr["songB:1-1"]["mode"] == "O2"
    assert pr["songB:1-1"]["mae"] == pytest.approx(1.0)
    assert "songB:4-4" not in pr


@pytest.mark.skipif(
    not (_REAL_LABELS.exists() and _REAL_TIMELINE.exists()),
    reason="real cohort_b expansion handoff fixtures not present")
def test_real_data_smoke_select_and_build():
    regions = select_catastrophic_regions(str(_REAL_LABELS), str(_REAL_TIMELINE))
    assert len(regions) == 29
    rows, out = build_oracle_requests(
        regions, str(_REAL_TIMELINE), str(FIXTURES_DIR / "smoke_oracle_requests.jsonl"))
    assert len(rows) == 116
    for r in rows:
        assert validate_no_gt_request(r) == []
