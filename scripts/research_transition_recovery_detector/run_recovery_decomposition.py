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
    feature_names = tuple(artifact.get("feature_names") or artifact.get("features_used") or [])
    frozen_v3 = records_root.parent / "research_transition_recovery_detector_20260809_second_supplement" / "06_detector" / "FROZEN_WORKING_POINTS_v3.json"
    frozen_path = frozen_v3 if frozen_v3.is_file() else (records_root / "10_followup" / "detector_v2" / "FROZEN_WORKING_POINTS_v2.json")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    wps = frozen.get("working_points_v3_format") or frozen.get("working_points_v3_format")
    wp = wps[args.working_point]

    split = json.loads((records_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"]["model_selection"]
    by_song = {json.loads(l)["song_id"]: json.loads(l)
               for l in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines() if l.strip()}
    from lyricalign.research_transition_recovery_detector.real_gt import load_real_gt  # noqa: E402
    real_ann = Path("/home/hyan/Data/lyricalign/derived/20260723_m4singer_overlay_slur_time_v1/prepare/m4singer_character_annotations.jsonl")
    real_gt = load_real_gt(real_ann, Path(args.timeline_manifest)) if real_ann.is_file() else {}
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
        # v3 detector 特征含 context interval gap；单行/短 retry rows 的 gap 可能 None，
        # predict_p_bad 会丢弃含 None 行导致空预测。用 0 填充缺失值保持行对齐。
        filled = [{nm: (f.get(nm) if f.get(nm) is not None else 0.0) for nm in feature_names}
                  for f in feats]
        return predict_p_bad(artifact, filled, feature_names)

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
            # ---- before：serial 提交行的 250ms correctness ----
            gt_units = {int(u["canonical_unit_id"]): float(u["start_sec"])
                        for u in row["canonical_units"]}
            if real_gt.get(song_id):
                gt_units = {cid: float(m["start_sec"]) for cid, m in real_gt[song_id].items()}
            serial_committed = list(w.get("writeback", {}).get("committed_this_window") or [])
            serial_rows = {int(r["canonical_id"]): float(r["start_sec"])
                           for r in w.get("serial_rows_timing") or []}
            before_errs = []
            for cid in serial_committed:
                s = serial_rows.get(int(cid))
                g = gt_units.get(int(cid))
                if s is not None and g is not None:
                    before_errs.append(abs(s - g))
            before_250 = (sum(1 for e in before_errs if e <= 0.25) / max(len(before_errs), 1)
                          if before_errs else None)
            before_mae = (sum(before_errs) / max(len(before_errs), 1) if before_errs else None)

            # ---- after：retry attempt 行的 250ms correctness（与 writeback 解耦）----
            retry_rows = {int(r["canonical_id"]): float(r["start_sec"])
                          for r in w.get("retry_rows_timing") or []}
            retry_query_ids = [int(x) for x in (w.get("retry", {}).get("query_ids") or [])]
            retry_commit_ids = list(w.get("retry_writeback", {}).get("commit_ids") or [])
            after_errs = []
            for cid in (retry_query_ids or retry_commit_ids):
                s = retry_rows.get(int(cid))
                g = gt_units.get(int(cid))
                if s is not None and g is not None:
                    after_errs.append(abs(s - g))
            if not after_errs:
                after_errs = list(before_errs)
            after_250 = (sum(1 for e in after_errs if e <= 0.25) / max(len(after_errs), 1)
                         if after_errs else None)
            after_mae = (sum(after_errs) / max(len(after_errs), 1) if after_errs else None)

            # ---- 同集合对比：before 也限制在 retry attempt span 上，避免 population mismatch ----
            # before（serial committed）与 after（retry query span）可能覆盖不同字符集合；
            # 取交集做 apples-to-apples 对比。serial_rows 无 GT 的行跳过。
            overlap_ids = sorted(set(serial_committed) & set(retry_query_ids or retry_commit_ids))
            before_ovl = [abs(serial_rows.get(int(c)) - gt_units[int(c)])
                          for c in overlap_ids
                          if serial_rows.get(int(c)) is not None and int(c) in gt_units]
            after_ovl = [abs(retry_rows.get(int(c)) - gt_units[int(c)])
                         for c in overlap_ids
                         if retry_rows.get(int(c)) is not None and int(c) in gt_units]
            if before_ovl and after_ovl:
                before_250 = sum(1 for e in before_ovl if e <= 0.25) / max(len(before_ovl), 1)
                after_250 = sum(1 for e in after_ovl if e <= 0.25) / max(len(after_ovl), 1)
                before_mae = sum(before_ovl) / len(before_ovl)
                after_mae = sum(after_ovl) / len(after_ovl)

            # ---- 分类（冻结标准）：250ms coverage +10pp 或 MAE 相对下降 20% ----
            # improved/worsened 基于 retry attempt 质量（与 writeback 解耦）；
            # accept/block 由 retry_commit_ids 是否非空区分。
            classification = "retry_not_improved"
            if before_250 is not None and after_250 is not None:
                cov_improve = after_250 - before_250
                mae_improve = None
                if before_mae and after_mae and before_mae > 0:
                    mae_improve = (before_mae - after_mae) / before_mae
                improved = cov_improve >= 0.10 or (mae_improve is not None and mae_improve >= 0.20)
                worsened = cov_improve <= -0.10 or (mae_improve is not None and mae_improve <= -0.20)
                if worsened:
                    classification = "retry_worsened"
                elif improved:
                    retry_commits = list(w.get("retry_writeback", {}).get("commit_ids") or [])
                    if len(retry_commits) > 0:
                        classification = "retry_improved_detector_accept"
                    else:
                        classification = "retry_improved_detector_block"

            rec = {"song_id": song_id, "window_index": w["window_index"],
                   "route": w.get("plan", {}).get("route"),
                   "retry_request_id": w.get("retry", {}).get("request_id"),
                   "retry_query_ids": w.get("retry", {}).get("query_ids"),
                   "retry_writeback": w.get("retry_writeback"),
                   "writeback_committed": w.get("writeback", {}).get("committed_this_window"),
                   "gate_c": w.get("writeback", {}).get("gate_c"),
                   "before_250ms": round(before_250, 4) if before_250 is not None else None,
                   "after_250ms": round(after_250, 4) if after_250 is not None else None,
                   "before_mae": round(before_mae, 4) if before_mae is not None else None,
                   "after_mae": round(after_mae, 4) if after_mae is not None else None,
                   "n_serial_committed": len(serial_committed),
                   "n_retry_committed": len(retry_commit_ids),
                   "retry_writeback_commits": list(w.get("retry_writeback", {}).get("commit_ids") or []),
                   "gate_c_ok": bool(w.get("writeback", {}).get("gate_c")),
                   "classification": classification}
            per_window.append(rec)
    out_dir = session_root / "07_closed_loop"
    out_dir.mkdir(parents=True, exist_ok=True)
    from collections import Counter
    summary = {
        "schema_version": "recovery_failure_decomposition_v2",
        "n_retry_windows": len(per_window),
        "classification": dict(Counter(r["classification"] for r in per_window)),
        "note": "before=serial committed rows 250ms correct coverage; after=retry writeback rows; "
                "improved=+10pp cov or -20% MAE; accept iff retry commit_ids nonempty",
        "windows": per_window,
    }
    (out_dir / "RECOVERY_FAILURE_DECOMPOSITION.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({"n_retry_windows": len(per_window),
                      "classification": summary["classification"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
