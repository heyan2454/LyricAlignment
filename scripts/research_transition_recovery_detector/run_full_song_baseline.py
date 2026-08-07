#!/usr/bin/env python3
"""Phase 2 补充：full-song 单次对齐 baseline（T0_product_independent_v1 候选）。

一次性整曲对齐（非串行、无窗口状态），在 model_selection songs 上评估，
与 T0 windowed oracle 对照。输出 <session>/02_transition/FULL_SONG_<role>.json。
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
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"


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
    p.add_argument("--tolerance", type=float, default=0.32)
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
    manifest = [
        json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_song = {r["song_id"]: r for r in manifest}

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
        timestamp_segment_sec=0.08,
        decoder_kind="raw",
        decoder_top_k=8,
        decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "full_song"),
        research_model_identity={"kind": "lora" if checkpoint else "raw"},
        device=args.device,
    )
    results = []
    for song_id in song_ids:
        row = by_song[song_id]
        audio, sr = sf.read(row["concat_audio_path"], dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        text = "".join(u["text"] for u in row["canonical_units"])
        document = parse_lyrics_text(text, language="Chinese")
        rows, audit = infer_slice(
            processor=processor, model=model, audio=audio, document=document,
            character_start=0, character_end=len(document.characters),
            global_audio_offset_sec=0.0, args=infer_args,
        )
        gt = {int(u["canonical_unit_id"]): u for u in row["canonical_units"]}
        diffs = [
            abs(float(r["fixed_global_start_sec"]) - gt[int(r["global_character_index"])]["start_sec"])
            for r in rows
            if int(r["global_character_index"]) in gt
        ]
        correct = sum(1 for d in diffs if d <= args.tolerance)
        out = {
            "song_id": song_id, "scope": "development_selection",
            "mode": "full_song_align",
            "rows": len(rows), "evaluated": len(diffs),
            "accuracy": {
                "correct": correct, "wrong": len(diffs) - correct,
                "total": len(diffs),
                "correct_rate": correct / len(diffs) if diffs else 0.0,
            },
            "max_diff_sec": max(diffs) if diffs else None,
            "median_diff_sec": sorted(diffs)[len(diffs) // 2] if diffs else None,
        }
        results.append(out)
        print(json.dumps({k: out[k] for k in ("song_id", "rows", "accuracy")}, ensure_ascii=False))
    out_path = session_root / "02_transition" / f"FULL_SONG_{args.role}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
    print(f"FULL_SONG {args.role}: {len(results)} songs -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
