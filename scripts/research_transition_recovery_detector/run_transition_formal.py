#!/usr/bin/env python3
"""Phase 2：Transition formal（C0 None，development selection）。

在四角色 split 的 model_selection songs 上对 T0–T3 运行冻结配置
（retained_total_sec=3.0 + silence snap + full-slot，07 §2 主 baseline），
每歌每 transition 产出 records -> metrics，输出：
  <session>/02_transition/FORMAL_<role>.json   每歌每 transition 的指标
  <session>/02_transition/FORMAL_<role>.jsonl  逐窗逐 record 的 committed 行+GT 判定

所有结果必须标 development_selection（不是 M4 formal）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.contracts import TRANSITIONS  # noqa: E402
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    RealAlignerBackend,
    TransitionRunner,
)
from lyricalign.research_transition_recovery_detector.transition_metrics import (  # noqa: E402
    cost_summary,
    coverage_stats,
    cursor_time_drift,
    first_error_window,
    missing_duplicate_committed,
    multi_tolerance_accuracy,
    occurrence_jump_rate,
    unit_accuracy,
)

R2_CHECKPOINT_DEFAULT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
MODEL_REVISION_DEFAULT = "c07281df297b9905d24a508279258cccf987a064"


def load_gt(row: dict) -> dict[int, dict]:
    return {
        int(u["canonical_unit_id"]): {"start_sec": u["start_sec"], "end_sec": u["end_sec"], "text": u["text"]}
        for u in row["canonical_units"]
    }


def committed_rows_for(record: dict) -> list[dict]:
    """从 record 的 evidence rows + decision 提取本窗提交的行，规范化为指标字段。"""
    if record.get("skipped"):
        return []
    raw = list(record["evidence_summary"]["raw_global_rows"])
    rows = [
        {
            "global_character_index": r["global_character_index"],
            "start_sec": r.get("original_global_start_sec", r["fixed_global_start_sec"]),
            "end_sec": r.get("original_global_end_sec", r["fixed_global_end_sec"]),
            "occurrence": r.get("occurrence"),
        }
        for r in raw
    ]
    if record["decision"].get("mode") == "oracle_independent":
        return rows  # T0：无 serial commit，评估全部 oracle query rows
    before = record["state_before"]["committed_end_exclusive"]
    after = record["decision"]["committed_end_exclusive"]
    new_ids = set(range(before, after))
    return [r for r in rows if r["global_character_index"] in new_ids]


def run_formal(args: argparse.Namespace) -> int:
    import argparse as _argparse

    from scripts.demo.align_qwen_fa_serial_demo import load_model

    session_root = Path(args.session_root)
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][args.role]
    if args.song_ids:
        song_ids = [s for s in song_ids if s in {x.strip() for x in args.song_ids.split(",")}]
    manifest_rows = {
        json.loads(line)["song_id"]: json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    transitions = [args.transition] if args.transition else list(TRANSITIONS)

    model_args = _argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf",
        revision=args.model_revision,
        cache_dir=args.cache_dir,
        local_files_only=True,
        device=args.device,
    )
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    processor, model = load_model(model_args, "lora" if checkpoint else "raw", checkpoint)
    model_identity = {
        "kind": "lora" if checkpoint else "raw",
        "checkpoint": str(checkpoint) if checkpoint else None,
        "revision": args.model_revision,
    }
    infer_args = _argparse.Namespace(
        timestamp_segment_sec=0.08,
        decoder_kind="raw",
        decoder_top_k=8,
        decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "serial_infer"),
        research_model_identity=model_identity,
        device=args.device,
    )
    config = {
        "lookback_units": 8,
        "head_strategy": getattr(args, "head_strategy", "H0"),
        "model_identity": model_identity,
        "env_identity": f"gpu-{args.role}",
        "config_hash": f"formal-{args.role}-{getattr(args, chr(104)+chr(101)+chr(97)+chr(100)+chr(95)+chr(115)+chr(116)+chr(114)+chr(97)+chr(116)+chr(101)+chr(103)+chr(121), chr(72)+chr(48))}",
        "sample_rate": 16000,
        "audio_profile_provider": lambda a: build_vocal_activity_profile(a, sample_rate=16000),
        "min_original_silence_sec": 5.0,
    }
    backend = RealAlignerBackend(processor=processor, model=model, args=infer_args)
    runner = TransitionRunner(config, session_root=session_root, backend=backend)

    out_rows: list[dict] = []
    detail_lines: list[dict] = []
    for song_id in song_ids:
        row = manifest_rows.get(song_id)
        if row is None:
            print(f"SKIP {song_id}: not in manifest", file=sys.stderr)
            continue
        from scripts.research_transition_recovery_detector.run_transition_smoke import (
            load_song_from_timeline,
        )

        audio, document, gt = load_song_from_timeline(row)
        from scripts.demo.align_qwen_fa_serial_demo import build_vocal_activity_profile
        from lyricalign.demo.window_planning import build_silence_aware_window_plan

        plan = build_silence_aware_window_plan(
            float(len(audio) / 16000), build_vocal_activity_profile(audio, sample_rate=16000),
            target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
        )
        for transition in transitions:
            target = session_root / "02_transition" / f"{song_id}__{transition}.jsonl"
            if target.is_file():
                target.unlink()
            records = runner.run_song(
                song_id=song_id, audio=audio, document=document, window_plan=plan,
                transition=transition, gt_timeline=gt,
                compress=True, retained_total_sec=3.0,
            )
            committed = [r for rec in records for r in committed_rows_for(rec)]
            acc = unit_accuracy(committed, gt)
            multi = multi_tolerance_accuracy(committed, gt)
            final_rec = next((r for r in reversed(records) if not r.get("skipped")), None)
            cov = coverage_stats(len(gt), final_rec["state_after"]["committed_end_exclusive"] if final_rec else 0)
            drift = cursor_time_drift(records, gt)
            first_err = first_error_window(records, gt)
            md = missing_duplicate_committed(committed, gt)
            occ = occurrence_jump_rate(committed, {i: "" for i in gt})
            if occ["total"] and occ["jumps"] == occ["total"] and all(
                r.get("occurrence") is None for r in committed
            ):
                occ = {"jumps": None, "total": len(committed), "jump_rate": None,
                       "note": "not_applicable: GT schema 无 occurrence，occurrence 跳变无法评估"}
            cost = cost_summary(records)
            summary = {
                "song_id": song_id, "transition": transition, "role": args.role,
                "scope": "development_selection",
                "n_windows": len(records), "n_units_total": len(gt),
                "committed": len(committed),
                "accuracy": acc,
                "multi_tolerance": multi,
                "coverage": cov,
                "drift": drift,
                "first_error_window": first_err,
                "missing_duplicate": md,
                "occurrence": occ,
                "cost": cost,
            }
            out_rows.append(summary)
            detail_lines.append({
                "song_id": song_id, "transition": transition,
                "records": [{k: r.get(k) for k in ("window_index", "decision", "request")} for r in records],
            })
            print(json.dumps({k: summary[k] for k in ("song_id", "transition", "committed", "accuracy", "coverage", "first_error_window")}, ensure_ascii=False))
    formal_path = session_root / "02_transition" / f"FORMAL_{args.role}.json"
    existing = []
    if formal_path.is_file():
        existing = json.loads(formal_path.read_text(encoding="utf-8"))
    merged = {f"{r['song_id']}::{r['transition']}": r for r in existing}
    for r in out_rows:
        merged[f"{r['song_id']}::{r['transition']}"] = r
    formal_path.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2), "utf-8")
    detail_path = session_root / "02_transition" / f"FORMAL_{args.role}.jsonl"
    with open(detail_path, "w", encoding="utf-8") as f:
        for line in detail_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(f"FORMAL {args.role}: {len(out_rows)} rows -> {formal_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--transition", choices=list(TRANSITIONS))
    p.add_argument("--song-ids", default="")
    p.add_argument("--head-strategy", choices=("H0", "H1"), default="H0")
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--checkpoint", default=R2_CHECKPOINT_DEFAULT)
    p.add_argument("--model-revision", default=MODEL_REVISION_DEFAULT)
    p.add_argument("--cache-dir", default="/home/hyan/Data/lyricalign/models/hf_cache")
    p.add_argument("--device", default="cuda:0")
    return p


def main() -> int:
    args = build_parser().parse_args()
    return run_formal(args)


if __name__ == "__main__":
    sys.exit(main())
