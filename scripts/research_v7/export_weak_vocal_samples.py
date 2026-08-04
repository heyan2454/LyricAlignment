#!/usr/bin/env python3
"""导出弱人声二档可听样本：从 v2 manifest 切窗并合成 weak-vocal+accomp。

对每个 demo item（sample_limit 控制数量）导出 3 个 wav 到 <out>/<song>/:
  - normal.wav          : vocals.wav 正常参考窗
  - weak_vocal.wav      : vocals.wav 低 RMS 窗（原样）
  - weak_accomp.wav     : 低 RMS vocal 窗 × mix_gain + accompaniment.wav 同窗 × 1.0
写入 <out>/AUDIO_EXPORT_MANIFEST.json 记录每个文件、源窗口、RMS、增益，供检查/复核。
不破坏原音频；只从既有 vocals/accompaniment wav 切窗/混合。
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np


def read_mono16(path, start_sec, end_sec):
    with wave.open(str(path), "rb") as f:
        rate = f.getframerate(); channels = f.getnchannels(); width = f.getsampwidth()
        sr = int(start_sec * rate); er = int(end_sec * rate)
        f.setpos(max(0, sr))
        frames = f.readframes(max(0, er - sr))
    if width != 2 or channels < 1:
        raise ValueError(f"unsupported {width}/{channels}: {path}")
    x = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x, rate


def rms(x):
    return float(np.sqrt(np.mean(x * x) + 1e-12)) if x.size else 0.0


def write_wav(path, x, rate):
    import struct

    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(struct.pack(f"<{len(x)}h", *np.clip(x.astype(np.int32), -32768, 32767).astype(np.int16)))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--sample-limit", type=int, default=5)
    args = p.parse_args(argv)

    rows = [json.loads(l) for l in Path(args.manifest).read_text().splitlines() if l.strip()]
    out_root = Path(args.out_root); out_root.mkdir(parents=True, exist_ok=True)
    records = []
    done = 0
    # 按 item 分组：每 item 有 normal / weak / weak-accomp
    by_item = {}
    for r in rows:
        by_item.setdefault(r["item_id"], []).append(r)
    for iid, it in by_item.items():
        if done >= args.sample_limit:
            break
        rel = {r["audio_relation"]: r for r in it}
        n = rel.get("normal_reference"); w = rel.get("low_vocal_energy_candidate"); a = rel.get("low_vocal_energy_plus_accompaniment")
        if not (n and w and a):
            continue
        try:
            vocal_path = Path(w["audio_path"])
            accomp_path = str(vocal_path).replace("vocals.wav", "accompaniment.wav")
            acomp = Path(accomp_path)
            v_n, rate = read_mono16(vocal_path, n["audio_start_sec"], n["audio_end_sec"])
            v_w, _ = read_mono16(vocal_path, w["audio_start_sec"], w["audio_end_sec"])
            mix_gain = a["provenance"].get("mix_gain", 0.25)
            if acomp.is_file():
                c_w, _ = read_mono16(acomp, a["audio_start_sec"], a["audio_end_sec"])
                minlen = min(len(v_w), len(c_w))
                mix = v_w[:minlen] * mix_gain + c_w[:minlen] * 1.0
            else:
                mix = v_w  # 无 accomp → 退化为 weak
        except Exception as e:
            records.append({"item": iid, "error": str(e)})
            continue
        song = iid.replace("/", "_")
        d = out_root / song; d.mkdir(parents=True, exist_ok=True)
        write_wav(d / "normal.wav", v_n, rate)
        write_wav(d / "weak_vocal.wav", v_w, rate)
        write_wav(d / "weak_accomp.wav", mix, rate)
        records.append({
            "item_id": iid, "audio_path_vocals": str(vocal_path), "audio_path_accomp": str(acomp),
            "normal": {"start": n["audio_start_sec"], "end": n["audio_end_sec"], "rms": round(rms(v_n), 4)},
            "weak_vocal": {"start": w["audio_start_sec"], "end": w["audio_end_sec"], "rms": round(rms(v_w), 4)},
            "weak_accomp": {"start": a["audio_start_sec"], "end": a["audio_end_sec"], "mix_gain": mix_gain, "rms": round(rms(mix), 4)},
            "files": {"normal": str(d / "normal.wav"), "weak_vocal": str(d / "weak_vocal.wav"), "weak_accomp": str(d / "weak_accomp.wav")},
        })
        done += 1
    (out_root / "AUDIO_EXPORT_MANIFEST.json").write_text(json.dumps(records, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "exported": done, "out_root": str(out_root),
                      "records": len(records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
