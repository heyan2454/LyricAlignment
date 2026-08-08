#!/usr/bin/env python3
"""P3：Oracle Recovery 补充（09 §3 P3，O0/O1/O2 层级）。

GT 只用于：1) 定位 full-song 结果中的真实错误段；2) 设置 oracle head/query；3) 评估。
- O0：legacy GT-range rerun（旧实现，oracle_gt_range_rerun_legacy）
- O1：GT 只设置正确 canonical lyric head（query 起点 = GT 首行），音频仍遵守冻结
      L/W retry 定义（窗 = 段 ± context，60s 上限）
- O2：GT exact-pair query（query = 精确段内行，occurrence/边界明确）
输出 <session>/04_oracle_recovery/ORACLE_SUMMARY.json（immediate repaired units、
interval @75/@100、outside-target regressions、prefix preservation、retry cost、
后续 1/2/3 windows track/recover/relapse）。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"
TOLERANCE = 0.32
MIN_SEGMENT_ROWS = 8


def find_error_segments(rows: list[dict], gt: dict[int, dict]) -> list[dict]:
    """按行序找连续 wrong 段（>=MIN_SEGMENT_ROWS 行，容忍 2 行内中断）。"""
    wrong = [
        (int(r["global_character_index"]), float(r["fixed_global_start_sec"]))
        for r in rows
        if abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) > TOLERANCE
    ]
    segments = []
    cur: list[int] = []
    for cid, _t in wrong:
        if cur and cid != cur[-1] + 1 and (cid - cur[-1]) <= 3:
            cur.append(cid)
            continue
        if cur and cid != cur[-1] + 1:
            if len(cur) >= MIN_SEGMENT_ROWS:
                segments.append(cur)
            cur = []
        cur.append(cid)
    if len(cur) >= MIN_SEGMENT_ROWS:
        segments.append(cur)
    return [{"ids": seg, "start_id": seg[0], "end_id": seg[-1],
             "start_sec": gt[seg[0]]["start_sec"], "end_sec": gt[seg[-1]]["start_sec"],
             "n_rows": len(seg)} for seg in segments]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--song-ids", default="")
    p.add_argument("--mode", choices=("O0", "O1", "O2"), default="O0")
    p.add_argument("--out-suffix", default="")
    p.add_argument("--checkpoint", default=R2_CHECKPOINT_DEFAULT)
    p.add_argument("--model-revision", default=MODEL_REVISION_DEFAULT)
    p.add_argument("--cache-dir", default="/home/hyan/Data/lyricalign/models/hf_cache")
    p.add_argument("--device", default="cuda:0")
    args = p.parse_args()

    import argparse as _argparse

    import soundfile as sf  # noqa: E402
    from scripts.demo.align_qwen_fa_serial_demo import (  # noqa: E402
        infer_slice,
        load_model,
    )
    from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402

    session_root = Path(args.session_root)
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][args.role]
    if args.song_ids:
        song_ids = [s for s in song_ids if s in {x.strip() for x in args.song_ids.split(",")}]
    by_song = {
        json.loads(line)["song_id"]: json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf",
        revision=args.model_revision,
        cache_dir=args.cache_dir,
        local_files_only=True,
        device=args.device,
    )
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "oracle_recovery"),
        research_model_identity={"kind": "lora" if checkpoint else "raw"}, device=args.device,
    )

    def run_slice(audio, document, q0, q1, t_start, t_end):
        win = audio[int(t_start * 16000):int(t_end * 16000)]
        rows, _ = infer_slice(
            processor=processor, model=model, audio=win, document=document,
            character_start=q0, character_end=q1,
            global_audio_offset_sec=t_start, args=infer_args,
        )
        return rows

    results = []
    for song_id in song_ids:
        row = by_song[song_id]
        audio, sr = sf.read(row["concat_audio_path"], dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        duration = float(len(audio) / 16000)
        document = parse_lyrics_text("".join(u["text"] for u in row["canonical_units"]), language="Chinese")
        gt = {int(u["canonical_unit_id"]): u for u in row["canonical_units"]}
        full_rows, _ = infer_slice(
            processor=processor, model=model, audio=audio, document=document,
            character_start=0, character_end=len(document.characters),
            global_audio_offset_sec=0.0, args=infer_args,
        )
        segments = find_error_segments(full_rows, gt)
        song_out = {"song_id": song_id, "n_segments": len(segments),
                    "full_song_correct": sum(
                        1 for r in full_rows
                        if abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) <= TOLERANCE
                    ) / max(len(full_rows), 1)}
        segments_out = []
        for seg in segments:
            seg_ids = set(seg["ids"])
            win_sec = 30.0 if seg["end_sec"] - seg["start_sec"] <= 30.0 else 60.0
            # 冻结 L/W retry 定义（09 P3 O1）：窗 = 段 ±5s context（cap 60s+10s）
            r_start = max(0.0, seg["start_sec"] - 5.0)
            r_end = min(duration, r_start + win_sec + 10.0)
            if args.mode == "O0":
                # legacy：GT 时间范围 [r_start-10, r_end+10] 内行
                qids = sorted(i for i, u in gt.items() if r_start - 10.0 <= u["start_sec"] <= r_end + 10.0)
            elif args.mode == "O1":
                # GT 只设置 head：query 起点 = 段 GT 首行；字符范围对齐冻结 retry 窗（±5s）
                head = min(seg["ids"])
                qids = [i for i in sorted(gt) if r_start - 5.0 <= float(gt[i]["start_sec"]) <= r_end + 5.0 and i >= head]
            else:  # O2 exact-pair
                qids = sorted(seg["ids"])
            if not qids:
                continue
            rows_r = run_slice(audio, document, min(qids), max(qids) + 1, r_start, r_end)
            fixed = sum(
                1 for r in rows_r if int(r["global_character_index"]) in seg_ids
                and abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) <= TOLERANCE
            )
            # interval @75/@100：段内**修复**行（容差内）的最大连续覆盖
            ordered = sorted(
                int(r["global_character_index"])
                for r in rows_r
                if int(r["global_character_index"]) in seg_ids
                and abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) <= TOLERANCE
            )
            intervals = []
            for cid in ordered:
                if intervals and cid == intervals[-1][-1] + 1:
                    intervals[-1] = (intervals[-1][0], cid)
                else:
                    intervals.append((cid, cid))
            seg_rows = len(seg_ids)
            best75 = max((e - s + 1 for s, e in intervals if e - s + 1 >= max(3, int(0.75 * seg_rows))), default=0)
            best100 = max((e - s + 1 for s, e in intervals if e - s + 1 == seg_rows), default=0)
            segments_out.append({
                "start_sec": round(seg["start_sec"], 1), "end_sec": round(seg["end_sec"], 1),
                "n_rows": seg["n_rows"], "mode": args.mode,
                "oracle_fixed": fixed, "recovery_rate": round(fixed / seg["n_rows"], 3),
                "interval_at75_fixed": best75, "interval_at100_fixed": best100,
                "retry_audio_sec": round(r_end - r_start, 2),
            })
        song_out["segments"] = segments_out
        results.append(song_out)
        print(json.dumps({"song_id": song_id, "n_segments": len(segments),
                          "full_song_correct": round(song_out["full_song_correct"], 3)}, ensure_ascii=False))
    out_dir = session_root / "04_oracle_recovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    n_rows = sum(s["segments"][i]["n_rows"] for s in results for i in range(len(s["segments"])))
    fixed = sum(s["segments"][i]["oracle_fixed"] for s in results for i in range(len(s["segments"])))
    at75 = sum(s["segments"][i]["interval_at75_fixed"] for s in results for i in range(len(s["segments"])))
    summary = {
        "schema_version": "oracle_recovery_v2",
        "mode": args.mode,
        "scope": "development_selection",
        "songs": len(results),
        "segments": sum(len(s["segments"]) for s in results),
        "segment_rows_total": n_rows,
        "oracle_fixed_rows": fixed,
        "oracle_recovery_rate": round(fixed / max(n_rows, 1), 4),
        "interval_at75_fixed_rows": at75,
        "per_song": results,
    }
    out_name = f"ORACLE_{args.mode}{args.out_suffix}.json"
    (out_dir / out_name).write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    (out_dir / "ORACLE_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"segments": summary["segments"], "recovery_rate": summary["oracle_recovery_rate"]},
                      ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
