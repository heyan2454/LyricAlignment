#!/usr/bin/env python3
"""Phase 4：Oracle Recovery 上界（full-song 错位段的 L/W 修复，07 §6 Phase 4）。

GT 只用于：1) 定位 full-song 结果中的真实错误段；2) 评估修复率。
输入模型时泄漏 GT 特征（oracle decision/anchor），检测自身能力不含 detector。

- Oracle-L：对错误段用小窗（30s）重对齐（窗覆盖段范围 ±10s context，query=GT 段内行），
  保留段外正确区不动（本实现评估段内修复率）。
- Oracle-W：对错误段用 60s 标准窗重跑全窗。
输出 <session>/04_oracle_recovery/ORACLE_SUMMARY.json。
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
        if cur and cid != cur[-1] + 1 and (cid - cur[-1]) <= 2:
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
            t0 = max(0.0, seg["start_sec"] - 10.0)
            t1 = min(duration, seg["end_sec"] + 10.0)
            q0 = min(seg["ids"])
            q1 = max(seg["ids"]) + 1
            # Oracle-L：30s 小窗（若段本身 <=30s；否则 60s）
            win_sec = 30.0 if seg["end_sec"] - seg["start_sec"] <= 30.0 else 60.0
            l_start = max(0.0, seg["start_sec"] - 5.0)
            l_end = min(duration, l_start + win_sec + 10.0)
            lqids = sorted(i for i, u in gt.items() if l_start - 10.0 <= u["start_sec"] <= l_end + 10.0)
            rows_l = run_slice(audio, document, min(lqids), max(lqids) + 1, l_start, l_end)
            seg_ids = set(seg["ids"])
            fixed_l = sum(
                1 for r in rows_l if int(r["global_character_index"]) in seg_ids
                and abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) <= TOLERANCE
            )
            # Oracle-W：60s 整窗重跑覆盖段
            w_start = max(0.0, seg["start_sec"] - 10.0)
            w_end = min(duration, w_start + 70.0)
            wqids = sorted(i for i, u in gt.items() if w_start - 10.0 <= u["start_sec"] <= w_end + 10.0)
            rows_w = run_slice(audio, document, min(wqids), max(wqids) + 1, w_start, w_end)
            fixed_w = sum(
                1 for r in rows_w if int(r["global_character_index"]) in seg_ids
                and abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) <= TOLERANCE
            )
            segments_out.append({
                "start_sec": round(seg["start_sec"], 1), "end_sec": round(seg["end_sec"], 1),
                "n_rows": seg["n_rows"],
                "oracle_L_fixed": fixed_l, "oracle_W_fixed": fixed_w,
                "L_recovery_rate": round(fixed_l / seg["n_rows"], 3),
                "W_recovery_rate": round(fixed_w / seg["n_rows"], 3),
            })
        song_out["segments"] = segments_out
        results.append(song_out)
        print(json.dumps({"song_id": song_id, "n_segments": len(segments),
                          "full_song_correct": round(song_out["full_song_correct"], 3)}, ensure_ascii=False))
    out_dir = session_root / "04_oracle_recovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    n_rows = sum(s["segments"][i]["n_rows"] for s in results for i in range(len(s["segments"])))
    fixed_l = sum(s["segments"][i]["oracle_L_fixed"] for s in results for i in range(len(s["segments"])))
    fixed_w = sum(s["segments"][i]["oracle_W_fixed"] for s in results for i in range(len(s["segments"])))
    summary = {
        "schema_version": "oracle_recovery_v1",
        "scope": "development_selection",
        "songs": len(results),
        "segments": sum(len(s["segments"]) for s in results),
        "segment_rows_total": n_rows,
        "oracle_L_fixed_rows": fixed_l,
        "oracle_L_recovery_rate": round(fixed_l / max(n_rows, 1), 4),
        "oracle_W_fixed_rows": fixed_w,
        "oracle_W_recovery_rate": round(fixed_w / max(n_rows, 1), 4),
        "per_song": results,
    }
    (out_dir / "ORACLE_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"segments": summary["segments"], "L": summary["oracle_L_recovery_rate"],
                      "W": summary["oracle_W_recovery_rate"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
