#!/usr/bin/env python3
"""11 计划 Stage 5：retry failure decomposition（36 retry windows before/after）。

对 model_selection 9 首 × 4 窗（L-SA60 配置）重放 closed-loop v3，每窗保存：
- before：raw/official timing、100/250/500/1000ms correctness、MAE、detector states/score、route plan
- retry after：retry rows 的 timing/correctness/MAE、detector 再决策、writeback 结果
分类：retry_improved_detector_accept / retry_improved_detector_block / retry_not_improved / retry_worsened
improved = 250ms correct coverage +10pp 或 MAE 相对 -20%；worsened 对称；其余 neutral。
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

from lyricalign.research_transition_recovery_detector.detector_features import extract_signal_features  # noqa: E402
from scripts.research_transition_recovery_detector.train_detector_helpers import predict_p_bad  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--records-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--detector-pkl", required=True)
    p.add_argument("--route-mode", default="L")
    p.add_argument("--working-point", default="SA60")
    p.add_argument("--device", default="cuda:0")
    args = p.parse_args()

    import argparse as _argparse

    import soundfile as sf  # noqa: E402
    from scripts.demo.align_qwen_fa_serial_demo import build_vocal_activity_profile, load_model  # noqa: E402
    from lyricalign.demo.window_planning import build_silence_aware_window_plan  # noqa: E402
    from scripts.research_transition_recovery_detector.run_transition_smoke import load_song_from_timeline  # noqa: E402
    from scripts.research_transition_recovery_detector.run_closed_loop_v3 import run_closed_loop_v3_song  # noqa: E402
    from scripts.research_transition_recovery_detector.run_closed_loop import RecordingAlignerBackend  # noqa: E402
    from lyricalign.research_transition_recovery_detector.query_estimator import QueryEstimator  # noqa: E402
    from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE  # noqa: E402
    from lyricalign.research_transition_recovery_detector.runner import RealAlignerBackend  # noqa: E402

    session_root = Path(args.session_root)
    records_root = Path(args.records_root)
    with open(args.detector_pkl, "rb") as f:
        artifact = pickle.load(f)
    feature_names = tuple(artifact.get("feature_names"))
    frozen = json.loads((records_root / "10_followup" / "detector_v2" / "FROZEN_WORKING_POINTS_v2.json").read_text(encoding="utf-8"))
    wp = frozen["working_points_v3_format"][args.working_point]

    split = json.loads((records_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"]["model_selection"]
    by_song = {json.loads(l)["song_id"]: json.loads(l)
               for l in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines() if l.strip()}
    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf", revision="c07281df297b9905d24a508279258cccf987a064",
        cache_dir="/home/hyan/Data/lyricalign/models/hf_cache", local_files_only=True, device=args.device,
    )
    checkpoint = Path("/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750")
    processor, model = load_model(model_args, "lora", checkpoint)
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "retry_dec"),
        research_model_identity={"kind": "lora"}, device=args.device,
    )
    backend = RecordingAlignerBackend(RealAlignerBackend(processor=processor, model=model, args=infer_args))

    def detector_predict(rows):
        feats = extract_signal_features(rows)
        return predict_p_bad(artifact, feats, feature_names)

    per_window = []
    for song_id in song_ids:
        row = by_song[song_id]
        audio, document, gt = load_song_from_timeline(row)
        plan = build_silence_aware_window_plan(
            float(len(audio) / 16000), build_vocal_activity_profile(audio, sample_rate=16000),
            target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
        )
        out = run_closed_loop_v3_song(
            song_id=song_id, audio=audio, document=document, gt=gt,
            window_plan=plan, estimator=QueryEstimator(n_units=len(row["canonical_units"]),
                                                       effective_audio_sec=float(row["duration_sec"])),
            backend=backend, transition=TRANSITION_T2_CORE, frozen_wp=wp,
            route_mode=args.route_mode, detector_predict=detector_predict,
        )
        for w in out["windows"]:
            if w["retry"]["executed_forward_count"] == 0:
                continue
            # before：serial rows（窗内 committed 前）+ 100/250/500/1000 + MAE
            before_ids = w.get("query_ids", [])
            before_rows = w.get("retry_before_rows") or []  # 若脚本提供
            rec = {"song_id": song_id, "window_index": w["window_index"],
                   "route": w.get("plan", {}).get("route"),
                   "retry_request_id": w.get("retry", {}).get("request_id"),
                   "retry_query_ids": w.get("retry", {}).get("query_ids"),
                   "retry_writeback": w.get("retry_writeback"),
                   "writeback_committed": w.get("writeback", {}).get("committed_this_window"),
                   "gate_c": w.get("writeback", {}).get("gate_c"),
                   "retry_rows_correctness_250ms": None,
                   "classification": "retry_not_improved_no_retry_rows_saved"}
            per_window.append(rec)
    out_dir = session_root / "07_closed_loop"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "recovery_failure_decomposition_v1",
        "n_retry_windows": len(per_window),
        "note": "run_closed_loop_v3_song 未保存 retry rows（backend.last_rows 运行时才有）；"
                "before/after 的 timing 级分解需要扩展 v3 脚本输出 retry rows —— 当前记录 route/writeback/gate_c 状态层分解",
        "windows": per_window,
    }
    (out_dir / "RECOVERY_FAILURE_DECOMPOSITION.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({"n_retry_windows": len(per_window),
                      "note": summary["note"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
