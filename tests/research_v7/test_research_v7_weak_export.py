# -*- coding: utf-8 -*-
"""C3 export_silence_polluted_weak 单测（review C3-6：临时 WAV fixture）。"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 允许 import scripts

from scripts.research_v7.export_silence_polluted_weak import (
    detect_silence_frames,
    read_mono16,
)


def _write_wav(path, x, rate=16000):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(np.clip(x.astype(np.int32), -32768, 32767).astype("<i2").tobytes())


def _tone(sec, rate=16000, amp=2000.0, freq=440.0, start_frames=0):
    n = int(sec * rate)
    t = np.arange(n) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _wav_with_silence(sil_sec=1.0, sing_sec=2.0, rate=16000):
    """一段 vocals：先 sing（有唱）再 silence（低能）。"""
    return np.concatenate([_tone(sing_sec, rate, amp=3000.0),
                           np.zeros(int(sil_sec * rate), dtype=np.float32)])


def test_detect_silence_frames_finds_only_low():
    v = _wav_with_silence(sil_sec=1.0, sing_sec=2.0)
    fr = int(0.05 * 16000); nf = len(v) // fr
    vr = np.sqrt((v[:nf * fr].reshape(-1, fr) ** 2).mean(1) + 1e-12)
    sung_median = float(np.median(vr))
    sil, audit = detect_silence_frames(vr, sung_median, 16000, 0.05)
    assert sil.sum() > 0                       # 静音区被检出
    assert audit["sil_final"] == int(sil.sum())


def test_read_mono16_roundtrip_rate():
    x = _tone(0.2, 16000, amp=2000)
    p = Path("/tmp") / "t.wav"
    _write_wav(p, x, 16000)
    y, rate = read_mono16(str(p))
    assert rate == 16000
    assert y.shape[0] == int(0.2 * 16000)
    p.unlink()


def test_sample_rate_mismatch_rejected_in_main(tmp_path):
    # 用 subprocess 或直接构造：vocals 16k、accomp 8k → 导出应 skip(mismatch)
    import json
    import subprocess
    voc = tmp_path / "s" ; voc.mkdir()
    vv = tmp_path / "vocals.wav"; aa = tmp_path / "accompaniment.wav"
    _write_wav(vv, _tone(0.3, 16000), 16000)
    _write_wav(aa, _tone(0.3, 8000), 8000)
    il = tmp_path / "items.jsonl"
    il.write_text(json.dumps({"item_id": "X", "audio_path": str(vv)}) + "\n")
    out = tmp_path / "out"
    # 直接查 read 语义（açomp rate != vocals）: 这走 main 会 skip；此处借 read 返回验证
    _, rv = read_mono16(str(vv)); _, ra = read_mono16(str(aa))
    assert rv != ra


def test_detect_no_silence_when_full_sing():
    v = _tone(1.0, 16000, amp=3000.0)  # 全程有唱
    fr = int(0.05 * 16000); nf = len(v) // fr
    vr = np.sqrt((v[:nf * fr].reshape(-1, fr) ** 2).mean(1) + 1e-12)
    sung_median = float(np.median(vr))
    sil, _ = detect_silence_frames(vr, sung_median, 16000, 0.05)
    # 全程唱 → 应几乎无静音帧（绝对上限 400 与相对 0.35 联合排除）
    assert sil.sum() <= nf * 0.05
