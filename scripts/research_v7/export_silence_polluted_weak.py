#!/usr/bin/env python3
"""导出「静音区分离残留污染」弱人声样本（C3 操作化 v3，2026-08-04，用户定夺多档试听）。

依据真实曲目分析（静音/间奏区 vocals≈0、伴奏强）：只在 vocals 静音/间奏帧叠加
“衰减到目标弱电平的伴奏残响”，正常人声段不动。α 多档：对照(0) / 1% / 2% / 5%，
目标弱电平 = 该窗正常人声段 RMS × α（不按伴奏本身，避免爆响）。

输出 per-song：normal.wav(对照=原 vocals) 与 weak_1/weak_2/weak_5.wav；写 AUDIO_EXPORT_MANIFEST.json。
用 wave+numpy，不改原音频、不跑 Demucs。
"""
from __future__ import annotations

import argparse
import json
import struct
import wave
from pathlib import Path

import numpy as np

ALPHAS = [0.0, 0.01]  # 用户最终选 α=1%（弱残响目标=normal×1%）
LOUDNESS_SCALE = 0.5  # 响度再降为一半 => 实际弱电平 = normal×1%×0.5


def read_mono16(path, start_sec=None, end_sec=None):
    with wave.open(str(path), "rb") as f:
        rate = f.getframerate(); ch = f.getnchannels(); w = f.getsampwidth()
        if start_sec is None:
            f.setpos(0); fr = f.readframes(f.getnframes())
        else:
            f.setpos(max(0, int(start_sec * rate)))
            fr = f.readframes(max(0, int(end_sec * rate) - int(start_sec * rate)))
    if w != 2 or ch < 1:
        raise ValueError(f"unsupported {w}/{ch}: {path}")
    x = np.frombuffer(fr, dtype="<i2").astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def rms(x):
    return float(np.sqrt(np.mean(x * x) + 1e-12)) if x.size else 0.0


def write_wav(path, x, rate):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(struct.pack(f"<{len(x)}h", *np.clip(x.astype(np.int32), -32768, 32767).astype(np.int16)))


def window_pick(vocal, acc, rate, window_sec=8.0):
    """挑‘有人声 + 有静音/间奏’的窗：窗内既有 sung（vocal 高能）也有 silence（vocal 低能）。"""
    fr = int(window_sec * rate); vf = np.sqrt((vocal * vocal).mean(1) + 1e-12)  # 本行占位，改下
    return None


def build_window(v, c, rate, alphas):
    """对一窗：区分 sung 帧(vocals 干净) 与 silence/间奏帧(vocals 低能)，silence 叠加伴奏×α 到目标弱电平。"""
    fr = int(0.05 * rate); nf = len(v) // fr
    wv = v[: nf * fr].reshape(-1, fr); wc = c[: nf * fr].reshape(-1, fr)
    vr = np.sqrt((wv * wv).mean(1) + 1e-12); cr = np.sqrt((wc * wc).mean(1) + 1e-12)
    sung_idx = np.where(vr >= float(np.percentile(vr, 40)))[0]     # 上 60% = 有唱
    sil_idx = np.where(vr < float(np.percentile(vr, 20)))[0]       # 下 20% = 静音/间奏
    normal_rms = float(np.sqrt(np.mean(vr[sung_idx] ** 2) + 1e-12)) if sung_idx.size else 1.0
    leak_energy = [float(np.sqrt(np.mean(cr[i] ** 2))) for i in sil_idx] if sil_idx.size else [0.0]
    acc_sil_rms = float(np.sqrt(np.mean(np.array(leak_energy) ** 2) + 1e-12))
    outs = {}
    for a in alphas:
        target = normal_rms * a * (LOUDNESS_SCALE if a > 0 else 1.0)
        gain = (target / (acc_sil_rms + 1e-9)) if acc_sil_rms > 0 and a > 0 else 0.0
        gain = min(gain, 1.0)  # 防爆响
        out = v.copy() if isinstance(v, np.ndarray) else np.array(v)
        for i in sil_idx:
            seg = slice(int(i * fr), int((i + 1) * fr))
            out[seg] = out[seg] + wc[i] * gain
        outs[a] = out
    return outs, {"normal_rms": round(normal_rms, 3), "acc_sil_rms": round(acc_sil_rms, 3),
                  "n_sung": int(sung_idx.size), "n_sil": int(sil_idx.size),
                  "sil_frac": round(sil_idx.size / nf, 3)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--item-list", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--window-sec", type=float, default=20.0)
    args = p.parse_args(argv)

    items = [json.loads(l) for l in Path(args.item_list).read_text().splitlines() if l.strip()]
    out_root = Path(args.out_root); out_root.mkdir(parents=True, exist_ok=True)
    recs = []; done = 0
    for it in items:
        if done >= args.limit:
            break
        vp = Path(it["audio_path"]); cp = vp.with_name(vp.name.replace("vocals.wav", "accompaniment.wav"))
        if not vp.is_file() or not cp.is_file():
            continue
        v, rate = read_mono16(vp); c, _ = read_mono16(cp)
        m = min(len(v), len(c)); v, c = v[:m], c[:m]
        win = int(args.window_sec * rate)
        if len(v) < win:
            continue
        # 选一个“有唱+有静音”的 20s 窗（找静音占比适中、且含 sung 的一段）
        start = None
        fr = int(0.05 * rate); step = int(2 * rate)
        for s in range(0, len(v) - win + 1, step):
            seg = slice(s, s + win)
            vf = np.sqrt((v[seg].reshape(-1, fr) ** 2).mean(1) + 1e-12)
            sil = float((vf < float(np.percentile(vf, 20))).mean())
            if 0.1 < sil < 0.6:
                start = s; break
        if start is None:
            continue
        outs, meta = build_window(np.array(v[start:start + win]), np.array(c[start:start + win]), rate, ALPHAS)
        song = it["item_id"].replace("/", "_")
        d = out_root / song; d.mkdir(parents=True, exist_ok=True)
        labels = {0.0: "control", **{a: f"weak_{int(round(a * 100))}" for a in ALPHAS if a > 0}}
        rms_all = {}
        for a in ALPHAS:
            name = labels[a]
            write_wav(d / f"{name}.wav", outs[a], rate); rms_all[name] = rms(outs[a])
        recs.append({"item_id": it["item_id"], "window_sec": [round(start / rate, 1), round((start + win) / rate, 1)],
                     **meta, "rms": {k: round(v, 3) for k, v in rms_all.items()},
                     "files": {lab: str(d / f"{lab}.wav") for lab in labels.values()}})
        done += 1
    (out_root / "AUDIO_EXPORT_MANIFEST.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "exported": done, "alphas": ALPHAS, "out_root": str(out_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
