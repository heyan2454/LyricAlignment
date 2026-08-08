#!/usr/bin/env python3
"""11 计划 Stage 2：evidence v3 collector（一次 forward 存 H/R/O/full posterior）。

对 detector_train/model_selection/threshold_validation 的 T2 轨迹重跑
（infer_slice 带 research_evidence_config），聚合 evidence 并生成：
  evidence_hidden.jsonl / evidence_posterior.jsonl / evidence_trajectory.jsonl
  SIGNAL_COVERAGE_AUDIT.json / EVIDENCE_SCHEMA_v3.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE  # noqa: E402
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    RealAlignerBackend,
    TransitionRunner,
)

R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"
EVIDENCE_CONFIG = {"hidden_layers": [-4, -1], "save_full_posterior": True}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="detector_train")
    p.add_argument("--song-ids", default="")
    p.add_argument("--checkpoint", default=R2_CHECKPOINT_DEFAULT)
    p.add_argument("--model-revision", default=MODEL_REVISION_DEFAULT)
    p.add_argument("--cache-dir", default="/home/hyan/Data/lyricalign/models/hf_cache")
    p.add_argument("--device", default="cuda:0")
    args = p.parse_args()

    import argparse as _argparse

    from scripts.demo.align_qwen_fa_serial_demo import build_vocal_activity_profile, load_model  # noqa: E402
    from lyricalign.demo.window_planning import build_silence_aware_window_plan  # noqa: E402
    from scripts.research_transition_recovery_detector.run_transition_smoke import load_song_from_timeline  # noqa: E402

    session_root = Path(args.session_root)
    (session_root / "06_detector").mkdir(parents=True, exist_ok=True)
    split = json.loads((session_root / "00_meta" / "RESOLVED_CONTRACT.json").read_text(encoding="utf-8"))
    # split 数据来自 corrected session
    corrected = Path("runs/research_transition_recovery_detector_20260808_corrected")
    data_split = json.loads((corrected / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = data_split["roles"][args.role]
    if args.song_ids:
        song_ids = [s for s in song_ids if s in {x.strip() for x in args.song_ids.split(",")}]
    by_song = {
        json.loads(line)["song_id"]: json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf", revision=args.model_revision,
        cache_dir=args.cache_dir, local_files_only=True, device=args.device,
    )
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "serial_infer_v3"),
        research_model_identity={"kind": "lora" if checkpoint else "raw", "evidence_v3": True},
        device=args.device, research_evidence_config=EVIDENCE_CONFIG,
    )
    config = {
        "lookback_units": 8, "head_strategy": "H0",
        "model_identity": {"kind": "lora" if checkpoint else "raw", "evidence_v3": True},
        "env_identity": "gpu-evidence-v3",
        "config_hash": f"evidence-v3-{args.role}",
        "sample_rate": 16000,
        "audio_profile_provider": lambda a: build_vocal_activity_profile(a, sample_rate=16000),
        "min_original_silence_sec": 5.0,
    }
    backend = RealAlignerBackend(processor=processor, model=model, args=infer_args)
    runner = TransitionRunner(config, session_root=session_root, backend=backend)

    out_dir = session_root / "06_detector"
    hidden_rows = []
    posterior_rows = []
    traj_rows = []
    n_requests = 0
    n_hidden = 0
    n_posterior = 0
    for song_id in song_ids:
        row = by_song.get(song_id)
        if row is None:
            continue
        audio, document, gt = load_song_from_timeline(row)
        duration = float(len(audio) / 16000)
        plan = build_silence_aware_window_plan(
            duration, build_vocal_activity_profile(audio, sample_rate=16000),
            target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
        )
        records = runner.run_song(
            song_id=song_id, audio=audio, document=document, window_plan=plan,
            transition=TRANSITION_T2_CORE, gt_timeline=gt,
            compress=True, retained_total_sec=3.0,
        )
        for rec in records:
            n_requests += 1
            ev = runner.last_evidence or {}
            if song_id == "always_online" and rec["window_index"] == 0:
                print("DEBUG ev:", json.dumps({k: list(v.keys()) if isinstance(v, dict) else v for k, v in ev.items()})[:200])
            req = rec["request"]
            qids = req["query_canonical_ids"]
            if ev.get("hidden"):
                hidden_rows.append({
                    "song_id": song_id, "window_index": rec["window_index"],
                    "request_id": req["request_id"], "n_units": len(qids),
                    "layers": ev["hidden"]["layers"], "dim": ev["hidden"]["dim"],
                    "n_slots": ev["hidden"].get("n_slots"),
                    "vector_paths": ev["hidden"].get("vector_paths"),
                    "schema": ev["hidden"]["schema"],
                })
                n_hidden += 1
            if ev.get("full_posterior"):
                posterior_rows.append({
                    "song_id": song_id, "window_index": rec["window_index"],
                    "request_id": req["request_id"], "n_units": len(qids),
                    "n_slots": ev["full_posterior"]["n_slots"],
                    "n_classes": ev["full_posterior"]["n_classes"],
                    "path": ev["full_posterior"].get("path"),
                    "schema": ev["full_posterior"]["schema"],
                })
                n_posterior += 1
        # trajectory evidence：committed 行的序列特征（velocity/acceleration/run）由 detector_features 计算
        committed = []
        for rec in records:
            before = rec["state_before"]["committed_end_exclusive"]
            after = rec["decision"]["committed_end_exclusive"]
            committed.extend(
                (int(r["global_character_index"]), float(r["fixed_global_start_sec"]))
                for r in rec["evidence_summary"]["raw_global_rows"]
                if before <= int(r["global_character_index"]) < after
            )
        committed.sort()
        for i in range(1, len(committed)):
            prev_id, prev_t = committed[i - 1]
            cid, t = committed[i]
            traj_rows.append({
                "song_id": song_id, "canonical_id": cid,
                "interval_sec": round(t - prev_t, 4) if t >= prev_t else None,
                "velocity_flag": "inversion" if t < prev_t else "ok",
            })
        print(json.dumps({"song": song_id, "requests": len(records), "hidden": n_hidden,
                          "posterior": n_posterior}))
    # 落盘（按 role 分文件，避免多次运行互相覆盖）
    with open(out_dir / f"evidence_hidden_{args.role}.jsonl", "w") as f:
        for r in hidden_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / f"evidence_posterior_{args.role}.jsonl", "w") as f:
        for r in posterior_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / f"evidence_trajectory_{args.role}.jsonl", "w") as f:
        for r in traj_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    schema = {
        "schema_version": "evidence_v3",
        "per_request": {
            "rows": "raw/official timing rows", "hidden": "layers -4/-1 timestamp-token vectors float16",
            "full_posterior": "full slot softmax float16",
        },
        "hidden_layers": [-4, -1], "posterior_storage": "float16",
        "request_identity": "request_id+audio_sha+query ids", "view_identity": "window_index",
    }
    (out_dir / "EVIDENCE_SCHEMA_v3.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2))
    audit = {
        "schema_version": "signal_coverage_audit_v1",
        "requests_total": n_requests, "hidden_requests": n_hidden, "posterior_requests": n_posterior,
        "trajectory_rows": len(traj_rows),
        "H": {"denominator": n_requests, "covered": n_hidden,
              "coverage": round(n_hidden / max(n_requests, 1), 4),
              "missing_reason": None if n_hidden else "hidden 采集失败（查看日志）"},
        "P": {"denominator": n_requests, "covered": n_posterior,
              "coverage": round(n_posterior / max(n_requests, 1), 4), "missing_reason": None},
        "R": {"denominator": n_requests, "covered": n_requests, "coverage": 1.0},
        "O": {"denominator": n_requests, "covered": n_requests, "coverage": 1.0},
        "S": {"denominator": n_requests, "covered": n_requests, "coverage": 1.0},
    }
    (out_dir / "SIGNAL_COVERAGE_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    print(json.dumps(audit, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
