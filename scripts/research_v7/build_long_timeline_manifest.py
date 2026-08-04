#!/usr/bin/env python3
"""review12 C3/A1：formal long-timeline manifest builder（真实长数据 + fixed-60s 请求）。

formal 契约（13/14）：主体 ≥180s（同歌同歌手按元数据顺序拼接，禁人工静音凑长数据）、
主模型请求 fixed 60s、baseline 按完整 request identity 配对、每窗携带 canonical lineage
（canonical_ids/canonical_to_local/canonical range/timeline SHA/source window），
role=lyrics_aligned + text_window_aligned=true——保证 guard/collect/assessor 链路不空转。

用法：
  PYTHONPATH=src python scripts/research_v7/build_long_timeline_manifest.py \
      --m4-manifest <m4singer_meta_v1/m4singer_manifest.jsonl> \
      --out-root <run>/formal_manifest \
      --min-duration 180 --windows-per-song 3 --window-sec 60 [--limit 5]

输出（均冻结 SHA 记录到 FREEZE.json）：
  LONG_TIMELINE_MANIFEST.jsonl  —— 每行：时间线拼接记录（segments/seams/canonical_units）
  WINDOW_PLAN.jsonl             —— 每行：{timeline, window [w0,w1), text_units, canonical_ids,
                                  canonical_to_local, canonical range, slot_plan, request row}
  REQUESTS.jsonl                —— 直接可喂 run_behavior_suite --real 的请求行
  纯 CPU，不启动模型。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.canonical_mapping import build_mapping  # noqa: E402
from lyricalign.research_v7.slot_planning import plan_slots  # noqa: E402
from lyricalign.research_v7.timeline import build_timeline  # noqa: E402

WINDOW_SEC = 60.0


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_jsonl(path: Path, rows) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_json(path: Path, payload) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def load_m4(path: Path, min_duration: float, max_songs: int, audio_root: Path | None = None) -> list[dict]:
    """按 song 聚合段，返回 ≥min_duration 的同歌时间线（段按 item_id 数字序）。"""
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_song: dict[str, list] = {}
    for r in rows:
        song = r.get("song_id")
        if not song:
            continue
        audio_path = Path(r.get("audio_relpath", ""))
        if audio_root is not None:
            audio_path = audio_root / audio_path
        if not audio_path.is_file():
            continue  # 音频缺失的段不参与拼接
        by_song.setdefault(song, []).append(r)
    timelines = []
    for song, segs in sorted(by_song.items()):
        if not segs:
            continue
        total = sum(float(s.get("duration_sec", 0) or 0) for s in segs)
        if total < min_duration:
            continue
        # 同歌手校验：同歌段必须同一 singer（M4Singer 约定）
        singers = {s.get("singer_id") for s in segs}
        if len(singers) > 1:
            continue
        # 按 item_id 的段序号排序（0000,0001,...），显式排序拒绝文件名乱序
        def _num(s):
            try:
                return int(str(s.get("item_id", "")).split("#")[-1])
            except ValueError:
                return -1
        segs_sorted = sorted(segs, key=_num)
        if any(_num(s) < 0 for s in segs_sorted):
            continue
        timelines.append({
            "song_id": song, "singer_id": next(iter(singers)), "segments": segs_sorted,
            "total_duration_sec": round(total, 3), "n_segments": len(segs_sorted),
            "audio_root": str(audio_root) if audio_root else "",
        })
        if len(timelines) >= max_songs:
            break
    return timelines


def _canonical_units_for_window(canonical_units, w0: float, w1: float) -> list[dict]:
    """窗 [w0,w1) 内 overlap 的 canonical 单位（与 c3 adapter 同语义：严格 overlap）。"""
    out = []
    for u in canonical_units:
        start, end = float(u["start_sec"]), float(u["end_sec"])
        if max(start, w0) < min(end, w1):
            out.append(u)
    out.sort(key=lambda u: int(u["canonical_unit_id"]))
    return out


def build_requests(tl: dict, timeline: object, *, windows_per_song: int,
                   row_sha: str, language: str = "Chinese") -> list[dict]:
    """从一条时间线生成 fixed-60s 窗请求（baseline + 缺失/替换 mutation 配对）。

    row_sha：LONG_TIMELINE_MANIFEST.jsonl 中本歌实际行的序列化 sha256
    （调用方在 main 中对该行 dict 以 json.dumps(ensure_ascii=False, sort_keys=True)
    求值，保证可从文件复验）。
    """
    units = list(timeline.canonical_units)
    n = len(units)
    duration = float(timeline.duration_sec)
    # 窗起点：early/middle/late 各 60s（窗不超时长）
    n_win = max(1, int(duration // WINDOW_SEC))
    if windows_per_song <= 1:
        starts = [0.0]
    else:
        span = max(0.0, duration - WINDOW_SEC)
        starts = [span * i / (windows_per_song - 1) for i in range(windows_per_song)]
    reqs = []
    for wi, w0 in enumerate(starts):
        w1 = min(w0 + WINDOW_SEC, duration)
        if w1 - w0 < 30.0:
            continue  # 尾窗太短不算正式请求
        in_win = _canonical_units_for_window(units, w0, w1)
        if len(in_win) < 4:
            continue  # 窗内歌词太少（可能是长间奏）→ 跳过，避免空对齐
        cids = [int(u["canonical_unit_id"]) for u in in_win]
        texts = [u["text"] for u in in_win]
        canonical_to_local = {cid: i for i, cid in enumerate(cids)}
        c0, c1 = cids[0], cids[-1] + 1
        # slot：full（默认）与非连续 strided 各一个（density 对比）
        plan_full = plan_slots(
            plan_id=f"{tl['song_id']}:w{wi}:full", canonical_unit_count=n,
            queried_canonical_ids=cids, strategy="contiguous",
            canonical_to_local=canonical_to_local, request_local_count=len(texts),
            comparison_group_id=f"{tl['song_id']}:w{wi}", phase="full")
        step = max(2, len(cids) // 6)
        plan_sparse = plan_slots(
            plan_id=f"{tl['song_id']}:w{wi}:sparse", canonical_unit_count=n,
            queried_canonical_ids=cids[::step], strategy=f"strided{step}",
            canonical_to_local=canonical_to_local, request_local_count=len(texts),
            comparison_group_id=f"{tl['song_id']}:w{wi}", phase="sparse")
        # canonical lineage（review12：guard/collect/assessor 消费）
        # canonical_timeline_row_sha 由 main 对实际写入行求值后传入（可从文件复验）
        tl_sha = tl.get("manifest_sha")
        for plan in (plan_full, plan_sparse):
            base = {
                "schema_version": "research_v7_long_slot_v1",
                "request_type": "long_timeline_60s",
                "item_id": f"{tl['song_id']}:w{wi}:{plan.phase_name}",
                "request_id": f"{tl['song_id']}:w{wi}:{plan.phase_name}",
                "parent_request_id": None,
                "audio_path": (tl.get("segs_audio") or [None])[0],
                "audio_start_sec": round(w0, 4), "audio_end_sec": round(w1, 4),
                "duration_sec": round(w1 - w0, 4), "audio_source": "m4singer_segment_concat",
                "text_source": "m4singer_meta_v1", "has_gt": True,
                "evaluation_role": "lyrics_aligned", "text_window_aligned": True,
                "text_units": texts, "text_start_index": 0, "text_end_index": len(texts),
                "timestamp_slot_indices": list(plan.local_indices),
                "workflow_mode": "long_slot_60s", "mutation_type": "baseline",
                "mutation_parameters": {"position": "whole", "requested_ratio": 0.0},
                "language": language, "dataset": "m4singer", "split": "validation",
                "model_id": "Qwen3-ForcedAligner-0.6B-hf", "checkpoint_id": "r2-step-000750",
                "input_variant": "text_mutation",
                # canonical lineage（review12：guard/collect/assessor 消费）
                "canonical_text_start": c0, "canonical_text_end": c1,
                "canonical_to_local": {str(k): v for k, v in canonical_to_local.items()},
                "canonical_ids": cids,
                "canonical_timeline_file_sha": tl_sha,
                "canonical_timeline_row_sha": row_sha,
                "canonical_adapter_version": "long_timeline_v1",
                "source_window_start_sec": round(w0, 4), "source_window_end_sec": round(w1, 4),
                "condition": "baseline", "pair_id": f"{tl['song_id']}:w{wi}",
                "slot_plan_id": plan.plan_id, "comparison_group_id": plan.comparison_group_id,
                "phase": plan.phase_name,
            }
            # missing：virtual gap（移除尾部 1/4 单位，评价 omitted-original）。
            # 契约：text_units 截断后，canonical_ids/mapping/range/slot 全部同步到保留单位
            # （缺失单位不得留在请求 canonical 字段里）。
            n_miss = max(1, len(texts) // 4)
            miss = dict(base)
            miss["request_id"] = f"{base['request_id']}:missing"
            miss["item_id"] = f"{base['item_id']}:missing"
            miss["mutation_type"] = "missing"
            miss["condition"] = "missing"
            kept = texts[:-n_miss]
            kept_ids = cids[:-n_miss]
            kept_to_local = {cid: i for i, cid in enumerate(kept_ids)}
            # missing 的 slot：用保留 canonical ids 在【新 local 映射】上的本地索引重算
            kept_slots = plan_slots(
                plan_id=f"{base['slot_plan_id']}:missing", canonical_unit_count=n,
                queried_canonical_ids=[c for c in plan.requested_canonical_ids if c in kept_to_local],
                canonical_to_local=kept_to_local, request_local_count=len(kept),
                comparison_group_id=plan.comparison_group_id, phase=plan.phase_name)
            miss["text_units"] = kept
            miss["text_end_index"] = len(kept)
            miss["canonical_ids"] = kept_ids
            miss["canonical_to_local"] = {str(k): v for k, v in kept_to_local.items()}
            miss["canonical_text_end"] = kept_ids[-1] + 1 if kept_ids else c0
            miss["timestamp_slot_indices"] = list(kept_slots.local_indices)
            miss["mutation_parameters"] = {"position": "tail", "requested_ratio": 0.25,
                                           "actual_removed_units": n_miss,
                                           "baseline_unit_count": len(texts)}
            reqs.append(miss)
            # baseline 本体
            reqs.append(base)
    return reqs


def concat_timeline_audio(segs: list[dict], output: Path, *, rate: int = 16000,
                          seam_silence_sec: float = 0.5) -> None:
    """按时间线顺序拼接段音频（16k mono int16，段间插 seam_silence_sec 静音，
    与 timeline.build_timeline 的 artificial_silence 一致），输出到 output。

    返回 None；失败抛错（调用方记录并跳过该歌）。音频是正式运行输入，
    用 sha256 记录 source 文件清单到 .sources.json（重放/审计）。
    """
    import shutil
    import struct
    import subprocess
    import wave as _wave
    import numpy as np

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg required to concat timeline audio")
    tmp = output.with_suffix(".tmp.wav")
    output.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    sil = np.zeros(int(rate * seam_silence_sec), dtype=np.float32)
    for si, s in enumerate(segs):
        src = Path(s["audio_path"])
        if not src.is_file():
            raise FileNotFoundError(f"segment audio missing: {src}")
        # 统一 16k mono s16le
        seg_out = output.with_suffix(f".seg{si}.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                        "-i", str(src), "-ar", str(rate), "-ac", "1",
                        "-c:a", "pcm_s16le", str(seg_out)], check=True)
        with _wave.open(str(seg_out), "rb") as f:
            data = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        seg_out.unlink()
        if si > 0:
            parts.append(sil)
        parts.append(data)
    out_audio = np.concatenate(parts) if parts else sil
    out_audio = np.clip(out_audio, -1.0, 1.0)
    with _wave.open(str(tmp), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(struct.pack(f"<{len(out_audio)}h",
                                  *(out_audio * 32767).astype(np.int16)))
    tmp.replace(output)
    sources = [{"path": str(Path(s["audio_path"]).resolve()), "sha256": _sha(Path(s["audio_path"]))}
               for s in segs]
    output.with_suffix(".sources.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--m4-manifest", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--audio-root", default="/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer",
                   help="audio_relpath 的根目录（音频实际位置）")
    p.add_argument("--min-duration", type=float, default=180.0)
    p.add_argument("--windows-per-song", type=int, default=3)
    p.add_argument("--limit", type=int, default=5, help="最多取几首歌曲构造时间线")
    args = p.parse_args(argv)

    m4 = Path(args.m4_manifest)
    out = Path(args.out_root); out.mkdir(parents=True, exist_ok=True)
    manifest_sha = _sha(m4)
    audio_root = Path(args.audio_root) if args.audio_root else None
    timelines = load_m4(m4, args.min_duration, args.limit, audio_root=audio_root)
    if not timelines:
        print(json.dumps({"ok": False, "reason": "no song >= min_duration",
                          "m4_manifest_sha": manifest_sha}, ensure_ascii=False))
        return 1

    tl_rows, win_rows, reqs = [], [], []
    for tl in timelines:
        # 决策记录（round06）：canonical_timeline_file_sha 语义 = 源 m4 manifest sha
        # （非 timeline 文件自身 sha，与 MIR builder 语义不同）；不改 identity，
        # 改会作废 120 req formal evidence 需重跑——见 FREEZE.canonical_timeline_file_sha_note。
        tl["manifest_sha"] = manifest_sha
        audio_root = Path(tl["audio_root"]) if tl.get("audio_root") else None
        segs = []
        for s in tl["segments"]:
            audio_path = Path(s["audio_relpath"])
            if audio_root is not None:
                audio_path = audio_root / audio_path
            segs.append({
                "item_id": s["item_id"], "song_id": s["song_id"], "singer_id": s["singer_id"],
                "text": s.get("lyrics_normalized") or s.get("lyrics_raw", ""),
                "duration_sec": float(s.get("duration_sec", 0) or 0),
                "audio_path": str(audio_path), "order": int(str(s["item_id"]).split("#")[-1]),
                "source_unit_index": 0,
            })
        try:
            timeline = build_timeline(
                timeline_id=f"m4:{tl['song_id']}:v1", source_song_id=tl["song_id"],
                dataset="m4singer", language="zh", segments=segs, order_field="order",
                artificial_silence_sec=0.5)
        except Exception as e:  # noqa
            print(json.dumps({"ok": False, "song": tl["song_id"], "error": str(e)}), ensure_ascii=False)
            return 2
        # 拼接整歌音频（16k mono，段间 0.5s 静音与 timeline seam 一致）——
        # 请求的 audio_start/end 是整歌坐标系，真实 executor 需要可解码的完整音频。
        concat_wav = out / "audio" / f"{tl['song_id']}.wav"
        try:
            concat_timeline_audio(segs, concat_wav, seam_silence_sec=0.5)
        except Exception as e:  # noqa
            print(json.dumps({"ok": False, "song": tl["song_id"], "error": f"concat failed: {e}"},
                             ensure_ascii=False))
            return 3
        tl["segs_audio"] = [str(concat_wav)] * len(segs)
        tl_row = {
            "timeline_id": timeline.timeline_id, "song_id": tl["song_id"],
            "singer_id": tl["singer_id"], "n_segments": tl["n_segments"],
            "duration_sec": round(timeline.duration_sec, 3),
            "canonical_units": [{"canonical_unit_id": u["canonical_unit_id"], "text": u["text"],
                                 "start_sec": u["start_sec"], "end_sec": u["end_sec"]}
                                for u in timeline.canonical_units],
            "seams": list(timeline.seams),
            "source_audio_paths": [s["audio_path"] for s in segs],
            "concat_audio_path": str(concat_wav),
        }
        tl_rows.append(tl_row)
        # row_sha：对【实际写入 LONG_TIMELINE_MANIFEST.jsonl 的序列化】求值
        # （与 _atomic_jsonl 的 json.dumps(r, ensure_ascii=False, sort_keys=True) 一致），
        # 保证可从文件逐行复验；texts-only hash 口径废弃。
        row_sha = _sha_bytes(
            json.dumps(tl_row, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        song_reqs = build_requests(tl, timeline, windows_per_song=args.windows_per_song,
                                   row_sha=row_sha)
        reqs.extend(song_reqs)
        for r in song_reqs:
            win_rows.append({"song_id": tl["song_id"], "request_id": r["request_id"],
                             "window": [r["audio_start_sec"], r["audio_end_sec"]],
                             "canonical_ids": r["canonical_ids"],
                             "text_units": r["text_units"],
                             "slot_plan_id": r.get("slot_plan_id")})
    _atomic_jsonl(out / "LONG_TIMELINE_MANIFEST.jsonl", tl_rows)
    _atomic_jsonl(out / "WINDOW_PLAN.jsonl", win_rows)
    _atomic_jsonl(out / "REQUESTS.jsonl", reqs)
    freeze = {
        "schema": "research_v7_long_timeline_manifest_v1",
        "m4_manifest": {"path": str(m4), "sha256": manifest_sha},
        # 决策记录（round06）：M4 builder 的 canonical_timeline_file_sha 为源 m4
        # manifest sha（与 MIR builder 的 timeline 文件 sha 语义不同）；此为决策记录，
        # 不改 identity（改会作废 formal evidence 需重跑）。
        "canonical_timeline_file_sha_note": (
            "M4 builder 的 canonical_timeline_file_sha 为源 m4 manifest sha"
            "（与 MIR builder 的 timeline 文件 sha 语义不同）；此为决策记录，"
            "不改 identity（改会作废 formal evidence 需重跑）。"
        ),
        "built_at_utc": "2026-08-05T00:00:00Z",
        "min_duration_sec": args.min_duration, "windows_per_song": args.windows_per_song,
        "songs": len(tl_rows), "requests": len(reqs),
        "files": {
            "LONG_TIMELINE_MANIFEST.jsonl": _sha(out / "LONG_TIMELINE_MANIFEST.jsonl"),
            "WINDOW_PLAN.jsonl": _sha(out / "WINDOW_PLAN.jsonl"),
            "REQUESTS.jsonl": _sha(out / "REQUESTS.jsonl"),
        },
    }
    _atomic_json(out / "FREEZE.json", freeze)
    print(json.dumps({"ok": True, "songs": len(tl_rows), "requests": len(reqs),
                      "out_root": str(out), "freeze": freeze["files"]["REQUESTS.jsonl"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
