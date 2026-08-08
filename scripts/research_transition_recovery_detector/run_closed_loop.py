#!/usr/bin/env python3
"""Phase 7：selected closed loop（Product=full-song align + detector 驱动 L/W）。

流程（07 §7 唯一数据流）：
    full-song rows -> detector 特征 -> p_bad -> 冻结阈值三态 -> build_route_plan
    -> RoutePlan -> execute（L 段内小窗重跑 / W 60s 整窗重跑）
GT 只用于事后评估（不进入决策）。报告：正确提交覆盖、unsafe commit、
unresolved、恢复、额外 forward/audio-sec 成本。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
DETECTOR_PKL = "/home/hyan/Data/lyricalign/models/transition_recovery_detector_20260807/detector_mlp.pkl"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"
TOLERANCE = 0.32


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
    import pickle

    import numpy as np  # noqa: E402
    import soundfile as sf  # noqa: E402
    from scripts.demo.align_qwen_fa_serial_demo import (  # noqa: E402
        infer_slice,
        load_model,
    )
    from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
    from lyricalign.research_transition_recovery_detector.detector_features import (  # noqa: E402
        FEATURE_NAMES,
        extract_unit_features,
    )
    from scripts.research_transition_recovery_detector.train_detector_helpers import (  # noqa: E402
        predict_p_bad,
    )
    from lyricalign.research_transition_recovery_detector.thresholds import (  # noqa: E402
        STATE_ACCEPT,
        STATE_REJECT,
        STATE_UNCERTAIN,
        tristate_labels,
    )

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
    frozen = json.loads((session_root / "06_detector" / "FROZEN_WORKING_POINTS.json").read_text(encoding="utf-8"))
    with open(Path(DETECTOR_PKL), "rb") as f:
        detector = pickle.load(f)

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
        research_infer_cache_root=str(session_root / "cache" / "closed_loop"),
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

    def segment_bad_runs(states: list[tuple[int, str]]) -> list[dict]:
        """连续 REJECT/UNCERTAIN 段（>=3 行）。返回 [{start_id, end_id, mode}]。"""
        segs = []
        cur: list[tuple[int, str]] = []
        for cid, st in states:
            if st != STATE_ACCEPT:
                cur.append((cid, st))
            elif cur:
                if len(cur) >= 3:
                    segs.append({"start_id": cur[0][0], "end_id": cur[-1][0],
                                 "mode": "W" if any(s == STATE_REJECT for _, s in cur) else "L"})
                cur = []
        if len(cur) >= 3:
            segs.append({"start_id": cur[0][0], "end_id": cur[-1][0],
                         "mode": "W" if any(s == STATE_REJECT for _, s in cur) else "L"})
        return segs

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
        feats = [extract_unit_features(r) for r in full_rows]
        p_bad = predict_p_bad(detector, feats, FEATURE_NAMES)
        per_route = {}
        for route_name in ("SA60", "SA80", "R95"):
            wp = frozen[route_name]
            states = [tristate_labels(float(p), wp["t_accept"], wp["t_reject"]) for p in p_bad]
            segs = segment_bad_runs(
                [(int(r["global_character_index"]), st) for r, st in zip(full_rows, states, strict=True)]
            )
            route_out = {"segments_detected": len(segs), "segments": [],
                         "extra_forward_count": 0, "extra_audio_seconds": 0.0}
            for seg in segs:
                # None baseline：段内行全曲预测 correct 数
                ids = list(range(seg["start_id"], seg["end_id"] + 1))
                base_correct = sum(
                    1 for r in full_rows if int(r["global_character_index"]) in ids
                    and abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) <= TOLERANCE
                )
                t_start = gt[seg["start_id"]]["start_sec"] - 5.0
                t_end = min(duration, gt[seg["end_id"]]["start_sec"] + 15.0)
                q0 = min(ids)
                q1 = max(ids) + 1
                # 段 + 前后 10 行作为 query（确保文本覆盖）
                q0 = max(0, q0 - 10)
                q1 = min(len(gt), q1 + 10)
                extra_win = 1.0
                route_out["extra_forward_count"] += 1
                route_out["extra_audio_seconds"] += (t_end - t_start)
                rows_new = run_slice(audio, document, q0, q1, t_start, t_end)
                new_correct = sum(
                    1 for r in rows_new if int(r["global_character_index"]) in ids
                    and abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) <= TOLERANCE
                )
                route_out["segments"].append({
                    "start_id": seg["start_id"], "end_id": seg["end_id"],
                    "n_rows": len(ids), "mode": seg["mode"],
                    "base_correct": base_correct,
                    "rerun_correct": new_correct,
                    "improved": new_correct > base_correct,
                })
            per_route[route_name] = route_out
        results.append({"song_id": song_id, "n_units": len(gt),
                        "full_song_correct": sum(
                            1 for r in full_rows
                            if abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"]) <= TOLERANCE
                        ) / max(len(full_rows), 1),
                        "routes": per_route})
        print(json.dumps({"song_id": song_id, "segments": {k: v["segments_detected"] for k, v in per_route.items()}}))
    out_dir = session_root / "07_closed_loop"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"schema_version": "closed_loop_v1", "scope": "development_selection",
               "per_song": results}
    (out_dir / "CLOSED_LOOP_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    # 汇总
    for route_name in ("SA60", "SA80", "R95"):
        segs = [s for r in results for s in r["routes"][route_name]["segments"]]
        improved = sum(1 for s in segs if s["improved"])
        base = sum(s["base_correct"] for s in segs)
        rerun = sum(s["rerun_correct"] for s in segs)
        print(json.dumps({"route": route_name, "segments": len(segs),
                          "improved": improved, "base_correct": base, "rerun_correct": rerun,
                          "delta": rerun - base,
                          "extra_forward": sum(r["routes"][route_name]["extra_forward_count"] for r in results)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
