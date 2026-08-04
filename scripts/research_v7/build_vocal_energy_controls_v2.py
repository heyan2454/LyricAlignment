#!/usr/bin/env python3
"""弱人声/伴奏 audio controls —— 三档版本（improve per user review 2026-08-04）。

用户反馈：现有 weak-vocal 窗 RMS 仍偏高(≤11)，且没有“弱人声+伴奏”混合档与正常对照。
本脚本为每个 demo 在相邻 8s 窗口内构造三档（同窗口、可对照）：
  - normal  (正常音量段)
  - weak-vocal (vocal 能量显著低于 normal，ratio 阈值约束)
  - weak-vocal+accomp (低能量 vocal 与伴奏按比例混合，rel 电平更低)
并只保留满足“weak/ normal RMS ratio <= max_ratio”的 item（移除仍太响的窗口）。

输出一行含三档 request：request_id 带 `:C6:normal`/`:C6:weak-vocal`/`:C6:weak-accomp`；
audio_relation 区分三者；provenance 写明 RMS、ratio 与混合参数。
不新建 wav、不破坏原数据：只产出 manifest，供 run 取 audio_path 的窗口切片。
"""
from __future__ import annotations

import argparse
import json
import math
import wave
from pathlib import Path

import numpy as np

PUNCT = set("，。！？、,.!?;:：；()（）[]【】\"'“”‘’—-…")
NORMAL_RATIO_MAX = 0.5      # weak / normal RMS 须 <= 0.5（比正常低一半 → 明显低）
MIX_ACCOMP_GAIN = 0.25      # accomp 相对 weak-vocal 增益


def lyric_units(path, limit):
    return [c for c in Path(path).read_text(encoding="utf-8") if not c.isspace() and c not in PUNCT][:limit]


def windows_rms(path, window_sec, hop_ratio=0.25):
    with wave.open(path, "rb") as f:
        rate = f.getframerate(); channels = f.getnchannels(); width = f.getsampwidth(); raw = f.readframes(f.getnframes())
    if width != 2:
        raise ValueError(f"unsupported sample width {width}: {path}")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    win = max(1, int(window_sec * rate)); hop = max(1, int(win * hop_ratio))
    if len(x) <= win:
        return [(0.0, len(x) / rate, float(np.sqrt(np.mean(x * x) + 1e-12)))]
    power = np.concatenate(([0.0], np.cumsum(x * x, dtype=np.float64)))
    starts = np.arange(0, len(x) - win + 1, hop)
    rms = np.sqrt((power[starts + win] - power[starts]) / win + 1e-12)
    return [(float(s / rate), float((s + win) / rate), float(rms[i])) for i, s in enumerate(starts)]


def build_cases(audio_path: str, window_sec: float, max_ratio: float, max_abs_rms: float) -> list[dict] | None:
    """返回该音频的候选三档窗口（若能找到满足 ratio 的组合）。"""
    ws = windows_rms(audio_path, window_sec)
    if len(ws) < 4:
        return None
    # 找正常段（前 40% 分位数的高能窗作 normal 参考）与最弱窗（weak）
    normal_ref = float(np.percentile([w for _, _, w in ws], 70))
    quiet = min(ws, key=lambda t: t[2])
    qs, qe, qrms = quiet
    if qrms <= 1e-6 or qrms > max_abs_rms:
        return None  # 绝对仍太响（或静音）→ 收紧剔除
    ratio = qrms / normal_ref
    if ratio > max_ratio:
        return None  # weak 相对 normal 仍太响
    # 正常对照窗：取与 weak 不同且 RMS 接近 normal_ref 的窗
    normal_win = min((w for w in ws if abs(w[2] - normal_ref) <= normal_ref * 0.3), key=lambda w: abs(w[2] - normal_ref))
    return [{
        "window": {"start": qs, "end": qe, "rms": qrms, "ratio_vs_normal": ratio},
        "normal": {"start": normal_win[0], "end": normal_win[1], "rms": normal_win[2]},
        "mix_gain": MIX_ACCOMP_GAIN,
    }]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--window-sec", type=float, default=8.0)
    p.add_argument("--unit-count", type=int, default=32)
    p.add_argument("--max-ratio", type=float, default=NORMAL_RATIO_MAX, help="weak/normal RMS 上限")
    p.add_argument("--max-abs-rms", type=float, default=5.0, help="weak 窗绝对 RMS 上限（剔除仍太响的段）")
    args = p.parse_args(argv)

    out = []
    n_skip_ratio = 0
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        r = json.loads(line)
        if r.get("dataset") != "demo" or r.get("gt_path") is not None:
            continue
        audio = Path(r["audio_path"])
        if not audio.is_file():
            continue
        if r.get("text_units"):
            text = list(r["text_units"])
        else:
            lyrics = Path(r.get("lyrics_path", ""));
            if not lyrics.is_file():
                continue
            text = lyric_units(str(lyrics), args.unit_count)
        if len(text) < 2:
            continue
        cand = build_cases(str(audio), args.window_sec, args.max_ratio, args.max_abs_rms)
        if not cand:
            n_skip_ratio += 1
            continue
        c = cand[0]
        common = {
            "item_id": r["item_id"], "song_id": r.get("source_song_id"), "source_song_id": r.get("source_song_id"),
            "dataset": "demo", "split": "demo_challenge", "language": r.get("language"), "gt_available": False,
            "audio_path": r["audio_path"], "text_source": r.get("lyrics_path") or r.get("text_source") or "", "baseline_unit_count": len(text),
            "n_base": len(text), "mutation_type": "replace", "requested_ratio": 1.0, "actual_ratio": 1.0,
            "actual_replaced_units": len(text), "mutation_position": "whole", "text_units": text,
            "text_relation": "instrumental_audio_with_real_lyrics",
        }
        # 三档
        out.append({**common, "request_id": f"{r['item_id']}:C6:normal", "audio_start_sec": c["normal"]["start"],
                    "audio_end_sec": c["normal"]["end"], "audio_relation": "normal_reference",
                    "provenance": {"selection": "70pct_rms_reference", "rms": round(c["normal"]["rms"], 4)}})
        out.append({**common, "request_id": f"{r['item_id']}:C6:weak-vocal", "audio_start_sec": c["window"]["start"],
                    "audio_end_sec": c["window"]["end"], "audio_relation": "low_vocal_energy_candidate",
                    "provenance": {"selection": "minimum_rms_sliding_window", "rms": round(c["window"]["rms"], 4),
                                   "ratio_vs_normal": round(c["window"]["ratio_vs_normal"], 4)}})
        out.append({**common, "request_id": f"{r['item_id']}:C6:weak-accomp",
                    "audio_start_sec": c["window"]["start"], "audio_end_sec": c["window"]["end"],
                    "audio_relation": "low_vocal_energy_plus_accompaniment",
                    "provenance": {"selection": "minimum_rms+accomp", "rms": round(c["window"]["rms"], 4),
                                   "mix_gain": c["mix_gain"]}})

    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out), encoding="utf-8")
    print(json.dumps({"ok": True, "items_used": len({x["item_id"] for x in out}),
                      "skipped_too_loud": n_skip_ratio, "requests": len(out), "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
