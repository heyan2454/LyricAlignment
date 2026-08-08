#!/usr/bin/env python3
"""Phase 8：Test Demo 自动分析（无 GT，不报 MAE/accuracy）。

自动发现 demo 目录的音频+同名 txt，每首：full-song 对齐 + detector 结构分析：
raw/official 差异、零时长/压缩 run、后验多峰、detector 标记段、suspicious ranking。
输出 TEST_DEMO_SUMMARY.json（含 per-song 结构与 ranking）。
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
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".mp4", ".mov", ".aac"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--demo-root", default="/home/hyan/Data/lyricalign/test")
    p.add_argument("--extra-roots", nargs="*", default=["/home/hyan/LyricAlignment/夜苏打"])
    p.add_argument("--limit", type=int, default=0)
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
    frozen = json.loads((session_root / "06_detector" / "FROZEN_WORKING_POINTS.json").read_text(encoding="utf-8"))
    with open(Path(DETECTOR_PKL), "rb") as f:
        detector = pickle.load(f)

    roots = [Path(args.demo_root)] + [Path(r) for r in args.extra_roots]
    items = []
    for root in roots:
        if not root.is_dir():
            continue
        for audio in sorted(root.rglob("*")):
            if audio.suffix.lower() not in AUDIO_EXTS:
                continue
            txt = audio.with_suffix(".txt")
            if not txt.is_file():
                continue
            lang = "unknown"
            rel = audio.relative_to(root)
            parts = rel.parts
            for cand in ("Chinese", "English", "Japanese", "Cantonese"):
                if cand in parts:
                    lang = cand.lower()
                    break
            items.append({"audio": audio, "txt": txt, "lang": lang, "root": root})
    if args.limit:
        items = items[:args.limit]
    print(f"discovered {len(items)} demo items")

    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf", revision=args.model_revision,
        cache_dir=args.cache_dir, local_files_only=True, device=args.device,
    )
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "demo_analysis"),
        research_model_identity={"kind": "lora" if checkpoint else "raw"}, device=args.device,
    )

    per_song = []
    failed = []
    for idx, item in enumerate(items):
        try:
            audio, sr = sf.read(str(item["audio"]), dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if sr != 16000:
                import scipy.signal as sig

                audio = sig.resample_poly(audio, 16000, sr).astype(np.float32)
                sr = 16000
            text = item["txt"].read_text(encoding="utf-8-sig")
            if not text.strip():
                failed.append({"item": str(item["audio"]), "reason": "empty txt"})
                continue
            try:
                document = parse_lyrics_text(text, language={
                    "japanese": "Japanese", "english": "English", "cantonese": "Cantonese",
                    "chinese": "Chinese", "unknown": "Chinese",
                }[item["lang"]])
            except Exception:
                document = parse_lyrics_text(text, language="Chinese")
            duration = float(len(audio) / 16000)
            rows, _ = infer_slice(
                processor=processor, model=model, audio=audio, document=document,
                character_start=0, character_end=len(document.characters),
                global_audio_offset_sec=0.0, args=infer_args,
            )
            feats = [extract_unit_features(r) for r in rows]
            p_bad = predict_p_bad(detector, feats, FEATURE_NAMES)
            wp = frozen["SA80"]
            states = [tristate_labels(float(pp), wp["t_accept"], wp["t_reject"]) for pp in p_bad]
            # 结构指标
            starts = [float(r["fixed_global_start_sec"]) for r in rows]
            zero_run = 0
            cur_zero = 0
            raw_off_diff = 0.0
            top2_peaks = 0
            for r in rows:
                if float(r.get("fixed_global_start_sec", 0)) == float(r.get("fixed_global_end_sec", -1)):
                    cur_zero += 1
                    zero_run = max(zero_run, cur_zero)
                else:
                    cur_zero = 0
                if r.get("official_fixed_global_start_sec") is not None:
                    raw_off_diff += abs(float(r["fixed_global_start_sec"]) - float(r["official_fixed_global_start_sec"]))
                if r.get("raw_start_topk_probabilities") and len(r["raw_start_topk_probabilities"]) >= 2:
                    if float(r["raw_start_topk_probabilities"][1]) > 0.15:
                        top2_peaks += 1
            n_reject = states.count(STATE_REJECT)
            n_uncertain = states.count(STATE_UNCERTAIN)
            mono = len(starts) == len(set(round(s, 2) for s in starts))
            record = {
                "item": str(item["audio"].relative_to(item["root"])),
                "lang": item["lang"],
                "duration_sec": round(duration, 1),
                "n_units": len(rows),
                "raw_official_mean_diff_sec": round(raw_off_diff / max(len(rows), 1), 3),
                "zero_duration_max_run": zero_run,
                "top2_competing_peak_units": top2_peaks,
                "tristate_SA80": {STATE_ACCEPT: states.count(STATE_ACCEPT),
                                  STATE_REJECT: n_reject, STATE_UNCERTAIN: n_uncertain},
                "suspicious_score": round(
                    (n_reject + 0.5 * n_uncertain + top2_peaks * 0.1 + zero_run * 0.2)
                    / max(len(rows), 1), 4),
                "monotonic_starts": mono,
            }
            per_song.append(record)
            print(json.dumps({k: record[k] for k in ("item", "lang", "n_units", "suspicious_score")}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            failed.append({"item": str(item["audio"]), "reason": str(exc)[:200]})
            print(json.dumps({"item": str(item["audio"]), "failed": str(exc)[:100]}, ensure_ascii=False))
    ranking = sorted(per_song, key=lambda r: -r["suspicious_score"])
    out_dir = session_root / "08_transfer_demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "test_demo_analysis_v1",
        "n_items": len(per_song), "n_failed": len(failed),
        "no_gt": True,
        "ranking": ranking,
        "failed": failed,
        "note": "无 GT，不报告 MAE/accuracy；suspicious_score 为 REJECT/UNCERTAIN/竞争峰/零时长 run 的启发式组合",
    }
    (out_dir / "TEST_DEMO_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"n_items": len(per_song), "n_failed": len(failed),
                      "top_suspicious": [r["item"] for r in ranking[:5]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
