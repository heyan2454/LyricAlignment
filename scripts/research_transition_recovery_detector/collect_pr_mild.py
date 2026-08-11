#!/usr/bin/env python3
"""11 计划 Stage 4：PR 轻度干预补集（low/medium risk episodes）。

轻度 spec（cursor ±1/±2、time ±0.25/±0.5s、mild boundary），9 首 model_selection，
continuation 语义（不重放窗 0），输出 PR_EPISODES.jsonl（含 risk 标签）与 PR_TARGET_AUDIT 更新。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE, TransitionState  # noqa: E402
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    RealAlignerBackend,
    TransitionRunner,
)
from lyricalign.research_transition_recovery_detector import gt_provenance  # noqa: E402

R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"
TOLERANCE = 0.25  # PR 用 250ms 标签


def mild_specs(n_units: int, sec_per_unit: float, base_committed: int, base_prev_end: float):
    """轻度干预：cursor ±1/±2 units、time ±0.25/±0.5s、mild boundary。"""
    out = []
    for delta in (1, 2):
        for sign in (+1, -1):
            new_end = max(0, min(n_units, base_committed + sign * delta))
            if new_end != base_committed:
                out.append(("cursor_mild", {"delta_units": sign * delta, "committed_end": new_end}))
    for ds in (0.25, 0.5):
        for sign in (+1, -1):
            out.append(("time_mild", {"delta_sec": sign * ds,
                                      "prev_end": max(0.0, base_prev_end + sign * ds)}))
    out.append(("boundary_mild", {"tail_units": 2}))
    return out


def risk_class(recovery: str) -> str:
    return {"self_recover": "low", "slow_recover": "medium"}.get(recovery, "high")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="model_selection")
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
    corrected = Path("runs/research_transition_recovery_detector_20260808_corrected")
    (session_root / "03_propagation").mkdir(parents=True, exist_ok=True)
    split = json.loads((corrected / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][args.role]
    by_song = {json.loads(l)["song_id"]: json.loads(l)
               for l in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines() if l.strip()}
    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf", revision=args.model_revision,
        cache_dir=args.cache_dir, local_files_only=True, device=args.device,
    )
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "pr_mild"),
        research_model_identity={"kind": "lora" if checkpoint else "raw"}, device=args.device,
    )
    config = {
        "lookback_units": 8, "head_strategy": "H0",
        "model_identity": {"kind": "lora" if checkpoint else "raw"},
        "env_identity": "gpu-pr-mild", "config_hash": "pr-mild-v1", "sample_rate": 16000,
        "audio_profile_provider": lambda a: build_vocal_activity_profile(a, sample_rate=16000),
        "min_original_silence_sec": 5.0,
    }
    backend = RealAlignerBackend(processor=processor, model=model, args=infer_args)
    runner = TransitionRunner(config, session_root=session_root, backend=backend)
    out_eps = []
    for song_id in song_ids:
        row = by_song[song_id]
        audio, document, gt = load_song_from_timeline(row)
        n_units = len(row["canonical_units"])
        sec_per_unit = float(row["duration_sec"]) / max(n_units, 1)
        plan = build_silence_aware_window_plan(
            float(len(audio) / 16000), build_vocal_activity_profile(audio, sample_rate=16000),
            target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
        )
        clean = runner.run_song(song_id=f"{song_id}::clean", audio=audio, document=document,
                                window_plan=plan, transition=TRANSITION_T2_CORE, gt_timeline=gt,
                                compress=True, retained_total_sec=3.0)
        clean_followup_wrong = []
        for rec in clean:
            before = rec["state_before"]["committed_end_exclusive"]
            after = rec["decision"]["committed_end_exclusive"]
            clean_followup_wrong.append(sum(
                1 for r in rec["evidence_summary"]["raw_global_rows"]
                if before <= int(r["global_character_index"]) < after
                and abs(float(r.get("original_global_start_sec", r["fixed_global_start_sec"]))
                        - gt[int(r["global_character_index"])]["start_sec"]) > TOLERANCE))
        base_state = TransitionState(**clean[0]["state_after"])
        obs0 = {
            int(r["global_character_index"]): {
                "global_character_index": int(r["global_character_index"]),
                "start_sec": float(r["fixed_global_start_sec"]),
                "end_sec": float(r["fixed_global_end_sec"]),
                "source": "raw"}
            for r in clean[0]["evidence_summary"]["raw_global_rows"]
        }
        for fam, spec in mild_specs(n_units, sec_per_unit, base_state.committed_end_exclusive,
                                    base_state.previous_committed_end_model_sec):
            if fam == "cursor_mild":
                corrupted = base_state.derive(
                    committed_end_exclusive=spec["committed_end"],
                    committed_ids=tuple(range(spec["committed_end"])),
                    next_input_cursor=min(base_state.next_input_cursor, spec["committed_end"]))
            elif fam == "time_mild":
                corrupted = base_state.derive(previous_committed_end_model_sec=spec["prev_end"])
            else:
                corrupted = base_state.derive(
                    occurrence_by_id=tuple(
                        (i, "jump" if i >= max(0, base_state.committed_end_exclusive - 2) else o)
                        for i, o in base_state.occurrence_by_id))
            records = runner.run_song(
                song_id=f"{song_id}::mild::{fam}::{json.dumps(spec, sort_keys=True)}",
                audio=audio, document=document, window_plan=plan,
                transition=TRANSITION_T2_CORE, gt_timeline=gt,
                compress=True, retained_total_sec=3.0,
                starting_state=corrupted, observations=obs0)
            followup = []
            for rec in records:
                before = rec["state_before"]["committed_end_exclusive"]
                after = rec["decision"]["committed_end_exclusive"]
                wrong = sum(1 for r in rec["evidence_summary"]["raw_global_rows"]
                            if before <= int(r["global_character_index"]) < after
                            and abs(float(r.get("original_global_start_sec", r["fixed_global_start_sec"]))
                                    - gt[int(r["global_character_index"])]["start_sec"]) > TOLERANCE)
                followup.append({"window_index": rec["window_index"], "new_wrong": wrong})
            wrongs = [w["new_wrong"] for w in followup]
            # 相对 clean baseline 判定（250ms 下模型本身误差大，绝对 wrong>0 不能代表传播）
            excess = [max(0, w - (clean_followup_wrong[rec_i] if rec_i < len(clean_followup_wrong) else 0))
                      for rec_i, w in enumerate(wrongs)]
            if all(e == 0 for e in excess):
                recovery = "self_recover"          # 干预未增加错误
            elif sum(1 for e in excess[:3] if e == 0) >= 1 or sum(excess) <= 2:
                recovery = "slow_recover"          # 有限额外错误，2-3 窗内恢复
            elif any(e >= 5 for e in excess[1:]) if len(excess) > 1 else False:
                recovery = "amplifying"            # 显著放大
            else:
                recovery = "persistent" if sum(excess) > 2 else "self_recover"
            out_eps.append({
                "episode_id": f"mild_{song_id}__{fam}__{json.dumps(spec, sort_keys=True)}",
                "source_song_id": song_id, "family": fam, "intervention": {"family": fam, "spec": spec},
                "continue_from_window_index": 1, "followup_windows": followup,
                "recovery_class": recovery, "risk": risk_class(recovery),
                "no_effect_attempt": all(w == 0 for w in followup),
                "provenance": gt_provenance.synthetic_uniform_timeline_provenance(),
            })
        print(json.dumps({"song": song_id, "mild_episodes": sum(1 for e in out_eps if e["source_song_id"] == song_id)}))
    gt_provenance.warn_synthetic_gt()
    with open(session_root / "03_propagation" / "PR_EPISODES.jsonl", "w", encoding="utf-8") as f:
        for e in out_eps:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    from collections import Counter

    print(json.dumps({"n_mild": len(out_eps), "by_risk": dict(Counter(e["risk"] for e in out_eps)),
                      "by_family": dict(Counter(e["family"] for e in out_eps))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
