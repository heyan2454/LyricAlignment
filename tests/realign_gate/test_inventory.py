"""Tests for realign_gate.inventory (00_inventory stage). CPU only, no real model."""

from __future__ import annotations

import json

import pytest

from lyricalign.realign_gate.inventory import (
    build_baseline_identity,
    build_baseline_population,
    build_data_inventory,
    discover_test_demo_items,
    load_real_gt_with_audit_map,
    plan_baseline_windows,
    run_stage,
)


def _write_jsonl(path, rows) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


ANNOTATION_ROWS = [
    {"song_id": "s1", "item_id": "segA", "character_index": 0, "start_sec": 1.0, "end_sec": 2.0,
     "mapping_status": "accepted_rule_based_pinyin_validated", "normalized_character": "甲"},
    {"song_id": "s1", "item_id": "segA", "character_index": 1, "start_sec": 2.0, "end_sec": 3.0,
     "mapping_status": "review_required", "normalized_character": "乙"},
    {"song_id": "s2", "item_id": "segB", "character_index": 0, "start_sec": 0.5, "end_sec": 1.5,
     "mapping_status": "accepted_rule_based_pinyin_validated", "normalized_character": "丙"},
]

MANIFEST_A_ROWS = [{
    "song_id": "s1", "duration_sec": 90.0, "concat_audio_path": "a.wav",
    "segment_offsets": [{"source_segment_id": "segA", "global_start_sec": 10.0}],
    "canonical_units": [
        {"canonical_unit_id": 0, "start_sec": 0.0, "end_sec": 1.0,
         "source_segment_id": "segA", "source_unit_index": 0, "text": "甲"},
        {"canonical_unit_id": 1, "start_sec": 1.0, "end_sec": 2.0,
         "source_segment_id": "segA", "source_unit_index": 1, "text": "乙"},
    ],
}]

MANIFEST_B_ROWS = [{
    "song_id": "s2", "duration_sec": 120.0, "concat_audio_path": "b.wav",
    "segment_offsets": [{"source_segment_id": "segB", "global_start_sec": 5.0}],
    "canonical_units": [
        {"canonical_unit_id": 0, "start_sec": 0.0, "end_sec": 1.0,
         "source_segment_id": "segB", "source_unit_index": 0, "text": "丙"},
    ],
}]


def _write_fixtures(tmp_path):
    ann = tmp_path / "annotations.jsonl"
    _write_jsonl(ann, ANNOTATION_ROWS)
    ma = tmp_path / "manifest_a.jsonl"
    _write_jsonl(ma, MANIFEST_A_ROWS)
    mb = tmp_path / "manifest_b.jsonl"
    _write_jsonl(mb, MANIFEST_B_ROWS)
    return ann, [ma, mb]


def _write_long_manifest(path, song_id="long1", duration=200.0, n_units=40):
    _write_jsonl(path, [{
        "song_id": song_id,
        "duration_sec": duration,
        "concat_audio_path": "long.wav",
        "segment_offsets": [],
        "canonical_units": [
            {"canonical_unit_id": i, "start_sec": i * 5.0, "end_sec": i * 5.0 + 5.0, "text": f"u{i}"}
            for i in range(n_units)
        ],
    }])


def test_plan_baseline_windows():
    assert plan_baseline_windows(30.0) == []
    assert plan_baseline_windows(59.99) == []
    w = plan_baseline_windows(200.0)
    assert [(i, cs, ws, we) for i, cs, ws, we in w] == [
        (0, 0.0, 0.0, 70.0),
        (1, 60.0, 50.0, 130.0),
        (2, 120.0, 110.0, 190.0),
    ]
    assert len(plan_baseline_windows(120.0)) == 2
    assert plan_baseline_windows(119.0)[0][1:] == (0.0, 0.0, 70.0)


