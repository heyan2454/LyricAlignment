# -*- coding: utf-8 -*-
"""Detector V2 anomaly manifest builder tests（Phase1-1）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src"))

import pytest

from lyricalign.research_v7.requests import AlignmentRequest


def _make_timeline(tmp_path):
    """两首歌、每首 200s 时间线（synthetic uniform），用于 builder 契约测试。"""
    tl = tmp_path / "tl.jsonl"
    lines = []
    for song in ("s1", "s2"):
        units = []
        for i in range(200):
            units.append({"canonical_unit_id": i, "text": f"字{i % 20}",
                          "start_sec": round(i * 0.8, 4), "end_sec": round(i * 0.8 + 0.7, 4)})
        lines.append(json.dumps({"song_id": song, "canonical_units": units,
                                 "duration_sec": 160.0, "seams": []}))
    tl.write_text("\n".join(lines) + "\n")
    return tl


def test_anomaly_manifest_all_cohorts_and_validate(tmp_path):
    tl = _make_timeline(tmp_path)
    audio = tmp_path / "audio"
    audio.mkdir()
    for song in ("s1", "s2"):
        (audio / f"{song}.wav").write_bytes(b"RIFF")
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_detector_v2_anomaly_manifest.py"),
                        "--timeline-manifest", str(tl), "--audio-root", str(audio),
                        "--out-root", str(out), "--songs", "2", "--windows-per-song", "2"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out / "ANOMALY_MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    assert reqs
    import collections
    fam = dict(collections.Counter(x["family"] for x in reqs))
    for expected in ("baseline_legal", "crop_late", "crop_early", "end_early",
                     "cursor_shift", "repeated_section"):
        assert fam.get(expected, 0) > 0, fam
    # 全部 validate（canonical lineage 完整）
    for rrow in reqs:
        req = AlignmentRequest(
            request_id=rrow["request_id"], item_id=rrow["item_id"], parent_request_id=None,
            audio_source=rrow["audio_path"], audio_start_sec=rrow["audio_start_sec"],
            audio_end_sec=rrow["audio_end_sec"],
            text_source=rrow["text_source"], text_start_index=rrow["text_start_index"],
            text_end_index=rrow["text_end_index"], text_units=tuple(rrow["text_units"]),
            timestamp_slot_indices=tuple(rrow["timestamp_slot_indices"]),
            workflow_mode=rrow["workflow_mode"], mutation_type=rrow["mutation_type"],
            mutation_parameters=rrow["mutation_parameters"], model_id=rrow["model_id"],
            checkpoint_id=rrow["checkpoint_id"], input_variant=rrow["input_variant"],
            canonical_text_start=rrow["canonical_text_start"], canonical_text_end=rrow["canonical_text_end"],
            canonical_to_local={int(k): int(v) for k, v in (rrow["canonical_to_local"] or {}).items()},
            canonical_ids=list(rrow["canonical_ids"]),
            canonical_timeline_file_sha=rrow["canonical_timeline_file_sha"],
            canonical_timeline_row_sha=rrow["canonical_timeline_row_sha"],
            canonical_adapter_version=rrow["canonical_adapter_version"],
            source_window_sec=(rrow["source_window_start_sec"], rrow["source_window_end_sec"]),
            view_id=rrow.get("view_id"), hidden_schema=rrow.get("hidden_schema"),
            metadata={"evaluation_role": rrow["evaluation_role"]})
        req.validate()
    # multiview 组存在且视图 request_id 可解析
    mv = [json.loads(l) for l in (out / "MULTIVIEW_MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    assert mv and all(len(m["views"]) >= 2 for m in mv)
    # view_id 进 identity：full 与 sparse 不同
    ids = {rrow["request_id"]: rrow for rrow in reqs}
    full = ids["s1:baseline_legal:full"]
    sparse = ids["s1:baseline_legal:sparse"]
    assert full["view_id"] == "full" and sparse["view_id"] == "sparse"


def test_anomaly_manifest_audio_path_resolved(tmp_path):
    tl = _make_timeline(tmp_path)
    audio = tmp_path / "audio"
    audio.mkdir()
    for song in ("s1", "s2"):
        (audio / f"{song}.wav").write_bytes(b"RIFF")
    out = tmp_path / "out2"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_detector_v2_anomaly_manifest.py"),
                        "--timeline-manifest", str(tl), "--audio-root", str(audio),
                        "--out-root", str(out), "--songs", "2", "--windows-per-song", "1"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out / "ANOMALY_MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    assert all(Path(rrow["audio_path"]).is_file() for rrow in reqs)
    # FREEZE 含 sha
    fr = json.loads((out / "FREEZE.json").read_text())
    assert fr["n_requests"] == len(reqs) and fr["requests_sha256"]
