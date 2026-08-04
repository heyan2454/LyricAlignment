#!/usr/bin/env python3
"""导出「静音区分离残留污染」弱人声样本（C3 操作化 v3，2026-08-04，用户定夺多档试听）。

依据真实曲目分析（静音/间奏区 vocals≈0、伴奏强）：只在 vocals 静音/间奏帧叠加
“衰减到目标弱电平的伴奏残响”，正常人声段不动。最终定档 α=2%（对照 control + weak_2），
目标弱电平 = 该窗正常人声段 RMS × α（不按伴奏本身，避免爆响）。
静音判定用：绝对 vocal RMS 上限 + 相对有唱段比例 + 最短连续静音；记录 frame audit 与 clip。

输出 per-song：control.wav(对照=原 vocals) 与 weak_2.wav；写 AUDIO_EXPORT_MANIFEST.json（含 sample_rate）。
用 wave+numpy，不改原音频、不跑 Demucs；vocals 与 accompaniment 采样率不一致则拒绝。
"""
from __future__ import annotations

import argparse
import json
import struct
import wave
from pathlib import Path

import numpy as np

ALPHAS = [0.0, 0.02]  # 用户最终定档 α=2%（weak_silence_samples_2pct 为正式档）
LOUDNESS_SCALE = 1.0  # 1.0 = 不做响度缩放（导出 2%）
TEXT_UNITS: list = []  # 可选：同窗歌词逐字（REQUESTS 写 text_units）；缺省=纯声学 probe


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


def _atomic_jsonl(path, rows):
    import json as _j
    import os as _os
    import tempfile as _tf

    from pathlib import Path as _P

    p = _P(path); p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = _tf.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with _os.fdopen(fd, "w") as f:
            for r in rows:
                f.write(_j.dumps(r, ensure_ascii=False) + "\n")
            f.flush(); _os.fsync(f.fileno())
        _os.replace(tmp, p)  # 原子替换
    except Exception:
        if _os.path.exists(tmp):
            _os.unlink(tmp)
        raise


def _atomic_json(path, payload):
    import json as _j
    import os as _os
    import tempfile as _tf

    from pathlib import Path as _P

    p = _P(path); p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = _tf.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with _os.fdopen(fd, "w") as f:
            _j.dump(payload, f, ensure_ascii=False, indent=1)
            f.flush(); _os.fsync(f.fileno())
        _os.replace(tmp, p)
    except Exception:
        if _os.path.exists(tmp):
            _os.unlink(tmp)
        raise


def write_wav(path, x, rate):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(struct.pack(f"<{len(x)}h", *np.clip(x.astype(np.int32), -32768, 32767).astype(np.int16)))


SIL_ABS_MAX = 400.0      # 绝对 vocal RMS 上限（低于才算静音区，防把 loud 人声机械判静）
SIL_REL_TO_SUNG = 0.35   # silence 需 < 有唱段中位 vocal RMS × 0.35
MIN_CONTIGUOUS_SIL_FRAMES = 6  # 最短连续静音帧(0.3s)，阻断单帧噪点


def detect_silence_frames(vr, sung_median, rate, frame_sec):
    """P0（C3-review）：静音帧 = 绝对上限 + 相对 sung + 连续长度。

    返回 (sil_mask, audit)。不满足 min 连续长度的孤立静音帧视同正常帧（避免污染人声区）。
    """
    abs_ok = vr < SIL_ABS_MAX
    rel_ok = vr < sung_median * SIL_REL_TO_SUNG
    cand = abs_ok & rel_ok
    # 用连续段过滤：孤立 < MIN_CONTIGUOUS 的候选帧重置为非静音
    sil = cand.copy()
    nf = len(cand)
    i = 0
    while i < nf:
        if cand[i]:
            j = i
            while j < nf and cand[j]:
                j += 1
            if (j - i) < MIN_CONTIGUOUS_SIL_FRAMES:
                sil[i:j] = False  # 太短 → 非静音
            i = j
        else:
            i += 1
    return sil, {"cand_abs": int(abs_ok.sum()), "cand_rel": int(rel_ok.sum()),
                 "sil_final": int(sil.sum()), "min_contig_frame": MIN_CONTIGUOUS_SIL_FRAMES}