def test_build_baseline_population_long(tmp_path):
    manifest = tmp_path / "long_manifest.jsonl"
    _write_long_manifest(manifest)

    cfg = {"inputs": {"cohort_manifests": [str(manifest)]}}
    run_root = tmp_path / "run"
    summary = build_baseline_population(run_root, cfg)

    assert summary["population_kind"] == "production_raw_baseline"
    assert summary["n_baseline_windows"] == 3
    assert summary["warnings"] == []

    inv = run_root / "00_inventory"
    assert (inv / "BASELINE_WINDOW_INDEX.jsonl").is_file()
    assert (inv / "BASELINE_UNITS.jsonl").is_file()
    assert (inv / "BASELINE_DETECTOR_SHADOW.jsonl").is_file()
    pop = json.loads((inv / "DETECTOR_BASELINE_POPULATION.json").read_text(encoding="utf-8"))
    assert pop["population_kind"] == "production_raw_baseline"
    assert pop["n_baseline_windows"] == 3

    idx_rows = [json.loads(l) for l in (inv / "BASELINE_WINDOW_INDEX.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(idx_rows) == 3
    assert len(idx_rows) == len({(r["song_id"], r["window_id"]) for r in idx_rows})
    assert {r["window_index"] for r in idx_rows} == {0, 1, 2}
    assert all(r["song_id"] == "long1" for r in idx_rows)

    by_index = {r["window_index"]: r for r in idx_rows}
    assert by_index[0]["window_start_sec"] == 0.0
    assert by_index[0]["window_end_sec"] == 70.0
    assert by_index[2]["window_start_sec"] == 110.0
    assert by_index[2]["window_end_sec"] == 190.0
    assert by_index[2]["audio_start_sec"] == 110.0
    assert by_index[2]["audio_end_sec"] == 190.0
    assert by_index[0]["audio_path"] == "long.wav"

    assert by_index[0]["target_unit_ids"] == list(range(0, 12))
    assert by_index[0]["canonical_unit_ids"] == list(range(0, 14))
    assert by_index[0]["text_unit_start"] == 0
    assert by_index[0]["text_unit_end"] == 13
    assert by_index[1]["target_unit_ids"] == list(range(11, 24))
    assert by_index[2]["target_unit_ids"] == list(range(23, 36))

    unit_rows = [json.loads(l) for l in (inv / "BASELINE_UNITS.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    w0_units = [r for r in unit_rows if r["window_id"] == "long1:0"]
    assert len(w0_units) == 14
    assert w0_units[0]["canonical_unit_id"] == 0 and w0_units[0]["start_sec"] == 0.0
    assert all(r["song_id"] == "long1" for r in unit_rows)

    shadow_rows = [json.loads(l) for l in (inv / "BASELINE_DETECTOR_SHADOW.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(shadow_rows) == 3
    assert all(s["detector_shadow"] == {"decision": None, "unsafe_intervals": [], "units": {}} for s in shadow_rows)


def test_build_baseline_population_dedupe_timeline_id(tmp_path):
    ma = tmp_path / "m_a.jsonl"
    mb = tmp_path / "m_b.jsonl"
    _write_long_manifest(ma, song_id="dup", duration=200.0, n_units=40)
    _write_long_manifest(mb, song_id="dup", duration=200.0, n_units=40)
    rows = [json.loads(l) for l in mb.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows[0]["timeline_id"] = "tlB"
    _write_jsonl(mb, rows)

    summary = build_baseline_population(tmp_path / "run", {"inputs": {"cohort_manifests": [str(ma), str(mb)]}})
    assert summary["n_baseline_windows"] == 6
    assert summary["warnings"]

    inv = tmp_path / "run" / "00_inventory"
    idx_rows = [json.loads(l) for l in (inv / "BASELINE_WINDOW_INDEX.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(idx_rows) == len({(r["song_id"], r["window_id"]) for r in idx_rows})
    assert "dup:0#tlB" in {r["window_id"] for r in idx_rows}


def test_build_baseline_population_duplicate_without_timeline_fails(tmp_path):
    """P0 fail-fast: duplicate (song_id, window_id) without timeline_id must raise."""
    ma = tmp_path / "m_a.jsonl"
    mb = tmp_path / "m_b.jsonl"
    _write_long_manifest(ma, song_id="dup", duration=200.0, n_units=40)
    _write_long_manifest(mb, song_id="dup", duration=200.0, n_units=40)
    with pytest.raises(ValueError):
        build_baseline_population(tmp_path / "run", {"inputs": {"cohort_manifests": [str(ma), str(mb)]}})


def test_run_stage_reports_baseline_windows(tmp_path):
    ann, manifests = _write_fixtures(tmp_path)
    old_requests = tmp_path / "old_requests.jsonl"
    _write_jsonl(old_requests, [{"request_id": 0}])
    frozen_op = tmp_path / "FROZEN_OPERATING_POINTS.json"
    frozen_op.write_text("{}", encoding="utf-8")

    demo_root = tmp_path / "demo"
    (demo_root / "chinese").mkdir(parents=True)
    (demo_root / "chinese" / "y.wav").write_bytes(b"a")
    (demo_root / "chinese" / "y.txt").write_text("x", encoding="utf-8")

    run_root = tmp_path / "run"
    cfg_path = run_root / "00_meta" / "CONFIG.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "inputs": {
            "real_gt_annotations": str(ann),
            "cohort_manifests": [str(m) for m in manifests],
            "frozen_op": str(frozen_op),
            "old_run_requests": str(old_requests),
            "test_demo_roots": [str(demo_root)],
        }
    }, ensure_ascii=False), encoding="utf-8")

    summary = run_stage(run_root, cfg_path)
    assert summary["result_status"] == "ok"
    assert summary["n_baseline_windows"] == 3
    for name in ("BASELINE_WINDOW_INDEX.jsonl", "BASELINE_UNITS.jsonl",
                 "BASELINE_DETECTOR_SHADOW.jsonl", "DETECTOR_BASELINE_POPULATION.json"):
        assert (run_root / "00_inventory" / name).is_file(), name
    assert summary["outputs"]["BASELINE_WINDOW_INDEX.jsonl"].endswith("BASELINE_WINDOW_INDEX.jsonl")


def test_load_real_gt_with_audit_map_merge_and_audit(tmp_path):
    ann, manifests = _write_fixtures(tmp_path)
    real_gt, audit = load_real_gt_with_audit_map(ann, manifests)

    assert set(real_gt) == {"s1", "s2"}
    assert set(real_gt["s1"]) == {0}
    assert real_gt["s1"][0]["start_sec"] == 11.0
    assert real_gt["s1"][0]["end_sec"] == 12.0
    assert real_gt["s1"][0]["text"] == "甲"
    assert real_gt["s1"][0]["status"] == "accepted_rule_based_pinyin_validated"
    assert real_gt["s2"][0]["start_sec"] == 5.5
    assert audit["s1"]["review_status"] == 1
    assert audit["s1"]["missing_overlay"] == 0
    assert audit["s2"]["review_status"] == 0


def test_build_data_inventory(tmp_path):
    ann, manifests = _write_fixtures(tmp_path)
    old_requests = tmp_path / "old_requests.jsonl"
    _write_jsonl(old_requests, [{"request_id": i} for i in range(3)])
    frozen_op = tmp_path / "FROZEN_OPERATING_POINTS.json"
    frozen_op.write_text("{}", encoding="utf-8")

    demo_root = tmp_path / "demo"
    (demo_root / "Chinese").mkdir(parents=True)
    (demo_root / "Chinese" / "x.wav").write_bytes(b"a")
    (demo_root / "Chinese" / "x.txt").write_text("hi", encoding="utf-8")

    cfg = {
        "inputs": {
            "real_gt_annotations": str(ann),
            "cohort_manifests": [str(m) for m in manifests],
            "frozen_op": str(frozen_op),
            "old_run_requests": str(old_requests),
            "test_demo_roots": [str(demo_root)],
        }
    }
    inv = build_data_inventory(tmp_path / "run", cfg)

    assert inv["real_gt_summary"]["n_songs"] == 2
    assert inv["real_gt_summary"]["accepted_units"] == 2
    assert len(inv["cohorts"]) == 2
    assert inv["constructible_windows"]["n_songs"] == 2
    assert inv["constructible_windows"]["constructible_windows"] == 2
    assert inv["constructible_windows"]["n_canonical_units"] == 3
    assert inv["existing_evidence"]["n_requests"] == 3
    assert inv["demo_summary"]["n_items"] == 1
    assert inv["inputs"][str(ann)] and inv["inputs"][str(manifests[0])]


def test_discover_test_demo_items(tmp_path):
    root = tmp_path / "test"
    langs = ["Chinese", "English", "japanese", "unknown"]
    for i, lang in enumerate(langs):
        d = root / lang
        d.mkdir(parents=True, exist_ok=True)
        ext = [".wav", ".mp3", ".m4a", ".flac"][i % 4]
        (d / f"f{i}{ext}").write_bytes(b"a")
        (d / f"f{i}.txt").write_text("x", encoding="utf-8")
    (root / "Chinese" / "no_txt.wav").write_bytes(b"a")
    (root / "English" / "bad.bin").write_bytes(b"a")
    (root / "English" / "bad.txt").write_text("x", encoding="utf-8")

    items = discover_test_demo_items([root])
    assert len(items) == 4
    langs_found = sorted(i["lang"] for i in items)
    assert langs_found == ["chinese", "english", "japanese", "unknown"]
    assert all(i["txt"].endswith(".txt") for i in items)
    assert not any("no_txt" in i["audio"] for i in items)
    assert not any("bad.bin" in i["audio"] for i in items)


def test_build_baseline_identity_has_accept_threshold():
    bl = build_baseline_identity()
    assert "T_accept" in bl["operating_points"]
    assert "repo_head" in bl
    assert bl["repo_head"]


def test_run_stage_writes_outputs(tmp_path):
    ann, manifests = _write_fixtures(tmp_path)
    old_requests = tmp_path / "old_requests.jsonl"
    _write_jsonl(old_requests, [{"request_id": 0}])
    frozen_op = tmp_path / "FROZEN_OPERATING_POINTS.json"
    frozen_op.write_text("{}", encoding="utf-8")

    demo_root = tmp_path / "demo"
    (demo_root / "japanese").mkdir(parents=True)
    (demo_root / "japanese" / "y.m4a").write_bytes(b"a")
    (demo_root / "japanese" / "y.txt").write_text("x", encoding="utf-8")

    run_root = tmp_path / "run"
    cfg_path = run_root / "00_meta" / "CONFIG.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "inputs": {
            "real_gt_annotations": str(ann),
            "cohort_manifests": [str(m) for m in manifests],
            "frozen_op": str(frozen_op),
            "old_run_requests": str(old_requests),
            "test_demo_roots": [str(demo_root)],
        }
    }, ensure_ascii=False), encoding="utf-8")

    summary = run_stage(run_root, cfg_path)
    assert summary["result_status"] == "ok"
    assert summary["n_demo_items"] == 1

    for name in ("DATA_INVENTORY.json", "DETECTOR_BASELINE_IDENTITY.json", "TEST_DEMO_INVENTORY.json"):
        p = run_root / "00_inventory" / name
        assert p.is_file(), name
        doc = json.loads(p.read_text(encoding="utf-8"))
        for field in ("schema", "inputs", "command", "generated_at_utc", "result_status"):
            assert field in doc, (name, field)
        assert doc["result_status"] == "ok"
