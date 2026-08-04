# -*- coding: utf-8 -*-
"""review12 C3/A1：long-timeline formal manifest builder 单测（真实 M4 数据装配 + 契约）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"))

import pytest

sys.path.insert(0, str(ROOT / "src"))


def _write_wav(path, rate=16000, sec=1.0):
    import numpy as np
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    x = (np.sin(2 * np.pi * 440 * np.arange(int(sec * rate)) / rate) * 3000).astype(np.float32)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(np.clip(x.astype(np.int32), -32768, 32767).astype("<i2").tobytes())


def _make_m4_manifest(tmp_path, n_segments=40, seg_sec=5.0):
    """构造一首歌 40 段 × 5s = 200s 的 m4singer_meta_v1 风格 manifest。"""
    audio_root = tmp_path / "audio"
    rows = []
    for i in range(n_segments):
        rel = f"Soprano-1#测试歌/{i:04d}.wav"
        _write_wav(audio_root / "Soprano-1#测试歌" / f"{i:04d}.wav", sec=seg_sec)
        rows.append({
            "item_id": f"Soprano-1#测试歌#{i:04d}", "song_id": "测试歌", "singer_id": "Soprano-1",
            "audio_relpath": rel, "duration_sec": seg_sec, "language": "zh",
            "lyrics_normalized": "春风吹绿江南岸" * 2, "lyrics_raw": "春风吹绿江南岸" * 2,
            "split": "validation", "status": "ok", "mapping_status": "ok",
        })
    mf = tmp_path / "m4_manifest.jsonl"
    mf.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    return mf, audio_root


def test_builder_produces_validated_requests(tmp_path):
    """review12 C3：builder 产出的每行都必须通过 AlignmentRequest.validate()，
    guard 全部 trainable（role/canonical lineage 完整），且窗严格 60s。"""
    from lyricalign.research_v7.requests import AlignmentRequest
    from lyricalign.research_v7.evaluation_guard import require_trainable

    mf, audio_root = _make_m4_manifest(tmp_path)
    out = tmp_path / "fm"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_long_timeline_manifest.py"),
                        "--m4-manifest", str(mf), "--out-root", str(out),
                        "--audio-root", str(audio_root), "--min-duration", "180",
                        "--windows-per-song", "2", "--limit", "2"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    assert reqs, "no requests"
    # 时间线 >=180s
    tl = json.loads((out / "LONG_TIMELINE_MANIFEST.jsonl").read_text().splitlines()[0])
    assert tl["duration_sec"] >= 180.0, tl["duration_sec"]
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
            metadata={"evaluation_role": rrow["evaluation_role"]})
        req.validate()  # 任何行不过 validate 即失败
        assert abs((req.audio_end_sec - req.audio_start_sec) - 60.0) < 1e-6, "window must be fixed 60s"
        # missing 变体：canonical_ids 必须与 text_units 等长（缺失单位不得残留）
        assert len(req.canonical_ids) == len(req.text_units)
        # condition 语义：baseline/missing 各自标注（不再继承 baseline）
        assert rrow["condition"] == rrow["mutation_type"]
    # row_sha 复验：必须等于 LONG_TIMELINE_MANIFEST.jsonl 实际行（默认 json.dumps 分隔符）的 sha256
    import hashlib
    row_shas = {}
    for line in (out / "LONG_TIMELINE_MANIFEST.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row_shas[row["song_id"]] = hashlib.sha256(
            json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    for rrow in reqs:
        song = rrow["pair_id"].rsplit(":", 1)[0]  # pair_id = f"{song_id}:w{wi}"
        assert rrow["canonical_timeline_row_sha"] == row_shas[song], rrow["request_id"]
    tr = require_trainable([{"item_id": x["item_id"], "request_id": x["request_id"],
                             "evaluation_role": x["evaluation_role"],
                             "text_window_aligned": x["text_window_aligned"]} for x in reqs])
    assert tr["trainable_count"] == len(reqs), "all long-timeline requests must be trainable"
    assert tr["rejected_count"] == 0
    # FREEZE 记录全部文件 SHA
    fr = json.loads((out / "FREEZE.json").read_text())
    for name in ("LONG_TIMELINE_MANIFEST.jsonl", "WINDOW_PLAN.jsonl", "REQUESTS.jsonl"):
        assert fr["files"][name]
    # round06：决策记录——canonical_timeline_file_sha 语义 note 必须存在且非空
    # （M4 = 源 m4 manifest sha；不改 identity）
    assert fr.get("canonical_timeline_file_sha_note")


def test_builder_missing_keeps_canonical_consistency(tmp_path):
    """review12 C3：missing 变体截断 text 后 canonical_ids/mapping/range/slot 必须同步。"""
    mf, audio_root = _make_m4_manifest(tmp_path)
    out = tmp_path / "fm2"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_long_timeline_manifest.py"),
                        "--m4-manifest", str(mf), "--out-root", str(out),
                        "--audio-root", str(audio_root), "--min-duration", "180",
                        "--windows-per-song", "1", "--limit", "1"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    miss = [x for x in reqs if x["mutation_type"] == "missing"]
    base = [x for x in reqs if x["mutation_type"] == "baseline"]
    assert miss and base
    assert all(x["condition"] == "missing" for x in miss)
    assert all(x["condition"] == "baseline" for x in base)
    m0 = miss[0]
    # 截断后 canonical 同步
    assert len(m0["canonical_ids"]) == len(m0["text_units"])
    assert m0["canonical_text_end"] == m0["canonical_ids"][-1] + 1
    assert set(int(k) for k in m0["canonical_to_local"]) == set(m0["canonical_ids"])
    # slot 索引在新 local 空间内
    assert all(0 <= i < len(m0["text_units"]) for i in m0["timestamp_slot_indices"])


def test_builder_refuses_short_song(tmp_path):
    """review12 A1：无 ≥min_duration 歌曲时返回非零并给出原因。"""
    mf, audio_root = _make_m4_manifest(tmp_path, n_segments=5, seg_sec=5.0)  # 25s 不够
    out = tmp_path / "fm3"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/build_long_timeline_manifest.py"),
                        "--m4-manifest", str(mf), "--out-root", str(out),
                        "--audio-root", str(audio_root), "--min-duration", "180",
                        "--windows-per-song", "1", "--limit", "1"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 1
    assert "no song >= min_duration" in r.stdout
