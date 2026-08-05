# -*- coding: utf-8 -*-
"""Detector V2 MIR anomaly manifest builder tests（C2 收尾：18 §13 / 21 §1 契约）。

纯内存 fixture：2 歌 × ~75s × 120 canonical_units + dummy wav + --duration-map，
subprocess 调 build_detector_v2_mir_manifest.py main()，断言：
cohort 全集、request_id 唯一、逐行 AlignmentRequest.validate（canonical lineage 完整）、
matched baseline_request_identity、multiview ≥2 views、audio 边界 ≤ 时长、
split=mir1k、弱标签（gt_validation_basis=null）。
"""
from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.research_v7.requests import AlignmentRequest

BUILDER = str(ROOT / "scripts/research_v7/build_detector_v2_mir_manifest.py")
DURATION = 75.0
WINDOW_SEC = 60.0


def _make_timeline(tmp_path):
    """2 歌、各 120 字、~75s 时间线（MIR_TIMELINE_MANIFEST 行 schema）。"""
    tl = tmp_path / "tl.jsonl"
    lines = []
    for song in ("s1", "s2"):
        units = []
        for i in range(120):
            units.append({"canonical_unit_id": i, "text": f"字{i % 20}",
                          "start_sec": round(i * 0.6, 4), "end_sec": round(i * 0.6 + 0.5, 4)})
        lines.append(json.dumps({"song_id": song, "canonical_units": units}))
    tl.write_text("\n".join(lines) + "\n")
    return tl


def _make_audio(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    for song in ("s1", "s2"):
        (audio / f"{song}.wav").write_bytes(b"RIFF")
    return audio


def _run_builder(tmp_path):
    tl = _make_timeline(tmp_path)
    audio = _make_audio(tmp_path)
    dm = tmp_path / "duration.json"
    dm.write_text(json.dumps({"s1": DURATION, "s2": DURATION}))
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, BUILDER,
                        "--timeline-manifest", str(tl), "--audio-root", str(audio),
                        "--out-root", str(out), "--songs", "2",
                        "--windows-per-song", "3", "--duration-map", str(dm)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in
            (out / "MIR_ANOMALY_MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    mv = [json.loads(l) for l in
          (out / "MULTIVIEW_MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    freeze = json.loads((out / "FREEZE.json").read_text())
    return reqs, mv, freeze


def _to_request(row):
    return AlignmentRequest(
        request_id=row["request_id"], item_id=row["item_id"],
        parent_request_id=row.get("parent_request_id"),
        audio_source=row["audio_path"], audio_start_sec=row["audio_start_sec"],
        audio_end_sec=row["audio_end_sec"], text_source=row["text_source"],
        text_start_index=row["text_start_index"], text_end_index=row["text_end_index"],
        text_units=tuple(row["text_units"]),
        timestamp_slot_indices=tuple(row["timestamp_slot_indices"]),
        workflow_mode=row["workflow_mode"], mutation_type=row["mutation_type"],
        mutation_parameters=row["mutation_parameters"], model_id=row["model_id"],
        checkpoint_id=row["checkpoint_id"], input_variant=row["input_variant"],
        canonical_text_start=row["canonical_text_start"],
        canonical_text_end=row["canonical_text_end"],
        canonical_to_local={int(k): int(v) for k, v in (row["canonical_to_local"] or {}).items()},
        canonical_ids=list(row["canonical_ids"]),
        canonical_timeline_file_sha=row["canonical_timeline_file_sha"],
        canonical_timeline_row_sha=row["canonical_timeline_row_sha"],
        canonical_adapter_version=row["canonical_adapter_version"],
        source_window_sec=(row["source_window_start_sec"], row["source_window_end_sec"]),
        view_id=row.get("view_id"), hidden_schema=row.get("hidden_schema"),
        metadata={"evaluation_role": row["evaluation_role"]})


def test_mir_manifest_cohorts_validate_identity(tmp_path):
    """全 cohort、request_id 唯一、逐行 validate（canonical lineage 完整）。"""
    reqs, mv, freeze = _run_builder(tmp_path)
    assert reqs and mv
    fam = dict(collections.Counter(x["family"] for x in reqs))
    for expected in ("baseline_legal", "crop_late", "crop_early", "end_early",
                     "cursor_shift", "repeated_section"):
        assert fam.get(expected, 0) > 0, fam
    ids = [r["request_id"] for r in reqs]
    assert len(set(ids)) == len(ids)
    for row in reqs:
        req = _to_request(row)
        req.validate(total_units=120, duration_sec=DURATION)
        assert row["baseline_request_identity"], row["request_id"]
        assert row["split"] == "mir1k"
        assert row["gt_validation_basis"] is None
        assert row["weak_label_source"] == "mir1k_qwen_fa_labels_v1"
        assert row["audio_start_sec"] >= 0.0 and row["audio_end_sec"] <= DURATION
    assert freeze["validate_ok"] is True
    assert freeze["request_ids_unique"] is True
    assert freeze["n_songs_processed"] == 2
    assert freeze["split_counts"] == {"mir1k": len(reqs)}


def test_mir_manifest_multiview_and_weak_labels(tmp_path):
    """multiview ≥2 views；弱标签轴：repeated_section 无 GT，其余 has_gt。"""
    reqs, mv, _ = _run_builder(tmp_path)
    assert all(len(m["views"]) >= 2 for m in mv)
    by_id = {r["request_id"]: r for r in reqs}
    full = by_id["s1:0:baseline_legal:legal:full"]
    sparse = by_id["s1:0:baseline_legal:legal:sparse"]
    assert full["view_id"] == "full" and sparse["view_id"] == "sparse"
    assert full["baseline_request_identity"] == by_id["s1:0:crop_late:2:full"]["baseline_request_identity"]
    rp = [r for r in reqs if r["family"] == "repeated_section"][0]
    assert rp["has_gt"] is False and rp["gt_ambiguity"] is True
    assert rp["text_units"] != full["text_units"]
    assert len(rp["text_units"]) == len(full["text_units"])
    for row in reqs:
        if row["family"] != "repeated_section":
            assert row["has_gt"] is True and row["gt_ambiguity"] is False
