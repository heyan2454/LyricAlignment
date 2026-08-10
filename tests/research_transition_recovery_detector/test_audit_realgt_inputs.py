"""Tests for Stage 3 audit_realgt_inputs provenance/cache-reuse plan (CPU only)."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.research_transition_recovery_detector.audit_realgt_inputs import (
    build_cache_reuse_plan,
    build_provenance_audit,
    discover_cache_entries,
    main,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    _write_text(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def make_inputs(tmp_path: Path) -> dict:
    audio1 = tmp_path / "audio" / "S1.wav"
    audio2 = tmp_path / "audio" / "S2.wav"
    audio3 = tmp_path / "audio" / "S3.wav"
    for audio in (audio1, audio2, audio3):
        _write_text(audio, f"wav-bytes-{audio.stem}")
    audio_sha = {name: _sha(audio.read_bytes()) for name, audio in
                 (("S1", audio1), ("S2", audio2), ("S3", audio3))}

    overlay = tmp_path / "overlay.jsonl"
    _write_jsonl(overlay, [
        {"song_id": "S1", "item_id": "seg1", "character_index": 0, "mapping_status": "accepted_rule_based_pinyin_validated", "start_sec": 0.0, "end_sec": 0.5, "normalized_character": "你", "raw_character": "你"},
        {"song_id": "S2", "item_id": "seg2", "character_index": 0, "mapping_status": "accepted_rule_validated_held_vowel", "start_sec": 0.0, "end_sec": 0.6, "normalized_character": "好", "raw_character": "好"},
        {"song_id": "S3", "item_id": "seg3", "character_index": 0, "mapping_status": "review_required_manually", "start_sec": 0.0, "end_sec": 0.4, "normalized_character": "啊", "raw_character": "啊"},
    ])

    cohort = tmp_path / "COHORT_A_FORMAL.jsonl"
    _write_jsonl(cohort, [
        {"song_id": "S1", "audio": str(audio1), "split": "validation", "source_split": "validation", "overlay": str(overlay)},
        {"song_id": "S2", "audio": str(audio2), "split": "validation", "source_split": "validation", "overlay": str(overlay)},
        {"song_id": "S3", "audio": str(audio3), "split": "validation", "source_split": "validation", "overlay": str(overlay)},
    ])

    long_rows = [
        {"song_id": "S1", "canonical_units": [{"canonical_unit_id": 0, "source_segment_id": "seg1", "source_unit_index": 0, "start_sec": 0.0, "end_sec": 0.5, "text": "你"}], "segment_offsets": [{"source_segment_id": "seg1", "global_start_sec": 0.0}]},
        {"song_id": "S2", "canonical_units": [{"canonical_unit_id": 0, "source_segment_id": "seg2", "source_unit_index": 0, "start_sec": 0.0, "end_sec": 0.6, "text": "好"}], "segment_offsets": [{"source_segment_id": "seg2", "global_start_sec": 0.0}]},
        {"song_id": "S3", "canonical_units": [{"canonical_unit_id": 0, "source_segment_id": "seg3", "source_unit_index": 0, "start_sec": 0.0, "end_sec": 0.4, "text": "啊"}], "segment_offsets": [{"source_segment_id": "seg3", "global_start_sec": 0.0}]},
    ]
    long_path = tmp_path / "LONG_TIMELINE_MANIFEST.jsonl"
    _write_jsonl(long_path, long_rows)

    real_gt_audit = tmp_path / "REAL_GT_PROJECTION_AUDIT.json"
    real_gt_audit.write_text(json.dumps({
        "summary": {"total_canonical_units": 3, "accepted_gt_units": 2, "unlabeled_total": 1},
        "per_song": {
            "S1": {"total": 1, "accepted": 1, "unlabeled": 0},
            "S2": {"total": 1, "accepted": 1, "unlabeled": 0},
            "S3": {"total": 1, "accepted": 0, "unlabeled": 1},
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "audio_sha": audio_sha,
        "cohort": cohort,
        "long": long_path,
        "real_gt_audit": real_gt_audit,
        "overlay": overlay,
        "text": {"S1": "你", "S2": "好", "S3": "啊"},
    }


def _cache_entry(request_id: str, song_id: str, audio_sha: str, text: str, **overrides) -> dict:
    entry = {
        "request_id": request_id,
        "song_id": song_id,
        "model_id": "qwen-fa-r2",
        "checkpoint_sha": "ckpt-aaa",
        "revision": "main",
        "audio_sha": audio_sha,
        "request_schema": "v7_requests_v1",
        "text": text,
        "mapping": "canonical_v1",
        "code_version": "commit-abc",
        "environment_identity": "env-123",
        "prediction_sha": "pred-" + request_id,
    }
    entry.update(overrides)
    return entry


CURRENT_IDENTITY = {
    "model_id": "qwen-fa-r2",
    "checkpoint_sha": "ckpt-aaa",
    "revision": "main",
    "request_schema": "v7_requests_v1",
    "mapping": "canonical_v1",
    "code_version": "commit-abc",
    "environment_identity": "env-123",
}


def test_main_end_to_end(tmp_path: Path) -> None:
    inputs = make_inputs(tmp_path)
    cache_dir = tmp_path / "historical" / "run1"
    _write_jsonl(cache_dir / "cache_entries.jsonl", [
        _cache_entry("rq-ok", "S1", inputs["audio_sha"]["S1"], inputs["text"]["S1"]),
        _cache_entry("rq-bad", "S2", inputs["audio_sha"]["S2"], inputs["text"]["S2"],
                     model_id="other-model", checkpoint_sha="ckpt-zzz"),
        _cache_entry("rq-diag", "S3", inputs["audio_sha"]["S3"], inputs["text"]["S3"],
                     code_version="", environment_identity=""),
    ])
    identity_path = tmp_path / "checkpoint_identity.json"
    identity_path.write_text(json.dumps(CURRENT_IDENTITY), encoding="utf-8")

    out = tmp_path / "out"
    main(["--cohort-manifest", str(inputs["cohort"]),
          "--long-manifest", str(inputs["long"]),
          "--real-gt-audit", str(inputs["real_gt_audit"]),
          "--historical-cache", str(cache_dir),
          "--checkpoint-identity", str(identity_path),
          "--out", str(out)])

    audit = json.loads((out / "INPUT_PROVENANCE_AUDIT.json").read_text(encoding="utf-8"))
    assert audit["songs"] == 3
    assert audit["provenance_ok"] is True
    by_song = {r["song_id"]: r for r in audit["per_song"]}
    assert by_song["S1"]["audio"]["sha256"] == inputs["audio_sha"]["S1"]
    assert by_song["S1"]["manifest"]["canonical_units"] == 1
    assert by_song["S1"]["real_gt"]["accepted_real_gt"] == 1
    assert by_song["S3"]["real_gt"]["unlabeled"] == 1
    assert by_song["S1"]["provenance_ok"] is True

    plan = json.loads((out / "CACHE_REUSE_PLAN.json").read_text(encoding="utf-8"))
    assert plan["counts"] == {"reusable": 1, "reusable_for_diagnostic_only": 1, "not_reusable": 1}
    by_rq = {e["request_id"]: e["classification"] for e in plan["entries"]}
    assert by_rq["rq-ok"] == "reusable"
    assert by_rq["rq-bad"] == "not_reusable"
    assert by_rq["rq-diag"] == "reusable_for_diagnostic_only"
    bad_reasons = next(e["reasons"] for e in plan["entries"] if e["request_id"] == "rq-bad")
    assert any("model_id" in r for r in bad_reasons)
    diag_reasons = next(e["reasons"] for e in plan["entries"] if e["request_id"] == "rq-diag")
    assert any("code_version" in r for r in diag_reasons)

    rows = list(csv.DictReader((out / "HISTORICAL_GT_LINEAGE_SUMMARY.csv").open(encoding="utf-8")))
    assert rows == [{"artifact_path": "(no lineage csv provided)", "prediction_sha": "", "request_id": "",
                     "action": "", "action_override": "", "override_reason": "no --lineage-csv input; HISTORICAL_GT_LINEAGE.csv not merged",
                     "note": "empty summary"}]

    freeze = json.loads((out / "INPUT_PROVENANCE_FREEZE.json").read_text(encoding="utf-8"))
    assert freeze["schema"] == "input_provenance_freeze_v1"
    assert freeze["git_head"] != "unknown"
    assert "COHORT_A_FORMAL.jsonl" in freeze["inputs"]
    assert "LONG_TIMELINE_MANIFEST.jsonl" in freeze["inputs"]


def test_provenance_ok_false_on_missing_hash(tmp_path: Path) -> None:
    inputs = make_inputs(tmp_path)
    missing = tmp_path / "missing.wav"
    cohort_path = tmp_path / "COHORT_B.jsonl"
    _write_jsonl(cohort_path, [
        {"song_id": "S1", "audio": str(inputs["audio"]["S1"]) if False else str(missing),
         "split": "validation", "overlay": str(inputs["overlay"])},
    ])
    long_rows = [
        {"song_id": "S1", "canonical_units": [{"canonical_unit_id": 0, "source_segment_id": "seg1", "source_unit_index": 0, "start_sec": 0.0, "end_sec": 0.5, "text": "你"}], "segment_offsets": [{"source_segment_id": "seg1", "global_start_sec": 0.0}]},
        {"song_id": "S2", "canonical_units": [{"canonical_unit_id": 0, "source_segment_id": "seg2", "source_unit_index": 0, "start_sec": 0.0, "end_sec": 0.6, "text": "好"}], "segment_offsets": [{"source_segment_id": "seg2", "global_start_sec": 0.0}]},
    ]
    long_path = tmp_path / "LONG2.jsonl"
    _write_jsonl(long_path, long_rows)
    audit = build_provenance_audit(cohort_path, long_path, inputs["real_gt_audit"])
    assert audit["provenance_ok"] is False
    row = audit["per_song"][0]
    assert row["provenance_ok"] is False
    assert "audio_file" in row["missing"]
    assert "audio_sha256" in row["missing"]


def test_scan_error_robustness(tmp_path: Path) -> None:
    inputs = make_inputs(tmp_path)
    cache_dir = tmp_path / "historical" / "broken"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "cache_entries.jsonl").write_text("{not-json\n", encoding="utf-8")
    (cache_dir / "identity.json").write_text("[[[", encoding="utf-8")
    entries = discover_cache_entries([str(cache_dir)])
    assert entries == []
    plan = build_cache_reuse_plan([str(cache_dir)], CURRENT_IDENTITY,
                                  inputs["audio_sha"], inputs["text"])
    assert plan["counts"] == {"reusable": 0, "reusable_for_diagnostic_only": 0, "not_reusable": 0}


def test_not_reusable_on_audio_mismatch(tmp_path: Path) -> None:
    inputs = make_inputs(tmp_path)
    cache_dir = tmp_path / "historical" / "run_audio_bad"
    _write_jsonl(cache_dir / "cache_entries.jsonl", [
        _cache_entry("rq-audio", "S1", "deadbeef", inputs["text"]["S1"]),
    ])
    plan = build_cache_reuse_plan([str(cache_dir)], CURRENT_IDENTITY, inputs["audio_sha"], inputs["text"])
    by_rq = {e["request_id"]: e["classification"] for e in plan["entries"]}
    assert by_rq["rq-audio"] == "not_reusable"
