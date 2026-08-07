from __future__ import annotations
from typing import Any
import numpy as np

def compress_long_silence_retained(audio, profile, *, sample_rate=16000, min_original_silence_sec=5.0, retained_total_sec=3.0, retained_distribution="centered", boundary_guard_sec=0.5):
    """仅压缩 original 时长 >= min_original_silence_sec 的静音；每段保留总长 retained_total_sec。
    retained_distribution='centered'：保留段居中于原静音区间。
    前导/尾随静音：单侧保留 boundary_guard_sec（仍记录在 mapping）。
    """
    from lyricalign.demo.window_planning import detect_silence_intervals
    samples = np.asarray(audio)
    duration_sec = float(len(samples) / sample_rate)
    intervals = detect_silence_intervals(profile, duration_sec=duration_sec, min_silence_sec=0.8, strong_silence_sec=1.5)
    removed = []   # 每段: {start_sec, end_sec, keep_start_sec, keep_end_sec, removed_start_sec, removed_end_sec}
    for row in intervals:
        s, e = float(row["start_sec"]), float(row["end_sec"])
        if e - s + 1e-9 < min_original_silence_sec:
            continue
        keep_len = min(retained_total_sec, e - s)
        # 居中保留；前导/尾随（s<=0 或 e>=duration）用单侧 guard
        if s <= 1e-9 or e >= duration_sec - 1e-9:
            keep_start = s if s <= 1e-9 else e - boundary_guard_sec
            keep_end = keep_start + keep_len if s <= 1e-9 else e
        else:
            half = keep_len / 2.0
            keep_start, keep_end = (s + e) / 2.0 - half, (s + e) / 2.0 + half
        keep_start = max(s, keep_start); keep_end = min(e, keep_end)
        removed.append({"start_sec": s, "end_sec": e, "keep_start_sec": keep_start, "keep_end_sec": keep_end,
                        "removed_start_sec": s, "removed_end_sec": keep_start})
        # 注意每段实际删除两个子区间 [s,keep_start] 与 [keep_end,e]
    # 构造 compressed 与 kept_segments（original<->compressed 双向映射段）
    kept_segments, pieces, compressed_cursor = [], [], 0.0
    cursor = 0.0
    for r in removed:
        if r["start_sec"] > cursor + 1e-9:
            pieces.append(samples[int(round(cursor*sample_rate)):int(round(r["start_sec"]*sample_rate))])
            kept_segments.append({"compressed_start_sec": compressed_cursor, "compressed_end_sec": compressed_cursor + (r["start_sec"]-cursor), "original_start_sec": cursor, "original_end_sec": r["start_sec"]})
            compressed_cursor += r["start_sec"] - cursor
        # 保留段
        klen = r["keep_end_sec"] - r["keep_start_sec"]
        pieces.append(samples[int(round(r["keep_start_sec"]*sample_rate)):int(round(r["keep_end_sec"]*sample_rate))])
        kept_segments.append({"compressed_start_sec": compressed_cursor, "compressed_end_sec": compressed_cursor + klen, "original_start_sec": r["keep_start_sec"], "original_end_sec": r["keep_end_sec"]})
        compressed_cursor += klen
        cursor = r["end_sec"]
    if cursor < duration_sec - 1e-9:
        pieces.append(samples[int(round(cursor*sample_rate)):])
        kept_segments.append({"compressed_start_sec": compressed_cursor, "compressed_end_sec": compressed_cursor + (duration_sec-cursor), "original_start_sec": cursor, "original_end_sec": duration_sec})
        compressed_cursor += duration_sec - cursor
    compressed = np.concatenate(pieces) if pieces else samples[:0].copy()
    mapping = {"schema_version": "silence_compression_retained_v1", "original_duration_sec": duration_sec,
               "compressed_duration_sec": float(len(compressed)/sample_rate), "removed_intervals": removed,
               "kept_segments": kept_segments,
               "parameters": {"min_original_silence_sec": min_original_silence_sec, "retained_total_sec": retained_total_sec,
                              "retained_distribution": retained_distribution, "boundary_guard_sec": boundary_guard_sec, "sample_rate": sample_rate}}
    return compressed, mapping

def _clamp_frac(v):
    return max(0.0, min(1.0, v))

def map_original_to_compressed(mapping, t_orig):
    """original -> compressed 分段线性映射。

    边界点归属采用右优先（落在删除区间右侧的 keep 段 start）；压缩拼接点是
    多对一的（删除区间两侧折叠到同一 compressed 点），故仅对 keep 段内部与
    起点保证双向往返。
    """
    best = None
    for seg in mapping["kept_segments"]:
        if seg["original_start_sec"] - 1e-9 <= t_orig <= seg["original_end_sec"] + 1e-9:
            best = seg
    if best is None:
        return float(mapping["compressed_duration_sec"])
    frac = _clamp_frac((t_orig - best["original_start_sec"]) / max(best["original_end_sec"] - best["original_start_sec"], 1e-12))
    return best["compressed_start_sec"] + frac * (best["compressed_end_sec"] - best["compressed_start_sec"])

def map_compressed_to_original(mapping, t_comp):
    """compressed -> original 分段线性映射；右优先保证 keep 段 start 往返一致。"""
    best = None
    for seg in mapping["kept_segments"]:
        if seg["compressed_start_sec"] - 1e-9 <= t_comp <= seg["compressed_end_sec"] + 1e-9:
            best = seg
    if best is None:
        return float(mapping["original_duration_sec"])
    frac = _clamp_frac((t_comp - best["compressed_start_sec"]) / max(best["compressed_end_sec"] - best["compressed_start_sec"], 1e-12))
    return best["original_start_sec"] + frac * (best["original_end_sec"] - best["original_start_sec"])
