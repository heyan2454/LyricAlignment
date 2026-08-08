#!/usr/bin/env python3
"""Phase 8：MIR-1K fixed transfer（冻结 detector/threshold 直接迁移，不重调）。

每首 MIR 歌：official vocal -> full-song 对齐 -> detector p_bad -> 冻结阈值三态。
GT 为字符级 ground_truth.characters.jsonl。输出 MIR_TRANSFER_SUMMARY.json。
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
MIR_SUBSET = "/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--mir-root", default=MIR_SUBSET)
    p.add_argument("--checkpoint", default=R2_CHECKPOINT_DEFAULT)
    p.add_argument("--model-revision", default=MODEL_REVISION_DEFAULT)
    p.add_argument("--cache-dir", default="/home/hyan/Data/lyricalign/models/hf_cache")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--limit", type=int, default=17)
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
    mir_root = Path(args.mir_root)
    frozen = json.loads((session_root / "06_detector" / "FROZEN_WORKING_POINTS.json").read_text(encoding="utf-8"))
    with open(Path(DETECTOR_PKL), "rb") as f:
        detector = pickle.load(f)

    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf", revision=args.model_revision,
        cache_dir=args.cache_dir, local_files_only=True, device=args.device,
    )
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "mir_transfer"),
        research_model_identity={"kind": "lora" if checkpoint else "raw"}, device=args.device,
    )

    results = []
    for line in Path(mir_root / "selection.jsonl").read_text(encoding="utf-8").splitlines()[:args.limit]:
        if not line.strip():
            continue
        sel = json.loads(line)
        item_id = sel["item_id"]
        item_dir = mir_root / "items" / item_id
        wav = item_dir / "audio" / "official_vocal.wav"
        if not wav.is_file():
            wav = item_dir / "audio" / "mix.wav"
        audio, sr = sf.read(str(wav), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 16000:
            # 简单线性重采样到 16k
            import scipy.signal as sig

            audio = sig.resample_poly(audio, 16000, sr).astype(np.float32)
            sr = 16000
        gt_rows = [
            json.loads(l)
            for l in (item_dir / "ground_truth.characters.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        gt = {r["character_index"]: r for r in gt_rows}
        text = "".join(r["normalized_character"] for r in gt_rows)
        document = parse_lyrics_text(text, language="Chinese")
        rows, _ = infer_slice(
            processor=processor, model=model, audio=audio, document=document,
            character_start=0, character_end=len(document.characters),
            global_audio_offset_sec=0.0, args=infer_args,
        )
        diffs = []
        for r in rows:
            cid = int(r["global_character_index"])
            g = gt.get(cid)
            if g is not None:
                diffs.append(abs(float(r["fixed_global_start_sec"]) - float(g["start_sec"])))
        correct = sum(1 for d in diffs if d <= TOLERANCE)
        feats = [extract_unit_features(r) for r in rows]
        p_bad = predict_p_bad(detector, feats, FEATURE_NAMES)
        tristate = {k: 0 for k in (STATE_ACCEPT, STATE_REJECT, STATE_UNCERTAIN)}
        for pp, g in zip(p_bad, [gt.get(int(r["global_character_index"])) for r in rows], strict=True):
            wp = frozen["SA80"]
            st = tristate_labels(float(pp), wp["t_accept"], wp["t_reject"])
            tristate[st] += 1
        out = {
            "item_id": item_id, "song_id": sel["song_id"],
            "n_units": len(diffs), "correct": correct,
            "correct_rate": round(correct / max(len(diffs), 1), 4),
            "median_abs_diff": round(sorted(diffs)[len(diffs) // 2], 3) if diffs else None,
            "tristate_SA80": tristate,
        }
        results.append(out)
        print(json.dumps({k: out[k] for k in ("item_id", "n_units", "correct", "correct_rate")}, ensure_ascii=False))
    out_dir = session_root / "08_transfer_demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    total = sum(r["n_units"] for r in results)
    correct_total = sum(r["correct"] for r in results)
    summary = {
        "schema_version": "mir_transfer_v1",
        "fixed_transfer": True, "n_songs": len(results), "pooled_units": total,
        "pooled_correct_rate": round(correct_total / max(total, 1), 4),
        "per_song": results,
        "note": "MIR 标签 schema 与 M4 不同（字符级 ground_truth），不拼入 M4 总表；detector/threshold 未重调",
    }
    (out_dir / "MIR_TRANSFER_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"pooled_correct_rate": summary["pooled_correct_rate"], "n_songs": len(results)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
