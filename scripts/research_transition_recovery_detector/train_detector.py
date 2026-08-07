#!/usr/bin/env python3
"""Phase 6：Detector 数据收集 + 训练 + SA60/SA80/R95 冻结。

四角色顺序（07 §6）：detector_train -> model_selection -> threshold_validation -> 冻结。
- collect：对 role 的歌曲跑 T2 轨迹（infer_slice cache 命中则无 GPU），records 含完整特征字段
- train：detector_train 数据 -> simple MLP（sklearn）-> 输出模型/scaler
- evaluate：model_selection（模型选择）与 threshold_validation（SA60/SA80/R95）评估
- freeze：threshold_validation 唯一阈值 -> FROZEN_WORKING_POINTS.json
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE  # noqa: E402
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    DEFAULT_UNIT_DENSITY_SEC,
    RealAlignerBackend,
    TransitionRunner,
)
from lyricalign.research_transition_recovery_detector.detector_features import (  # noqa: E402
    FEATURE_NAMES,
    extract_unit_features,
)
from lyricalign.research_transition_recovery_detector.thresholds import (  # noqa: E402
    joint_working_point,
    select_working_point,
)

R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"
TOLERANCE = 0.32


def collect_role(args: argparse.Namespace, runner: TransitionRunner, role: str) -> None:
    import soundfile as sf  # noqa: E402
    from scripts.demo.align_qwen_fa_serial_demo import build_vocal_activity_profile  # noqa: E402
    from lyricalign.demo.window_planning import build_silence_aware_window_plan  # noqa: E402
    from scripts.research_transition_recovery_detector.run_transition_smoke import (  # noqa: E402
        load_song_from_timeline,
    )

    session_root = Path(args.session_root)
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][role]
    by_song = {
        json.loads(line)["song_id"]: json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for song_id in song_ids:
        row = by_song[song_id]
        audio, document, gt = load_song_from_timeline(row)
        duration = float(len(audio) / 16000)
        plan = build_silence_aware_window_plan(
            duration, build_vocal_activity_profile(audio, sample_rate=16000),
            target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
        )
        runner.run_song(
            song_id=song_id, audio=audio, document=document, window_plan=plan,
            transition=TRANSITION_T2_CORE, gt_timeline=gt,
            compress=True, retained_total_sec=3.0,
        )
        print(json.dumps({"collect": role, "song": song_id, "done": True}))


def load_units(session_root: Path, role: str) -> tuple[list[dict], list[float | None]]:
    """从 T2 records 提取 (特征, label)。records 的 raw_global_rows 含完整字段。"""
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    gt_by_song: dict[str, dict[int, dict]] = {}
    for song_id in split["roles"][role]:
        p = session_root / "02_transition" / f"{song_id}__{TRANSITION_T2_CORE}.jsonl"
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            for r in rec["evidence_summary"]["raw_global_rows"]:
                pass
    # 简化：直接用 GT manifest
    return [], []


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--mode", choices=("collect", "train", "evaluate", "freeze"), required=True)
    p.add_argument("--role", default="detector_train")
    p.add_argument("--checkpoint", default=R2_CHECKPOINT_DEFAULT)
    p.add_argument("--model-revision", default=MODEL_REVISION_DEFAULT)
    p.add_argument("--cache-dir", default="/home/hyan/Data/lyricalign/models/hf_cache")
    p.add_argument("--device", default="cuda:0")
    args = p.parse_args()
    session_root = Path(args.session_root)

    if args.mode == "collect":
        import argparse as _argparse

        from scripts.demo.align_qwen_fa_serial_demo import build_vocal_activity_profile, load_model  # noqa: E402

        model_args = _argparse.Namespace(
            model="Qwen/Qwen3-ForcedAligner-0.6B-hf", revision=args.model_revision,
            cache_dir=args.cache_dir, local_files_only=True, device=args.device,
        )
        checkpoint = Path(args.checkpoint) if args.checkpoint else None
        processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
        model_identity = {"kind": "lora" if checkpoint else "raw", "checkpoint": str(checkpoint)}
        infer_args = _argparse.Namespace(
            timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
            research_infer_cache_root=str(session_root / "cache" / "serial_infer"),
            research_model_identity=model_identity, device=args.device,
        )
        config = {
            "unit_density_sec": DEFAULT_UNIT_DENSITY_SEC, "lookback_units": 8,
            "model_identity": model_identity, "env_identity": f"gpu-{args.role}",
            "config_hash": f"detector-collect-{args.role}-v1", "sample_rate": 16000,
            "audio_profile_provider": lambda a: build_vocal_activity_profile(a, sample_rate=16000),
            "min_original_silence_sec": 5.0,
        }
        backend = RealAlignerBackend(processor=processor, model=model, args=infer_args)
        runner = TransitionRunner(config, session_root=session_root, backend=backend)
        collect_role(args, runner, args.role)
        return 0

    if args.mode == "train":
        from scripts.research_transition_recovery_detector.train_detector_helpers import (  # noqa: E402
            build_dataset,
            train_mlp,
        )

        features, labels, meta = build_dataset(session_root, args.role, tolerance=TOLERANCE)
        model, scaler, auc = train_mlp(features, labels, feature_names=FEATURE_NAMES)
        out_dir = session_root / "06_detector"
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "detector_mlp.pkl", "wb") as f:
            pickle.dump({"model": model, "scaler": scaler, "feature_names": FEATURE_NAMES}, f)
        (out_dir / "TRAIN_META.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps({"mode": "train", "n_units": len(features), **auc}))
        return 0

    if args.mode == "evaluate":
        from scripts.research_transition_recovery_detector.train_detector_helpers import (  # noqa: E402
            build_dataset,
            predict_p_bad,
        )
        with open(session_root / "06_detector" / "detector_mlp.pkl", "rb") as f:
            artifact = pickle.load(f)
        features, labels, meta = build_dataset(session_root, args.role, tolerance=TOLERANCE)
        p_bad = predict_p_bad(artifact, features, FEATURE_NAMES)
        out = session_root / "06_detector" / f"EVAL_{args.role}.json"
        out.write_text(json.dumps({
            "role": args.role, "n_units": len(p_bad),
            "labels": labels, "p_bad": [round(float(v), 6) for v in p_bad],
        }, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps({"mode": "evaluate", "role": args.role, "n": len(p_bad)}))
        return 0

    if args.mode == "freeze":
        from scripts.research_transition_recovery_detector.train_detector_helpers import (  # noqa: E402
            build_dataset,
            predict_p_bad,
        )
        with open(session_root / "06_detector" / "detector_mlp.pkl", "rb") as f:
            artifact = pickle.load(f)
        features, labels, meta = build_dataset(session_root, "threshold_validation", tolerance=TOLERANCE)
        p_bad = predict_p_bad(artifact, features, FEATURE_NAMES)
        valid = [(float(p), g) for p, g in zip(p_bad, labels, strict=True) if g is not None]
        p_list = [p for p, _ in valid]
        g_list = [g for _, g in valid]
        sa60 = select_working_point(p_list, g_list, constraint="SA60", level=0.60)
        sa80 = select_working_point(p_list, g_list, constraint="SA80", level=0.80)
        r95 = select_working_point(p_list, g_list, constraint="R95", level=0.95)
        joint = joint_working_point(p_list, g_list)
        frozen = {
            "schema_version": "frozen_working_points_v1",
            "model": str(session_root / "06_detector" / "detector_mlp.pkl"),
            "feature_names": list(FEATURE_NAMES),
            "SA60": sa60, "SA80": sa80, "R95": r95, "joint_sa60_r95": joint,
            "threshold_validation_denominators": {
                "safe": sum(1 for g in g_list if g == 0),
                "unsafe": sum(1 for g in g_list if g == 1),
                "total": len(g_list),
            },
        }
        out = session_root / "06_detector" / "FROZEN_WORKING_POINTS.json"
        out.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk in ("feasible", "t_accept", "t_reject", "safe_accept", "unsafe_reject")}) for k, v in frozen.items() if k in ("SA60", "SA80", "R95", "joint_sa60_r95")}, ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
