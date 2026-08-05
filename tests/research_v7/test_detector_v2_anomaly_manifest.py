# -*- coding: utf-8 -*-
"""Detector V2 anomaly manifest builder tests（Phase1-1 + review C1-C5/M3/M4/M8/M9/M10）。"""
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

BUILDER = str(ROOT / "scripts/research_v7/build_detector_v2_anomaly_manifest.py")


def _make_timeline(tmp_path):
    """两首歌、每首 160s 时间线（synthetic uniform），用于 builder 契约测试。"""
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


def _make_audio(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    for song in ("s1", "s2"):
        (audio / f"{song}.wav").write_bytes(b"RIFF")
    return audio


def _run_builder(tmp_path, *extra):
    tl = _make_timeline(tmp_path)
    audio = _make_audio(tmp_path)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, BUILDER,
                        "--timeline-manifest", str(tl), "--audio-root", str(audio),
                        "--out-root", str(out), "--songs", "2", "--windows-per-song", "3",
                        *extra],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out / "ANOMALY_MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    mv = [json.loads(l) for l in (out / "MULTIVIEW_MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    return out, reqs, mv


def test_anomaly_manifest_all_cohorts_and_validate(tmp_path):
    out, reqs, mv = _run_builder(tmp_path)
    assert reqs
    import collections
    fam = dict(collections.Counter(x["family"] for x in reqs))
    for expected in ("baseline_legal", "crop_late", "crop_early", "end_early",
                     "end_late", "cursor_shift", "repeated_section"):
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
        assert rrow["window_index"] in (0, 1, 2)
        assert rrow["baseline_request_identity"]
        assert rrow["split"] == "unassigned"
    # M4：request_id 全局唯一（含窗号/severity/view）
    ids = [rrow["request_id"] for rrow in reqs]
    assert len(set(ids)) == len(ids)
    # 视图进 identity：full/sparse/overlap 并存于同一窗
    by_id = {rrow["request_id"]: rrow for rrow in reqs}
    full = by_id["s1:0:baseline_legal:legal:full"]
    sparse = by_id["s1:0:baseline_legal:legal:sparse"]
    assert full["view_id"] == "full" and sparse["view_id"] == "sparse"
    # multiview 组存在，含 overlap 视图（≥3 视图）
    assert mv and all(len(m["views"]) >= 3 for m in mv)
    ov = by_id["s1:0:baseline_legal:legal:overlap"]
    assert ov["view_id"] == "overlap"
    assert ov["audio_start_sec"] == 0.0 and ov["audio_end_sec"] == 61.0
    # M3：multiview group pair_id 与请求行 pair_id 一致
    assert full["pair_id"] == mv[0]["pair_id"]


