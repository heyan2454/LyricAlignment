#!/usr/bin/env python3
"""Phase 3：canonical state corruption + model-native forced commit 传播收集（GPU）。

机制（07 §2 §7 / 02 §6-7）：
- corruption：直接修改 canonical transition state（cursor/time/coupled/occurrence/boundary），
  从 corrupted state 出发在 T2 上真实 forward 2-5 窗，记录 recovery class。
- forced：从已有 T2 轨迹中取模型自己产生的 wrong committed 行，构造"已强制提交"状态后继续。

每 episode 保存：clean 起点、错误 state delta、follow-up 窗记录、recovery class。
输出追加 <session>/03_propagation/EPISODES.jsonl + 更新 ATTEMPT_DENOMINATORS.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.contracts import (  # noqa: E402
    TRANSITION_T2_CORE,
    TransitionState,
)
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    RealAlignerBackend,
    TransitionRunner,
)

R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"
TOLERANCE = 0.32


def corrupted_states(
    state: TransitionState, *, n_units: int, sec_per_unit: float,
) -> list[tuple[str, dict, TransitionState]]:
    """返回 (family, 强度描述, corrupted state) 列表。

    07 §7 families：
    1. lyric cursor ahead/behind（±10/20/40 units，clamp 到 [0, n_units]）
    2. time cursor ahead/behind（±1/3/6/12 s）
    3. lyric+time coupled 自洽错（cursor ahead 且 previous_end 同步前移）
    4. wrong occurrence（首个 committed id 的 occurrence 改为 "2"）
    5. partial boundary/tail corruption（committed_ids 尾段 occurrence 标注异常）
    """
    families: list[tuple[str, dict, TransitionState]] = []
    base = state
    for delta in (10, 20, 40):
        for sign in (+1, -1):
            new_end = max(0, min(n_units, base.committed_end_exclusive + sign * delta))
            if new_end == base.committed_end_exclusive:
                continue
            fam = "cursor_ahead" if sign > 0 else "cursor_behind"
            corrupted = base.derive(
                committed_end_exclusive=new_end,
                committed_ids=tuple(range(new_end)),
                next_input_cursor=min(base.next_input_cursor, new_end),
            )
            families.append((fam, {"delta_units": sign * delta, "committed_end": new_end}, corrupted))
    for delta_s in (1.0, 3.0, 6.0, 12.0):
        for sign in (+1, -1):
            fam = "time_ahead" if sign > 0 else "time_behind"
            corrupted = base.derive(
                previous_committed_end_model_sec=max(0.0, base.previous_committed_end_model_sec + sign * delta_s),
            )
            families.append((fam, {"delta_sec": sign * delta_s}, corrupted))
    for delta in (20, 40):
        new_end = max(0, min(n_units, base.committed_end_exclusive + delta))
        coupled = base.derive(
            committed_end_exclusive=new_end,
            committed_ids=tuple(range(new_end)),
            next_input_cursor=min(base.next_input_cursor, new_end),
            previous_committed_end_model_sec=base.previous_committed_end_model_sec
            + delta * sec_per_unit,
        )
        families.append(("coupled_self_consistent", {"delta_units": delta}, coupled))
    wrong_occ = base.derive(
        occurrence_by_id=((0, "2"), *[(i, o) for i, o in base.occurrence_by_id if i != 0]),
    )
    families.append(("wrong_occurrence", {"id": 0, "occurrence": "2"}, wrong_occ))
    boundary = base.derive(
        occurrence_by_id=tuple(
            (i, "jump" if i >= max(0, base.committed_end_exclusive - 5) else o)
            for i, o in base.occurrence_by_id
        ),
    )
    families.append(("boundary_tail_corruption", {"tail_units": 5}, boundary))
    return families


def recovery_class(followup: list[dict], first_new_wrong: int) -> str:
    """02 §7 分类。followup 每窗含 new_committed/new_wrong。"""
    wrongs = [w["new_wrong"] for w in followup]
    if first_new_wrong > 10:
        return "occurrence_jump"
    if not wrongs or all(w == 0 for w in wrongs):
        return "self_recover"
    if len(wrongs) <= 3 and all(w == 0 for w in wrongs[1:]):
        return "slow_recover"
    if any(w > first_new_wrong for w in wrongs):
        return "amplifying"
    return "persistent"


def run(args: argparse.Namespace) -> int:
    import argparse as _argparse

    from scripts.demo.align_qwen_fa_serial_demo import (  # noqa: E402
        build_vocal_activity_profile,
        load_model,
    )
    from lyricalign.demo.window_planning import build_silence_aware_window_plan  # noqa: E402
    from scripts.research_transition_recovery_detector.run_transition_smoke import (  # noqa: E402
        load_song_from_timeline,
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
    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf",
        revision=args.model_revision,
        cache_dir=args.cache_dir,
        local_files_only=True,
        device=args.device,
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
        "lookback_units": 8,
        "model_identity": model_identity,
        "env_identity": "gpu-propagation",
        "config_hash": "propagation-v1",
        "sample_rate": 16000,
        "audio_profile_provider": lambda a: build_vocal_activity_profile(a, sample_rate=16000),
        "min_original_silence_sec": 5.0,
    }
    backend = RealAlignerBackend(processor=processor, model=model, args=infer_args)
    runner = TransitionRunner(config, session_root=session_root, backend=backend)

    (session_root / "03_propagation").mkdir(parents=True, exist_ok=True)
    episodes_path = session_root / "03_propagation" / "EPISODES.jsonl"
    existing = []
    if episodes_path.is_file():
        existing = [json.loads(l) for l in episodes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_episode = {e["episode_id"]: e for e in existing}
    new_episodes = 0
    song_counts: dict[str, int] = {}
    for song_id in song_ids:
        row = by_song[song_id]
        audio, document, gt = load_song_from_timeline(row)
        n_units = len(row["canonical_units"])
        sec_per_unit = float(row["duration_sec"]) / max(n_units, 1)
        duration = float(len(audio) / 16000)
        plan = build_silence_aware_window_plan(
            duration, build_vocal_activity_profile(audio, sample_rate=16000),
            target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
        )
        # clean 起点：正常 T2 首窗后的 state（作为 corruption 的 base）；
        # continuation 语义（09 P0.2）：corrupted.window_index=k+1 时只执行 windows[k+1:]，
        # 并恢复前序 observations，绝不重放已执行窗口。
        clean_records = runner.run_song(
            song_id=f"{song_id}::clean", audio=audio, document=document, window_plan=plan,
            transition=TRANSITION_T2_CORE, gt_timeline=gt, compress=True, retained_total_sec=3.0,
        )
        # 只恢复至窗口 k 的前序观察（09 review P1：不得把未来窗观察注入 corruption 起点）
        clean_observations = {
            int(r["global_character_index"]): obs
            for rec in clean_records[:1]
            for r in rec.get("evidence_summary", {}).get("raw_global_rows", [])
            for obs in [{
                "global_character_index": int(r["global_character_index"]),
                "start_sec": float(r["fixed_global_start_sec"]),
                "end_sec": float(r["fixed_global_end_sec"]),
                "source": "raw",
            }]
        }
        base_state = TransitionState(**clean_records[0]["state_after"])
        for family, spec, corrupted in corrupted_states(
            base_state, n_units=n_units, sec_per_unit=sec_per_unit,
        ):
            eid = f"corr_{song_id}__{family}__{json.dumps(spec, sort_keys=True)}"
            if eid in by_episode:
                continue
            records = runner.run_song(
                song_id=f"{song_id}::corr::{family}", audio=audio, document=document,
                window_plan=plan, transition=TRANSITION_T2_CORE, gt_timeline=gt,
                compress=True, retained_total_sec=3.0,
                starting_state=corrupted,
                observations=clean_observations,
            )
            followup = []
            first_new_wrong = 0
            for rec in records:
                before = rec["state_before"]["committed_end_exclusive"]
                after = rec["decision"]["committed_end_exclusive"]
                new_rows = [
                    r for r in rec["evidence_summary"]["raw_global_rows"]
                    if before <= r["global_character_index"] < after
                ]
                wrong = sum(
                    1 for r in new_rows
                    if abs(float(r.get("original_global_start_sec", r["fixed_global_start_sec"]))
                           - gt[r["global_character_index"]]["start_sec"]) > TOLERANCE
                )
                followup.append({"window_index": rec["window_index"], "new_committed": len(new_rows), "new_wrong": wrong})
                if not first_new_wrong:
                    first_new_wrong = wrong
            episode = {
                "episode_id": eid, "family": family,
                "source": "canonical_state_corruption",
                "source_song_id": song_id,
                "transition_id": TRANSITION_T2_CORE,
                "natural": False,
                "window_index_before_intervention": corrupted.window_index - 1,
                "continue_from_window_index": corrupted.window_index,
                "state_before": corrupted.__dict__,
                "state_after_clean_window": base_state.__dict__,
                "intervention": {"family": family, "spec": spec},
                "provenance": {
                    "clean_run_song_id": f"{song_id}::clean",
                    "query_estimator_version": "units_per_sec_v2",
                    "clean_observations_restored": True,
                    "continuation": True,
                },
                "corruption_spec": spec,
                "state_delta": {"committed_end": corrupted.committed_end_exclusive},
                "followup_windows": followup[:5],
                "recovery_class": recovery_class(followup[:5], first_new_wrong),
                "no_effect_attempt": all(w["new_committed"] == 0 for w in followup[:2]),
            }
            with open(episodes_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(episode, ensure_ascii=False) + "\n")
            by_episode[eid] = episode
            new_episodes += 1
            song_counts[song_id] = song_counts.get(song_id, 0) + 1
            print(json.dumps({"episode_id": eid, "family": family, "recovery": episode["recovery_class"]}))
    denom = {
        "songs_analyzed": len(song_ids),
        "corruption_episodes_new": new_episodes,
        "per_song_episodes": song_counts,
        "max_single_song_fraction": round(max(song_counts.values(), default=0) / max(new_episodes, 1), 3),
        "family_budget": 64,
        "note": "corruption episodes（continuation 语义，09 P2）；单歌占比上限 25%，source-song 下限 8",
        "gate_p": "pending_corrected_transition",
        "count_rejected_before_commit_as_propagated": False,
    }
    (session_root / "03_propagation" / "ATTEMPT_DENOMINATORS.json").write_text(
        json.dumps(denom, ensure_ascii=False, indent=2), "utf-8",
    )
    print(json.dumps(denom, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--song-ids", default="")
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--checkpoint", default=R2_CHECKPOINT_DEFAULT)
    p.add_argument("--model-revision", default=MODEL_REVISION_DEFAULT)
    p.add_argument("--cache-dir", default="/home/hyan/Data/lyricalign/models/hf_cache")
    p.add_argument("--device", default="cuda:0")
    return p


def main() -> int:
    args = build_parser().parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
