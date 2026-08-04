# -*- coding: utf-8 -*-
"""review8-1：exporter → REQUESTS.jsonl → runner(suite) 端到端测试（adapter 已接线）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def _write_wav(path, x, rate=16000):
    import wave
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(np.clip(x.astype(np.int32), -32768, 32767).astype("<i2").tobytes())


def _make_item(tmp_path, name="song001"):
    rate = 16000
    # 前半秒静音 + 后半有唱（vocals）；accompaniment 全程噪声
    n = rate * 2
    v = np.zeros(n, dtype=np.float32); v[rate // 2:] = np.random.RandomState(0).randn(n - rate // 2).astype(np.float32) * 0.5
    c = (np.random.RandomState(1).randn(n).astype(np.float32) * 0.05)
    d = tmp_path / name; d.mkdir(parents=True, exist_ok=True)
    audio = d / "work" / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    vp = audio / "vocals.wav"; cp = audio / "accompaniment.wav"
    _write_wav(vp, v, rate); _write_wav(cp, c, rate)
    return {"item_id": name, "audio_path": str(vp)}


def _run(cmd, expected=0):
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV)
    assert r.returncode == expected, f"rc={r.returncode}\nstdout={r.stdout[-2000:]}\nstderr={r.stderr[-2000:]}"


def test_exporter_to_runner_end_to_end(tmp_path):
    it = _make_item(tmp_path)
    item_list = tmp_path / "items.jsonl"
    item_list.write_text(json.dumps(it) + "\n")
    # canonical GT timeline（原曲 0s 起两字，落在 source window [0,1)）
    canon = tmp_path / "canon.jsonl"
    canon.write_text(json.dumps({
        "item_id": it["item_id"],
        "units": [
            {"global_index": 0, "text": "乙", "start_sec": 0.10, "end_sec": 0.45},
            {"global_index": 1, "text": "女", "start_sec": 0.50, "end_sec": 0.95},
        ],
    }) + "\n")
    textm = tmp_path / "text.jsonl"
    textm.write_text(json.dumps({"item_id": it["item_id"], "text_units": ["乙", "女"], "has_gt": True, "source": "canon"}) + "\n")
    out = tmp_path / "export"
    _run([sys.executable, str(ROOT / "scripts/research_v7/export_silence_polluted_weak.py"),
          "--item-list", str(item_list), "--out-root", str(out),
          "--canonical-timeline", str(canon), "--text-manifest", str(textm),
          "--window-sec", "1.0"], expected=0)
    reqs = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    assert reqs, "exporter produced no REQUESTS"
    # adapter 接线 → lyrics_aligned + 且 local/canonical indices 原子并存、可 JSON
    for r in reqs:
        payload = json.dumps(r)  # 可序列化
        assert r["text_window_aligned"] is True, r
        assert r["evaluation_role"] == "lyrics_aligned"
        assert r["window_sec"] is not None and r["window_sec"][0] >= 0
        assert r["text_start_index"] == 0 and r["text_end_index"] == 2   # request-local
        assert r["canonical_text_start"] == 0 and r["canonical_text_end"] == 2  # canonical global
        assert {str(k): v for k, v in r["canonical_to_local"].items()} == {"0": 0, "1": 1}
        # 局部与源窗坐标不混：局部从 0 起、源窗含原曲时间
        assert r["audio_start_sec"] == 0.0 and r["audio_end_sec"] == r["duration_sec"]
    # 喂 runner(suite)--smoke：必须 0 通过（fake executor 消费 lyrics_aligned 请求）
    runout = tmp_path / "run"
    _run([sys.executable, str(ROOT / "scripts/research_v7/run_behavior_suite.py"),
          "--manifest", str(out / "REQUESTS.jsonl"), "--out-root", str(runout), "--smoke"],
         expected=0)
    rm = json.loads((runout / "RUN_MANIFEST.json").read_text())
    ri = rm["requests_identity"]
    assert ri, "no requests recorded"
    assert all(x["status"] == "ok" for x in ri), rm["failures"]
    assert all(x["evaluation_role"] == "lyrics_aligned" for x in ri)
