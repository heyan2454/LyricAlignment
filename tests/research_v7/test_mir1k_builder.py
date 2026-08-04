# -*- coding: utf-8 -*-
"""round02：MIR-1K canonical timeline + request builder 单测（弱监督标签装配 + 契约）。

覆盖：窗计划（≤60s 单窗 / >60s 两窗含 tail≥30s）、end<=start 容错、REQUESTS 全部通过
AlignmentRequest.validate()、baseline/missing 配对、missing 的 canonical 同步截断、
--no-sparse 行数公式、FREEZE 三 sha、音频路径存在性。不依赖真实模型/真实数据。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"))

import pytest

_BUILDER_PATH = ROOT / "scripts/research_v7/build_mir1k_long_manifest.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_mir1k_long_manifest", _BUILDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_wav(path, rate=16000, sec=1.0):
    import numpy as np
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    x = (np.sin(2 * np.pi * 440 * np.arange(int(sec * rate)) / rate) * 3000).astype(np.float32)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(np.clip(x.astype(np.int32), -32768, 32767).astype("<i2").tobytes())


def _make_labels(tmp_path):
    """2 首合成歌：60s 单窗 + 70s 双窗（songB 含 yifen_1 式 end<=start 容错 pair）。

    timestamp ids 铺满整首歌（字符 span = duration/n），保证每个窗都有 ≥4 个字符。
    """
    audio_root = tmp_path / "audio" / "vocal_wavs"
    specs = [
        ("songA_1", 60.0, "春风吹绿江南岸花好月圆夜", None),  # 12 字符 → 60s 单窗
        ("songB_1", 70.0, "月亮代表我的心你知多少", 5),       # 11 字符 → 70s 双窗 + 容错 pair
    ]
    rows = []
    for name, duration, lyrics, bad_pair in specs:
        _write_wav(audio_root / f"{name}.wav", sec=duration)
        n = len(lyrics)
        ids = []
        for i, ch in enumerate(lyrics):
            start_cls = int(round(duration / 0.08 * i / n))
            end_cls = int(round(duration / 0.08 * (i + 1) / n))
            if bad_pair is not None and i == bad_pair:
                end_cls = start_cls - 4  # end class < onset class → 触发容错
            ids += [start_cls, end_cls]
        rows.append({
            "item_id": name, "song_id": f"{name}.wav", "singer_id": "singerA",
            "lyrics_normalized": lyrics, "character_count": n,
            "duration_sec": duration, "audio_relpath": f"vocal_wavs/{name}.wav",
            "timestamp_class_ids": ids, "mapping_status": "ground_truth_character",
            "validation_basis": None, "split": "test",
        })
    mf = tmp_path / "mir1k_labels.jsonl"
    mf.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    return mf, tmp_path / "audio"


def _req_from_row(rrow):
    from lyricalign.research_v7.requests import AlignmentRequest
    return AlignmentRequest(
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


def _run_builder(tmp_path, *extra):
    mf, audio_root = _make_labels(tmp_path)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(_BUILDER_PATH),
                        "--labels", str(mf), "--audio-root", str(audio_root),
                        "--out-root", str(out), *extra],
                       capture_output=True, text=True, env=ENV)
    return mf, audio_root, out, r


def test_window_plan_auto_and_explicit():
    """窗计划：≤60s 单窗；>60s 两窗 [0,60)+tail≥30s；显式 N 均匀分布且丢弃 <30s 尾窗。"""
    mod = _load_builder()
    assert mod.window_plan(55.0, None) == [(0.0, 55.0)]
    assert mod.window_plan(60.0, None) == [(0.0, 60.0)]
    wp = mod.window_plan(70.0, None)
    assert wp == [(0.0, 60.0), (40.0, 70.0)]
    assert all(w1 - w0 >= 30.0 for w0, w1 in wp)
    wp2 = mod.window_plan(108.0, None)
    assert wp2 == [(0.0, 60.0), (60.0, 108.0)]
    # 显式 windows_per_song=3 于 100s 歌：等距 [0,60) [20,80) [40,100)
    assert mod.window_plan(100.0, 3) == [(0.0, 60.0), (20.0, 80.0), (40.0, 100.0)]


def test_canonical_units_tolerance_and_ids():
    """canonical 单位：id 即下标、text 逐字符、end<=start 容错为 start+0.01。"""
    mod = _load_builder()
    row = {"lyrics_normalized": "月亮", "timestamp_class_ids": [0, 4, 8, 2]}
    units = mod.build_canonical_units(row)
    assert [u["canonical_unit_id"] for u in units] == [0, 1]
    assert [u["text"] for u in units] == ["月", "亮"]
    assert units[0]["start_sec"] == 0.0 and units[0]["end_sec"] == 0.32
    assert units[1]["start_sec"] == 0.64
    assert units[1]["end_sec"] == units[1]["start_sec"] + 0.01  # 容错


def test_builder_produces_validated_requests(tmp_path):
    """3 窗（60s×1 + 70s×2）× full/sparse × baseline/missing = 12 行，全部 validate。"""
    mf, audio_root, out, r = _run_builder(tmp_path)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    assert len(reqs) == 12, len(reqs)  # 3 窗 × 2 slot 档 × 2 mutation
    for rrow in reqs:
        req = _req_from_row(rrow)
        req.validate()  # 任何行不过 validate 即失败
        assert len(req.canonical_ids) == len(req.text_units)
        assert req.metadata["evaluation_role"] == "lyrics_aligned"
        assert rrow["canonical_adapter_version"] == "mir1k_weak_labels_v1"
        assert rrow["dataset"] == "mir1k" and rrow["split"] == "test"
        assert Path(rrow["audio_path"]).is_file()  # 音频路径存在
    # 配对完整性：每 baseline 有对应 missing（同 pair_id），且 removed 单位数 = 1/4
    base = [x for x in reqs if x["mutation_type"] == "baseline"]
    miss = {x["request_id"] for x in reqs if x["mutation_type"] == "missing"}
    assert len(base) == 6
    for b in base:
        assert f"{b['request_id']}:missing" in miss, b["request_id"]
        m = next(x for x in reqs if x["request_id"] == f"{b['request_id']}:missing")
        assert m["pair_id"] == b["pair_id"]
        assert m["mutation_parameters"]["actual_removed_units"] == max(1, len(b["text_units"]) // 4)


def test_builder_missing_keeps_canonical_consistency(tmp_path):
    """missing 变体截断 text 后 canonical_ids/mapping/range/slot 必须同步（无残留缺失单位）。"""
    mf, audio_root, out, r = _run_builder(tmp_path)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    for rrow in (x for x in reqs if x["mutation_type"] == "missing"):
        assert len(rrow["canonical_ids"]) == len(rrow["text_units"])
        assert rrow["canonical_text_end"] == rrow["canonical_ids"][-1] + 1
        assert set(int(k) for k in rrow["canonical_to_local"]) == set(rrow["canonical_ids"])
        assert all(0 <= i < len(rrow["text_units"]) for i in rrow["timestamp_slot_indices"])
    # missing 的 canonical 字段在 baseline 基础上同步截断
    by_id = {x["request_id"]: x for x in reqs}
    for bid, b in by_id.items():
        if b["mutation_type"] != "baseline":
            continue
        m = by_id[f"{bid}:missing"]
        n_miss = max(1, len(b["text_units"]) // 4)
        assert m["canonical_ids"] == b["canonical_ids"][:-n_miss]
        assert m["canonical_text_end"] == b["canonical_ids"][-n_miss]  # 缺的是末尾 cids


def test_builder_no_sparse_halves_requests(tmp_path):
    """--no-sparse：每窗仅 full 档 → 3 窗 × 1 × 2 = 6 行。"""
    mf, audio_root, out, r = _run_builder(tmp_path, "--no-sparse")
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    assert len(reqs) == 6, len(reqs)
    assert {x["phase"] for x in reqs} == {"full"}


def test_builder_timeline_and_freeze(tmp_path):
    """timeline manifest schema 与 T1 一致；FREEZE 含 labels/timeline/REQUESTS 三 sha。"""
    mf, audio_root, out, r = _run_builder(tmp_path)
    assert r.returncode == 0, r.stderr
    tl = {json.loads(l)["song_id"]: json.loads(l)
          for l in (out / "MIR_TIMELINE_MANIFEST.jsonl").read_text().splitlines() if l.strip()}
    assert set(tl) == {"songA_1.wav", "songB_1.wav"}
    # 行 schema：{song_id, canonical_units:[{canonical_unit_id,text,start_sec,end_sec}]}
    for row in tl.values():
        assert set(row) == {"song_id", "canonical_units"}
        for u in row["canonical_units"]:
            assert set(u) == {"canonical_unit_id", "text", "start_sec", "end_sec"}
            assert u["end_sec"] > u["start_sec"]
    # songB 的容错 pair：end == start + 0.01
    b = tl["songB_1.wav"]["canonical_units"][5]
    assert b["end_sec"] == round(b["start_sec"] + 0.01, 4)
    # 请求的 file sha == 实际 timeline manifest sha；每歌一个 row sha
    fr = json.loads((out / "FREEZE.json").read_text())
    import hashlib
    assert fr["labels"]["sha256"] == hashlib.sha256(mf.read_bytes()).hexdigest()
    assert fr["labels"]["path"] == str(mf)
    assert fr["files"]["MIR_TIMELINE_MANIFEST.jsonl"] == \
        hashlib.sha256((out / "MIR_TIMELINE_MANIFEST.jsonl").read_bytes()).hexdigest()
    assert fr["files"]["REQUESTS.jsonl"] == \
        hashlib.sha256((out / "REQUESTS.jsonl").read_bytes()).hexdigest()
    reqs = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    assert reqs[0]["canonical_timeline_file_sha"] == fr["files"]["MIR_TIMELINE_MANIFEST.jsonl"]
    assert len({x["canonical_timeline_row_sha"] for x in reqs}) == 2  # 每歌一个行 sha


def test_builder_refuses_without_audio(tmp_path):
    """音频缺失的行不参与（弱监督标签存在但 wav 不在 → 无歌 → 非零退出）。"""
    mf, audio_root, out, r = _run_builder(tmp_path)
    # 重新指向空 audio-root：labels 指向 vocal_wavs/*.wav，但根下没有 → 0 首歌
    out2 = tmp_path / "out2"
    empty = tmp_path / "empty_audio"
    empty.mkdir(exist_ok=True)
    r2 = subprocess.run([sys.executable, str(_BUILDER_PATH),
                         "--labels", str(mf), "--audio-root", str(empty),
                         "--out-root", str(out2)],
                        capture_output=True, text=True, env=ENV)
    assert r2.returncode == 1
    assert "no labels with existing audio" in r2.stdout
