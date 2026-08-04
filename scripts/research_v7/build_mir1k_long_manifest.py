#!/usr/bin/env python3
"""round02：MIR-1K canonical timeline + request builder（跨域 assessor 前置）。

背景：13 §10.3 跨域要求 M4 ↔ MIR-1K 分开汇报。MIR-1K 弱监督标签
（qwen_fa_timestamp_labels_v1，mapping_status=ground_truth_character，
validation_basis=null —— **非人工 GT**）逐字符给出 [onset,offset] class（×0.08s），
可直接构造 canonical timeline（**不用** timeline.build_timeline 的 synthetic uniform 轴）。

输入 labels 行（每行一首歌）：
  {item_id, song_id, singer_id, lyrics_normalized（len==character_count）, duration_sec,
   audio_relpath="vocal_wavs/*.wav", timestamp_class_ids（长度恰 2×character_count）,
   mapping_status, validation_basis, split}

输出（均冻结 SHA 记录到 FREEZE.json）：
  MIR_TIMELINE_MANIFEST.jsonl —— 每行 {song_id, canonical_units:[{canonical_unit_id, text,
                                  start_sec, end_sec}]}（schema 与 T1 GT 评价一致）
  REQUESTS.jsonl              —— 每窗 baseline + tail-missing(1/4) 配对、full+sparse slot
                                 （--no-sparse 可关）、完整 canonical lineage
                                 （canonical_ids/canonical_to_local/canonical range/
                                 timeline file sha/per-song row sha/adapter 版本/source window）、
                                 dataset=mir1k、split=test、role=lyrics_aligned
  FREEZE.json                 —— labels sha256 + timeline sha256 + REQUESTS sha256 + 源路径

窗规则（--windows-per-song 缺省按 duration 自动）：
  ≤60s  单窗 [0, min(60, duration))
  >60s  两窗 [0,60) + tail（长度 ≥30s：起点 = min(60, duration-30)，终点 = duration）
  显式 --windows-per-song N：M4 同款均匀分布（窗不超时长，<30s 的尾窗跳过）。
  纯 CPU，不启动模型。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.slot_planning import plan_slots  # noqa: E402

WINDOW_SEC = 60.0
MIN_WINDOW_SEC = 30.0
MIN_UNITS_PER_WINDOW = 4
TIMESTAMP_CLASS_SEC = 0.08
ADAPTER_VERSION = "mir1k_weak_labels_v1"
MODEL_ID = "Qwen3-ForcedAligner-0.6B-hf"
CHECKPOINT_ID = "r2-step-000750"


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


def load_labels(path: Path, audio_root: Path | None, max_songs: int) -> list[dict]:
    """读取弱监督标签行；音频缺失的行不参与（与 M4 builder 同策略）。"""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        song_id = r.get("song_id") or r.get("item_id")
        if not song_id:
            continue
        audio_path = Path(r.get("audio_relpath", ""))
        if audio_root is not None:
            audio_path = audio_root / audio_path
        if not audio_path.is_file():
            continue
        r = dict(r)
        r["song_id"] = song_id
        r["audio_path"] = str(audio_path.resolve())
        out.append(r)
        if len(out) >= max_songs:
            break
    return out


def build_canonical_units(row: dict) -> list[dict]:
    """从 timestamp_class_ids 构造逐字符 canonical 单位（弱监督时间轴）。

    ids 长度恰 2×character_count：每字符 [onset,offset] class × 0.08s。
    end<=start 的 pair 容错：end = max(end, start+0.01)（如 yifen_1）。
    不连续的 id 保持原样（无 gap 时即连续）；id 即下标 i（0..N-1）。
    """
    lyrics = str(row.get("lyrics_normalized", ""))
    ids = list(row.get("timestamp_class_ids") or [])
    if len(ids) != 2 * len(lyrics):
        raise ValueError(
            f"timestamp_class_ids len {len(ids)} != 2 x character_count {len(lyrics)}"
        )
    units = []
    for i, ch in enumerate(lyrics):
        start = ids[2 * i] * TIMESTAMP_CLASS_SEC
        end = ids[2 * i + 1] * TIMESTAMP_CLASS_SEC
        if end <= start:
            end = start + 0.01  # 弱标签容错：保证 end > start
        units.append({
            "canonical_unit_id": i,
            "text": ch,
            "start_sec": round(start, 4),
            "end_sec": round(end, 4),
        })
    return units


def timeline_row(song_id: str, units: list[dict]) -> dict:
    return {"song_id": song_id, "canonical_units": units}


def _canonical_units_for_window(canonical_units, w0: float, w1: float) -> list[dict]:
    """窗 [w0,w1) 内 overlap 的 canonical 单位（与 c3 adapter 同语义：严格 overlap）。"""
    out = []
    for u in canonical_units:
        start, end = float(u["start_sec"]), float(u["end_sec"])
        if max(start, w0) < min(end, w1):
            out.append(u)
    out.sort(key=lambda u: int(u["canonical_unit_id"]))
    return out


def window_plan(duration: float, windows_per_song: int | None) -> list[tuple[float, float]]:
    """窗计划：返回 [(w0, w1), ...]，每窗长度 ∈ [30, 60]，不超 duration。

    - windows_per_song 缺省（None）：≤60s 单窗 [0, min(60,dur))；>60s 两窗
      [0,60) + tail（起点 = min(60, duration-30)，保证 tail 长 ≥30s）。
    - 显式 N：M4 同款均匀分布（span 上等距取 N 个 60s 起点，尾窗 <30s 丢弃）。
    """
    if windows_per_song is None:
        if duration <= WINDOW_SEC:
            starts = [0.0]
        else:
            starts = [0.0, min(WINDOW_SEC, duration - MIN_WINDOW_SEC)]
    elif windows_per_song <= 1:
        starts = [0.0]
    else:
        span = max(0.0, duration - WINDOW_SEC)
        starts = [span * i / (windows_per_song - 1) for i in range(windows_per_song)]
    out = []
    for w0 in starts:
        w1 = min(w0 + WINDOW_SEC, duration)
        if w1 - w0 < MIN_WINDOW_SEC:
            continue
        out.append((round(w0, 4), round(w1, 4)))
    return out


def build_requests(song: dict, units: list[dict], windows: list[tuple[float, float]],
                   *, timeline_sha: str, row_sha: str, sparse: bool = True) -> list[dict]:
    """从一首歌的 canonical units 生成窗请求（baseline + tail-missing(1/4) 配对）。

    每窗产出 full + sparse 两档 slot（--no-sparse 时仅 full）；每档 baseline + missing。
    missing 变体同步截断 canonical 字段：kept_ids、新 canonical_to_local、重算 slot
    （缺失单位不得留在请求 canonical 字段里）。
    """
    n = len(units)
    song_id = song["song_id"]
    reqs: list[dict] = []
    for wi, (w0, w1) in enumerate(windows):
        in_win = _canonical_units_for_window(units, w0, w1)
        if len(in_win) < MIN_UNITS_PER_WINDOW:
            continue  # 窗内歌词太少 → 跳过，避免空对齐
        cids = [int(u["canonical_unit_id"]) for u in in_win]
        texts = [u["text"] for u in in_win]
        canonical_to_local = {cid: i for i, cid in enumerate(cids)}
        c0, c1 = cids[0], cids[-1] + 1
        plans = [plan_slots(
            plan_id=f"{song_id}:w{wi}:full", canonical_unit_count=n,
            queried_canonical_ids=cids, strategy="contiguous",
            canonical_to_local=canonical_to_local, request_local_count=len(texts),
            comparison_group_id=f"{song_id}:w{wi}", phase="full")]
        if sparse:
            step = max(2, len(cids) // 6)
            plans.append(plan_slots(
                plan_id=f"{song_id}:w{wi}:sparse", canonical_unit_count=n,
                queried_canonical_ids=cids[::step], strategy=f"strided{step}",
                canonical_to_local=canonical_to_local, request_local_count=len(texts),
                comparison_group_id=f"{song_id}:w{wi}", phase="sparse"))
        for plan in plans:
            base = {
                "schema_version": "research_v7_long_slot_v1",
                "request_type": "long_timeline_mir1k",
                "item_id": f"{song_id}:w{wi}:{plan.phase_name}",
                "request_id": f"{song_id}:w{wi}:{plan.phase_name}",
                "parent_request_id": None,
                "audio_path": song["audio_path"],
                "audio_start_sec": w0, "audio_end_sec": w1,
                "duration_sec": round(w1 - w0, 4),
                "audio_source": "mir1k_vocal_channel1_ood",
                "text_source": "mir1k_qwen_fa_labels_v1", "has_gt": True,
                "evaluation_role": "lyrics_aligned", "text_window_aligned": True,
                "text_units": texts, "text_start_index": 0, "text_end_index": len(texts),
                "timestamp_slot_indices": list(plan.local_indices),
                "workflow_mode": "long_slot_60s", "mutation_type": "baseline",
                "mutation_parameters": {"position": "whole", "requested_ratio": 0.0},
                "language": "zh", "dataset": "mir1k", "split": song.get("split") or "test",
                "model_id": MODEL_ID, "checkpoint_id": CHECKPOINT_ID,
                "input_variant": "text_mutation",
                # canonical lineage（canonical_timeline_file_sha = timeline manifest sha，
                # canonical_timeline_row_sha = 本歌行 sha，adapter = 弱标签版本）
                "canonical_text_start": c0, "canonical_text_end": c1,
                "canonical_to_local": {str(k): v for k, v in canonical_to_local.items()},
                "canonical_ids": cids,
                "canonical_timeline_file_sha": timeline_sha,
                "canonical_timeline_row_sha": row_sha,
                "canonical_adapter_version": ADAPTER_VERSION,
                "source_window_start_sec": w0, "source_window_end_sec": w1,
                "condition": "baseline", "pair_id": f"{song_id}:w{wi}",
                "slot_plan_id": plan.plan_id, "comparison_group_id": plan.comparison_group_id,
                "phase": plan.phase_name,
            }
            # missing：virtual gap（移除尾部 1/4 单位，评价 omitted-original）。
            # 契约：text_units 截断后，canonical_ids/mapping/range/slot 全部同步到保留单位。
            n_miss = max(1, len(texts) // 4)
            miss = dict(base)
            miss["request_id"] = f"{base['request_id']}:missing"
            miss["item_id"] = f"{base['item_id']}:missing"
            miss["mutation_type"] = "missing"
            kept = texts[:-n_miss]
            kept_ids = cids[:-n_miss]
            kept_to_local = {cid: i for i, cid in enumerate(kept_ids)}
            # missing 的 slot：用保留 canonical ids 在【新 local 映射】上的本地索引重算
            kept_slots = plan_slots(
                plan_id=f"{base['slot_plan_id']}:missing", canonical_unit_count=n,
                queried_canonical_ids=[c for c in plan.requested_canonical_ids
                                       if c in kept_to_local],
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--labels", required=True,
                   help="mir1k_qwen_fa_labels.jsonl（弱监督逐字符时间戳标签）")
    p.add_argument("--audio-root",
                   default="/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood",
                   help="audio_relpath 的根目录（vocal wav 实际位置）")
    p.add_argument("--out-root", required=True)
    p.add_argument("--windows-per-song", type=int, default=None,
                   help="每歌窗数（缺省按 duration 自动：≤60s 单窗；>60s 两窗 [0,60)+tail≥30s）")
    p.add_argument("--no-sparse", action="store_true",
                   help="只产出 full slot 档（默认 full+sparse 两档）")
    p.add_argument("--limit", type=int, default=17, help="最多构造几首歌")
    args = p.parse_args(argv)

    labels = Path(args.labels)
    out = Path(args.out_root); out.mkdir(parents=True, exist_ok=True)
    labels_sha = _sha(labels)
    audio_root = Path(args.audio_root) if args.audio_root else None
    songs = load_labels(labels, audio_root, args.limit)
    if not songs:
        print(json.dumps({"ok": False, "reason": "no labels with existing audio",
                          "labels_sha256": labels_sha}, ensure_ascii=False))
        return 1

    tl_rows = []
    for song in songs:
        units = build_canonical_units(song)
        tl_rows.append(timeline_row(song["song_id"], units))
    _atomic_jsonl(out / "MIR_TIMELINE_MANIFEST.jsonl", tl_rows)
    timeline_sha = _sha(out / "MIR_TIMELINE_MANIFEST.jsonl")
    # timeline 文件 sha 进每个请求的 canonical lineage（正式身份内容字段）
    final_reqs = []
    for song in songs:
        units = build_canonical_units(song)
        row = timeline_row(song["song_id"], units)
        row_sha = _sha_bytes(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8"))
        final_reqs.extend(build_requests(
            song, units,
            window_plan(float(song.get("duration_sec", 0) or 0), args.windows_per_song),
            timeline_sha=timeline_sha, row_sha=row_sha, sparse=not args.no_sparse))
    _atomic_jsonl(out / "REQUESTS.jsonl", final_reqs)
    freeze = {
        "schema": "research_v7_mir1k_manifest_v1",
        "labels": {"path": str(labels), "sha256": labels_sha},
        "audio_root": str(audio_root) if audio_root else "",
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows_per_song": args.windows_per_song,
        "sparse_slots": not args.no_sparse,
        "songs": len(tl_rows),
        "windows": sum(len(window_plan(float(s.get("duration_sec", 0) or 0),
                                       args.windows_per_song)) for s in songs),
        "requests": len(final_reqs),
        "files": {
            "MIR_TIMELINE_MANIFEST.jsonl": timeline_sha,
            "REQUESTS.jsonl": _sha(out / "REQUESTS.jsonl"),
        },
    }
    _atomic_json(out / "FREEZE.json", freeze)
    print(json.dumps({"ok": True, "songs": len(tl_rows), "requests": len(final_reqs),
                      "out_root": str(out),
                      "freeze": freeze["files"]["REQUESTS.jsonl"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