def test_anomaly_manifest_text_audio_separation(tmp_path):
    """C1：crop 系与 end 系只改 audio 窗，text 保持原窗；repeated 真实替换文本。"""
    out, reqs, _ = _run_builder(tmp_path)
    by_id = {rrow["request_id"]: rrow for rrow in reqs}
    base = by_id["s1:0:baseline_legal:legal:full"]
    # crop_late：text_units == baseline（歌词正确只改 crop），audio 平移
    cl = by_id["s1:0:crop_late:2:full"]
    assert cl["text_units"] == base["text_units"]
    assert cl["canonical_ids"] == base["canonical_ids"]
    assert cl["audio_start_sec"] == base["audio_start_sec"] + 2.0
    assert cl["audio_end_sec"] == base["audio_end_sec"] + 2.0
    # crop_early（第二窗）：text 原窗，audio 平移前
    ce = by_id["s1:1:crop_early:2:full"]
    assert ce["text_units"] == by_id["s1:1:baseline_legal:legal:full"]["text_units"]
    assert ce["audio_start_sec"] == by_id["s1:1:baseline_legal:legal:full"]["audio_start_sec"] - 2.0
    # end_early：text 全长，audio 提前截止
    ee = by_id["s1:0:end_early:2:full"]
    assert ee["text_units"] == base["text_units"]
    assert ee["audio_end_sec"] == base["audio_end_sec"] - 2.0
    assert ee["audio_start_sec"] == base["audio_start_sec"]
    # cursor_shift：audio 不变，text 起点偏移 2 units
    cs = by_id["s1:0:cursor_shift:2:full"]
    assert cs["audio_start_sec"] == base["audio_start_sec"]
    assert cs["audio_end_sec"] == base["audio_end_sec"]
    assert cs["text_units"] == base["text_units"][2:]
    assert cs["canonical_ids"] == base["canonical_ids"][2:]
    # C3：repeated_section 真实注入——text_units 与 baseline 不同，长度与 canonical_ids 不变
    rp = by_id["s1:0:repeated_section:repeat:full"]
    assert rp["text_units"] != base["text_units"]
    assert len(rp["text_units"]) == len(base["text_units"])
    assert rp["canonical_ids"] == base["canonical_ids"]
    assert rp["has_gt"] is False and rp["gt_ambiguity"] is True
    # 替换确实来自窗内前 1/3 文本
    n = len(base["text_units"])
    third = max(1, n // 3)
    assert rp["text_units"][-third:] == base["text_units"][:third]
    # end_late：text 原窗，audio 延长
    el = by_id["s1:0:end_late:2:full"]
    assert el["text_units"] == base["text_units"]
    assert el["audio_end_sec"] == base["audio_end_sec"] + 2.0


def test_anomaly_manifest_window_guards(tmp_path):
    """C2/M8：crop_early 首窗无退化档；crop_late/end 系 audio 边界封顶 duration。"""
    out, reqs, _ = _run_builder(tmp_path)
    by_id = {rrow["request_id"]: rrow for rrow in reqs}
    # C2：首窗（wi=0）crop_early 全部跳过（audio_w0<0 物理不可能）；其余窗 audio_start>0
    crop_early = [r for r in reqs if r["family"] == "crop_early"]
    assert crop_early and all(r["window_index"] in (1, 2) for r in crop_early)
    assert all(r["audio_start_sec"] > 0 for r in crop_early)
    # M8：crop_late audio_end <= duration（最后一窗封顶 160s，留 1ms 余量防取整越界）
    duration = 160.0
    for r in reqs:
        if r["family"] in ("crop_late", "end_late"):
            assert r["audio_end_sec"] <= duration
    assert by_id["s1:2:crop_late:8:full"]["audio_end_sec"] <= duration
    assert by_id["s1:2:crop_late:8:full"]["audio_end_sec"] >= duration - 0.002


def test_anomaly_manifest_split_file(tmp_path):
    """C5：--split-file 按歌分配 split；test 歌在 manifest 顶层标记。"""
    sf = tmp_path / "split.json"
    sf.write_text(json.dumps({"schema_version": "detector_v2_source_song_split_v1",
                              "songs": {"train": ["s1"], "test": ["s2"]}}))
    out, reqs, _ = _run_builder(tmp_path, "--split-file", str(sf))
    s1 = [r for r in reqs if r["item_id"].startswith("s1:")]
    s2 = [r for r in reqs if r["item_id"].startswith("s2:")]
    assert s1 and s2
    assert all(r["split"] == "train" for r in s1)
    assert all(r["split"] == "test" for r in s2)
    fr = json.loads((out / "FREEZE.json").read_text())
    assert fr["split_counts"] == {"train": len(s1), "test": len(s2)}
    assert fr["cli"]["split_file"] == str(sf)


def test_anomaly_manifest_no_split_warns_and_freezes(tmp_path):
    """C5/C4：无 split-file → unassigned + warning；FREEZE 记录全部 CLI 参数与档位。"""
    out, reqs, _ = _run_builder(tmp_path)
    assert all(r["split"] == "unassigned" for r in reqs)
    fr = json.loads((out / "FREEZE.json").read_text())
    for key in ("timeline_manifest", "audio_root", "songs", "windows_per_song",
                "split_file", "include_acoustic"):
        assert key in fr["cli"], key
    for key in ("crop_late_shifts_sec", "crop_early_shifts_sec", "end_early_cuts_sec",
                "end_late_shifts_sec", "cursor_shift_units"):
        assert key in fr["gears"], key
    assert fr["n_songs_processed"] == 2
    assert fr["request_ids_unique"] is True
    assert fr["requests_sha256"]
    # row_sha 口径（M9）：等于 timeline 行序列化 sha256，可逐行复验
    import hashlib
    line = (tmp_path / "tl.jsonl").read_text(encoding="utf-8").splitlines()[0]
    expect = hashlib.sha256(json.dumps(json.loads(line), ensure_ascii=False,
                                       sort_keys=True).encode("utf-8")).hexdigest()
    assert reqs[0]["canonical_timeline_row_sha"] == expect