def build_window(v, c, rate, alphas):
    """对一窗：区分 sung 帧(vocals 干净) 与 silence/间奏帧(vocals 低能)，silence 叠加伴奏×α 到目标弱电平。

    P0（C3）：silence 判定用绝对上限+相对 sung 比例+最短连续静音；frame audit 记录污染帧的 residual/clip。
    """
    fr = int(0.05 * rate); nf = len(v) // fr
    wv = v[: nf * fr].reshape(-1, fr); wc = c[: nf * fr].reshape(-1, fr)
    vr = np.sqrt((wv * wv).mean(1) + 1e-12); cr = np.sqrt((wc * wc).mean(1) + 1e-12)
    sung_idx = np.where(vr >= float(np.percentile(vr, 40)))[0]
    sung_median = float(np.median(vr[sung_idx])) if sung_idx.size else 1.0
    sil, aud = detect_silence_frames(vr, sung_median, rate, 0.05)
    normal_rms = float(np.sqrt(np.mean(vr[sung_idx] ** 2) + 1e-12)) if sung_idx.size else 1.0
    sil_frames = {"v": vr[sil], "c": cr[sil]} if sil.any() else None
    outs = {}
    clip = 0
    for a in alphas:
        out = np.array(v, copy=True)
        if sil.any():
            acc_sil_rms = float(np.sqrt(np.mean(cr[sil] ** 2) + 1e-12))
            target = normal_rms * a * (LOUDNESS_SCALE if a > 0 else 1.0)
            gain = min(target / (acc_sil_rms + 1e-9), 1.0) if a > 0 and acc_sil_rms > 0 else 0.0
            for i in np.where(sil)[0]:
                seg = slice(int(i * fr), int((i + 1) * fr))
                out[seg] = out[seg] + wc[i] * gain
            clip = int((np.abs(out) > 32000).sum())  # 16-bit 峰值裁剪计数
        outs[a] = out
    meta = {"normal_rms": round(normal_rms, 3), "n_sung": int(sung_idx.size),
            "n_sil": int(sil.sum()), "sil_frac": round(float(sil.mean()), 3),
            "clip_count": clip, "silence_audit": aud}
    return outs, meta


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--item-list", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--window-sec", type=float, default=20.0)
    p.add_argument("--text-units", nargs="*", default=[], help="同窗歌词逐字（供 REQUESTS 写 text_units；缺省=纯声学 probe）")
    args = p.parse_args(argv)
    global TEXT_UNITS
    TEXT_UNITS = list(args.text_units)

    items = [json.loads(l) for l in Path(args.item_list).read_text().splitlines() if l.strip()]
    out_root = Path(args.out_root); out_root.mkdir(parents=True, exist_ok=True)
    recs = []; _reqs = []; done = 0
    for it in items:
        if done >= args.limit:
            break
        vp = Path(it["audio_path"]); cp = vp.with_name(vp.name.replace("vocals.wav", "accompaniment.wav"))
        if not vp.is_file() or not cp.is_file():
            continue
        v, rate = read_mono16(vp); c, c_rate = read_mono16(cp)
        if c_rate != rate:
            recs.append({"item_id": it["item_id"], "skipped": "sample_rate_mismatch",
                         "vocal_rate": rate, "acc_rate": c_rate})
            continue
        m = min(len(v), len(c)); v, c = v[:m], c[:m]
        win = int(args.window_sec * rate)
        if len(v) < win:
            continue
        # P0（C3-review）：选窗用与 build_window 相同的 silence 判定（绝对/相对/连续），非机械 20%。
        start = None
        fr = int(0.05 * rate); step = int(2 * rate)
        for s in range(0, len(v) - win + 1, step):
            seg = slice(s, s + win)
            wv = v[seg][: len(v[seg]) // fr * fr].reshape(-1, fr)
            vr = np.sqrt((wv * wv).mean(1) + 1e-12)
            sung_median = float(np.median(vr[np.where(vr >= np.percentile(vr, 40))]))
            sil, _ = detect_silence_frames(vr, sung_median, rate, 0.05)
            frac = float(sil.mean())
            if 0.1 < frac < 0.6:
                start = s; break
        if start is None:
            recs.append({"item_id": it["item_id"], "skipped": "no_adequate_silence_window"})
            continue
        outs, meta = build_window(np.array(v[start:start + win]), np.array(c[start:start + win]), rate, ALPHAS)
        if meta["n_sil"] == 0:
            recs.append({"item_id": it["item_id"], "skipped": "no_silence_frames_after_audit",
                         "silence_audit": meta["silence_audit"]})
            continue  # 无合格静音 → 不导出（避免 control==weak）
        song = it["item_id"].replace("/", "_")
        d = out_root / song; d.mkdir(parents=True, exist_ok=True)
        labels = {0.0: "control", **{a: f"weak_{int(round(a * 100))}" for a in ALPHAS if a > 0}}
        rms_all = {}
        for a in ALPHAS:
            name = labels[a]
            write_wav(d / f"{name}.wav", outs[a], rate); rms_all[name] = rms(outs[a])
        # P0（C3-review）：实际计算 source SHA，不使用输入里的可选字段
        import hashlib
        import json as _json
        import os as _os
        import tempfile as _tf

        window_s = round(start / rate, 1)
        pair_id = f"{it['item_id']}:w{window_s}"
        conditions = {lab: ("control" if lab == "control" else "weak_vocal_residual") for lab in labels.values()}
        vocal_sha = hashlib.sha256(vp.read_bytes()).hexdigest()
        acc_sha = hashlib.sha256(cp.read_bytes()).hexdigest()
        # P0(review3-2)：identity 必须包含全部构造内容：acc sha、每个导出 wav 的 content sha、
        # alpha、silence-mask 摘要(meta.silence_audit 的确定性编码)、rate、code/transform version。
        code_ver = "c3-exporter-v3"
        wav_sha = {}
        for a in ALPHAS:
            name = labels[a]
            p = d / f"{name}.wav"
            wav_sha[name] = hashlib.sha256(p.read_bytes()).hexdigest()  # 写文件后算 content sha
        sil_desc = _json.dumps(meta.get("silence_audit", {}), sort_keys=True) if meta.get("silence_audit") else ""
        target_ratio = next((a for a in ALPHAS if a > 0), None)

        def _reqid(cond, cond_sha):
            return "sha256:" + hashlib.sha256(
                f"{pair_id}|{cond}|{rate}|{vocal_sha}|{acc_sha}|{cond_sha}|{target_ratio}|{sil_desc}|{code_ver}".encode()
            ).hexdigest()

        recs.append({"item_id": it["item_id"], "window_sec": [window_s, round((start + win) / rate, 1)],
                     "pair_id": pair_id, "sample_rate": rate,
                     "vocal_sha256": vocal_sha, "acc_sha256": acc_sha, "wav_sha256": wav_sha, **meta,
                     "rms": {k: round(v, 3) for k, v in rms_all.items()},
                     "conditions": conditions,
                     "files": {lab: str(d / f"{lab}.wav") for lab in labels.values()}, "done": True})
        for lab in labels.values():
            cond = conditions[lab]
            is_control = (lab == "control")
            wav_path = str(d / f"{lab}.wav")
            wav_dur = round(win / rate, 4)  # 生成 WAV 实际时长
            req = {
                "schema_version": "research_v7_long_slot_v1",
                "request_type": "c3_weak_vocal_calibration",
                "condition": cond, "pair_id": pair_id, "item_id": it["item_id"],
                # review4-2：显式 audio 范围(0..wav 时长) + audio_path，供 runner/executor 正确消费
                "audio_path": wav_path,
                "audio_start_sec": 0.0, "audio_end_sec": wav_dur, "duration_sec": wav_dur,
                "audio_source": "generated_c3_wav",
                "window_sec": [window_s, round((start + win) / rate, 1)],
                "audio_path_vocals": str(vp), "audio_path_accompaniment": str(cp),
                "vocal_sha256": vocal_sha, "acc_sha256": acc_sha,
                "sample_rate": rate, "code_version": code_ver,
                "request_identity": _reqid(cond, wav_sha[lab]),
                "files": [wav_path], "files_sha256": [wav_sha[lab]],
                # review4-1：歌词 units/range（缺省空=纯声学 probe；有则用同窗歌词）
                "text_units": TEXT_UNITS, "text_start_index": 0, "text_end_index": len(TEXT_UNITS),
                # review4-5：control 显式 ratio 0/baseline，不伪装成污染样本
                "mutation": ("control" if is_control else "silence_residual"),
                "target_ratio": (0.0 if is_control else target_ratio),
            }
            _reqs.append(req)
        done += 1
    # P0(review3-2)：REQUESTS 原子写（临时文件+replace）并按 identity 去重；AUDIO_EXPORT_MANIFEST 同理。
    seen = set(); uniq = []
    for r in _reqs:
        if r["request_identity"] not in seen:
            seen.add(r["request_identity"]); uniq.append(r)
    _atomic_jsonl(out_root / "REQUESTS.jsonl", uniq)
    _atomic_json(out_root / "AUDIO_EXPORT_MANIFEST.json", recs)
    print(json.dumps({"ok": True, "exported": done, "alphas": ALPHAS, "out_root": str(out_root),
                      "n_requests": len(uniq)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
