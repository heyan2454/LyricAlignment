"""Tests for the real frozen population -> v2 request source adapter.

Fixtures are written to tmp_path as the same-schema JSONL files the real
inventory ships (BASELINE_DETECTOR_SHADOW.jsonl / BASELINE_UNITS.jsonl /
BASELINE_WINDOW_INDEX.jsonl / DETECTOR_BASELINE_IDENTITY.json) and reloaded
from disk, matching the production pipeline read path.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "unit_realign"))

from run_unit_realign import _region_to_request

from lyricalign.unit_realign.intervention_check import validate_request
from lyricalign.unit_realign.source_adapter import (
    IDENTITY_KEYS,
    attach_audio_and_identity,
    attach_real_units,
    compute_audio_sha256,
    make_real_identity_context,
)


def _dump_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8")


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_inventory(tmp_path):
    """Write real-schema inventory JSONL fixtures; return (inv_dir, audio_dir)."""
    inv = tmp_path / "inventory"
    inv.mkdir(parents=True, exist_ok=True)
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "songA.wav").write_bytes(b"fake-audio-bytes-for-songA-0123456789")

    identity = {
        "schema": "realign_gate/detector_baseline_identity/1",
        "model_id": "Qwen3-ForcedAligner-0.6B-hf",
        "model_revision": "rev-fake-0001",
        "checkpoint_id": "r2-step-000750",
        "checkpoint_path": "/fake/checkpoints/step-000750",
        "repo_head": "f" * 40,
        "detector": {"kind": "standardized_logistic"},
    }
    (inv / "DETECTOR_BASELINE_IDENTITY.json").write_text(
        json.dumps(identity, ensure_ascii=False), encoding="utf-8")

    def span_units(base, n, state="accept", shift=0.0):
        return {str(base + i): {"start_sec": float(base + i + shift), "end_sec": float(base + i + 1 + shift),
                                "p_bad": 0.1, "state": state} for i in range(n)}

    shadow0 = {"song_id": "songA", "window_id": "songA:0", "window_index": 0,
               "detector_shadow": {"decision": "reject", "units": span_units(0, 5)}}
    shadow1 = {"song_id": "songA", "window_id": "songA:1", "window_index": 1,
               "detector_shadow": {"decision": "accept", "units": span_units(100, 3)}}
    shadowB = {"song_id": "songB", "window_id": "songB:0", "window_index": 0,
               "detector_shadow": {"decision": "reject", "units": span_units(10, 4)}}
    _dump_jsonl(inv / "BASELINE_DETECTOR_SHADOW.jsonl", [shadow0, shadow1, shadowB])

    def unit_rows(song, window_index, base, n):
        return [{"song_id": song, "window_id": f"{song}:{window_index}",
                 "canonical_unit_id": base + i, "start_sec": float(base + i),
                 "end_sec": float(base + i + 1), "text": f"u{base+i}"} for i in range(n)]

    _dump_jsonl(inv / "BASELINE_UNITS.jsonl",
                unit_rows("songA", 0, 0, 5) + unit_rows("songA", 1, 100, 3) + unit_rows("songB", 0, 10, 4))

    def window_row(song, index, audio, base, n):
        ids = list(range(base, base + n))
        return {"song_id": song, "window_id": f"{song}:{index}", "window_index": index,
                "window_start_sec": 0.0, "window_end_sec": 70.0, "text_unit_start": 0,
                "text_unit_end": n, "canonical_unit_ids": ids, "target_unit_ids": ids,
                "audio_path": audio, "audio_start_sec": 0.0, "audio_end_sec": 70.0}

    _dump_jsonl(inv / "BASELINE_WINDOW_INDEX.jsonl",
                [window_row("songA", 0, "songA.wav", 0, 5),
                 window_row("songA", 1, "songA.wav", 100, 3),
                 window_row("songB", 0, "songB_missing.wav", 10, 4)])
    return inv, audio_dir


def _units_by_window(inv):
    groups = {}
    for row in _read_jsonl(inv / "BASELINE_UNITS.jsonl"):
        window_index = int(row["window_id"].rsplit(":", 1)[1])
        groups.setdefault((row["song_id"], window_index), []).append(row)
    return groups


def _region(song_id, window_index, targets, region_id):
    return {"region_id": region_id, "song_id": song_id, "window_index": window_index,
            "seed_kind": "unsafe_region", "target_unit_ids": targets,
            "detector_state": "UNSAFE", "baseline_available": True}


def test_attach_real_units_fills_text_and_time_sorted(tmp_path):
    inv, _ = _build_inventory(tmp_path)
    region = _region("songA", 0, [2, 3], "songA:w0:unsafe:0")
    regions, audit = attach_real_units([region], _units_by_window(inv))
    assert audit["n_regions"] == 1
    units = regions[0]["units"]
    assert [u["canonical_unit_id"] for u in units] == [0, 1, 2, 3, 4]
    assert units[2]["text"] == "u2"
    assert units[2]["start_sec"] == 2.0 and units[2]["end_sec"] == 3.0
    assert audit["missing_units"] == []
    assert audit["unit_time_mismatch"] == []


def _shadow_obj(units):
    return {"decision": "reject", "units": units, "unsafe_intervals": []}


def test_attach_real_units_detector_alignment_overrides_gt_reference(tmp_path):
    inv, _ = _build_inventory(tmp_path)
    region = _region("songA", 0, [2, 3], "songA:w0:unsafe:0")
    shadow_by = {
        ("songA", 0): _shadow_obj({
            "0": {"start_sec": 0.3, "end_sec": 1.4, "p_bad": 0.5, "state": "reject"},
            "1": {"start_sec": 1.5, "end_sec": 2.6, "p_bad": 0.5, "state": "reject"},
            "2": {"start_sec": 3.1, "end_sec": 4.2, "p_bad": 0.9, "state": "reject"},
            "3": {"start_sec": 4.3, "end_sec": 5.4, "p_bad": 0.9, "state": "reject"},
            "4": {"start_sec": 5.5, "end_sec": 6.6, "p_bad": 0.1, "state": "accept"},
        }),
    }
    regions, audit = attach_real_units([region], _units_by_window(inv), shadow_by_window=shadow_by)
    units = regions[0]["units"]
    # P1-1: request-local times must be the detector (baseline) alignment, not
    # the GT reference, so baseline/fixed-slot evidence has a real error.
    assert units[2]["start_sec"] == 3.1 and units[2]["end_sec"] == 4.2
    assert units[2]["reference_start_sec"] == 2.0 and units[2]["reference_end_sec"] == 3.0
    assert len(audit["unit_time_mismatch"]) == 5
    assert audit["missing_shadow_unit"] == []
    assert audit["missing_units"] == []


def test_attach_real_units_shadow_missing_unit_falls_back_to_reference(tmp_path):
    inv, _ = _build_inventory(tmp_path)
    region = _region("songA", 0, [2, 3], "songA:w0:unsafe:0")
    shadow_by = {("songA", 0): _shadow_obj({"2": {"start_sec": 2.5, "end_sec": 3.6, "p_bad": 0.9, "state": "reject"}})}
    regions, audit = attach_real_units([region], _units_by_window(inv), shadow_by_window=shadow_by)
    units = regions[0]["units"]
    assert units[2]["start_sec"] == 2.5 and units[2]["reference_start_sec"] == 2.0
    assert units[0]["start_sec"] == 0.0 and units[0]["reference_start_sec"] == 0.0
    assert len(audit["missing_shadow_unit"]) == 4
    assert len(audit["unit_time_mismatch"]) == 1


def test_attach_real_units_invalid_shadow_interval_keeps_reference(tmp_path):
    inv, _ = _build_inventory(tmp_path)
    region = _region("songA", 0, [2, 3], "songA:w0:unsafe:0")
    # P1-2: zero-length / end<=start shadow intervals must not pollute the
    # request-local timeline; the unit falls back to the GT reference times
    # and the case is audited, keeping R-S fixed_slot_rows constructible.
    shadow_by = {
        ("songA", 0): _shadow_obj({
            "0": {"start_sec": 0.0, "end_sec": 0.0, "p_bad": 0.5, "state": "reject"},
            "1": {"start_sec": 2.0, "end_sec": 1.0, "p_bad": 0.5, "state": "reject"},
            "2": {"start_sec": 2.5, "end_sec": 3.6, "p_bad": 0.9, "state": "reject"},
            "3": {"start_sec": 3.7, "end_sec": 4.8, "p_bad": 0.9, "state": "reject"},
            "4": {"start_sec": 4.9, "end_sec": 6.0, "p_bad": 0.1, "state": "accept"},
        }),
    }
    regions, audit = attach_real_units([region], _units_by_window(inv), shadow_by_window=shadow_by)
    units = regions[0]["units"]
    assert units[0]["start_sec"] == 0.0 and units[0]["reference_start_sec"] == 0.0
    assert units[1]["start_sec"] == 1.0 and units[1]["reference_start_sec"] == 1.0
    assert units[2]["start_sec"] == 2.5 and units[2]["reference_start_sec"] == 2.0
    assert len(audit["invalid_shadow_unit"]) == 2
    assert all(x["reason"] == "end_le_start" for x in audit["invalid_shadow_unit"])
    assert len(audit["unit_time_mismatch"]) == 3


def test_end_to_end_request_ready(tmp_path):
    inv, audio_dir = _build_inventory(tmp_path)
    region = _region("songA", 0, [2, 3], "songA:w0:unsafe:0")
    regions, _ = attach_real_units([region], _units_by_window(inv))
    ctx = make_real_identity_context(inv)
    assert set(ctx.keys()) == set(IDENTITY_KEYS)
    regions, audit = attach_audio_and_identity(regions, _read_jsonl(inv / "BASELINE_WINDOW_INDEX.jsonl"),
                                               ctx, audio_dir=audio_dir)
    row = regions[0]
    assert audit["n_ready"] == 1 and audit["missing_audio"] == 0
    assert all(row["identity_context"].get(k) for k in IDENTITY_KEYS)
    request = _region_to_request(row)
    assert request.get("status") != "not_constructible"
    assert request["request_identity"] is not None
    assert validate_request(request)["status"] == "ready"


def test_missing_audio_counted(tmp_path):
    inv, audio_dir = _build_inventory(tmp_path)
    region = _region("songB", 0, [10, 11], "songB:w0:unsafe:0")
    regions, _ = attach_real_units([region], _units_by_window(inv))
    ctx = make_real_identity_context(inv)
    regions, audit = attach_audio_and_identity(regions, _read_jsonl(inv / "BASELINE_WINDOW_INDEX.jsonl"),
                                               ctx, audio_dir=audio_dir)
    assert audit["missing_audio"] == 1
    assert audit["n_ready"] == 0
    assert regions[0]["identity_context"]["audio_sha256"] is None
    request = _region_to_request(regions[0])
    assert request.get("status") == "not_constructible"
    assert "audio_sha256" in request.get("reason", "")


def test_missing_units_audited(tmp_path):
    inv, audio_dir = _build_inventory(tmp_path)
    region = _region("songB", 0, [10, 11, 99], "songB:w0:unsafe:1")
    regions, audit = attach_real_units([region], _units_by_window(inv))
    assert any(rec["missing_target_unit_ids"] == [99] for rec in audit["missing_units"])
    ctx = make_real_identity_context(inv)
    regions, audit2 = attach_audio_and_identity(regions, _read_jsonl(inv / "BASELINE_WINDOW_INDEX.jsonl"),
                                                ctx, audio_dir=audio_dir)
    assert audit2["missing_units"] == 1
    assert audit2["n_ready"] == 0
    assert audit2["missing_audio"] == 1


def test_make_real_identity_context_defaults(tmp_path):
    inv, _ = _build_inventory(tmp_path)
    ctx = make_real_identity_context(inv)
    assert set(ctx.keys()) == set(IDENTITY_KEYS)
    assert ctx["model_identity"] == "Qwen3-ForcedAligner-0.6B-hf:rev-fake-0001"
    assert ctx["checkpoint_identity"] == "r2-step-000750:/fake/checkpoints/step-000750"
    assert ctx["code_identity"] == "git:" + "f" * 40
    assert ctx["decoder_identity"] == "official"
    assert ctx["text_adapter_identity"] == "pypinyin-zh"
    assert ctx["mapping_schema"] == "unit_realign_local_v2"
    assert ctx["baseline_digest"].startswith("sha256:")
    assert ctx["audio_sha256"] is None


def test_compute_audio_sha256(tmp_path):
    audio = tmp_path / "x.wav"
    payload = b"some-audio-bytes"
    audio.write_bytes(payload)
    assert compute_audio_sha256(audio) == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert compute_audio_sha256(tmp_path / "missing.wav") is None
