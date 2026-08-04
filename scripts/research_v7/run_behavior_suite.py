#!/usr/bin/env python3
"""阶段 B：run_behavior_suite —— 从 behavior_manifest 批量跑 alignment 行为用例。

对 manifest 每条（baseline/extra/missing/replace/no_match）构造 v7 AlignmentRequest，
支持 sparse-slot 骨架（slot mask），用可注入 executor 产出 EvidencePack 到 <out-root>/items。

用法：
  PYTHONPATH=src python scripts/research_v7/run_behavior_suite.py \
      --manifest <behavior_manifest.jsonl> --out-root runs/research_v7_align_behavior/run \
      --smoke                      # fake executor，纯 CPU 验证
  # 真模型：manifest 的 audio_path 必须指向存在的 vocal 文件。

每条 evidence identity 含 audio/text hash + mutation + mutation params，供 lineage/重放。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.attempt import run_request
from lyricalign.research_v7.requests import AlignmentRequest


def _fake_executor(_req: object):
    import random

    rnd = random.Random(0)

    def ex(request: AlignmentRequest):
        from lyricalign.research_v7.attempt import AlignmentAttempt

        n = len(request.text_units)
        rows = [{"global_character_index": i, "start_sec": i * 0.5, "end_sec": i * 0.5 + 0.4} for i in range(n)]
        fa = []
        if request.mutation_type == "no_match":
            fa = ["WRONG_REPEATED_SECTION"]
        elif request.mutation_type == "extra":
            fa = ["TAIL_COLLAPSE"]
        elif request.mutation_type == "missing":
            fa = ["GLOBAL_SHIFT"]
        return AlignmentAttempt(
            request=request, attempt_id=f"B-{request.item_id}-{request.mutation_type}",
            decoder_outputs={"official": {"rows": rows}, "raw": {"rows": rows}},
            cursor_after=float(n) * 0.5, committed=True, status="ok", fa_taxonomy=tuple(fa),
        )

    return ex


def hash_text(units):
    return hashlib.sha256("|".join(units).encode()).hexdigest()[:16]


def audio_range(duration_sec):
    return (0.0, float(duration_sec or 60.0))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--real", action="store_true", help="run frozen Qwen executor; requires manifest audio_path")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--model", default="Qwen3-ForcedAligner-0.6B-hf")
    p.add_argument("--checkpoint", default="r2-step-000750")
    p.add_argument("--checkpoint-path", help="local LoRA checkpoint directory; required with --real")
    p.add_argument("--model-dir")
    p.add_argument("--revision", default="main")
    p.add_argument("--resume", action="store_true", help="reuse only identity-identical evidence; reject mismatches")
    args = p.parse_args(argv)

    rows = [json.loads(l) for l in Path(args.manifest).read_text().splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    if args.smoke == args.real:
        p.error("choose exactly one of --smoke or --real")
    if args.real:
        if not args.model_dir or not args.checkpoint_path:
            p.error("--real requires --model-dir and --checkpoint-path")
        from lyricalign.research_v7.real_executor import RealAligner, make_real_executor
        executor = make_real_executor(RealAligner(args.model_dir, args.revision, args.checkpoint_path))
    else:
        executor = _fake_executor(None)
    out_root = Path(args.out_root)
    written = 0
    cache_hit = 0
    forward = 0
    identities: list[dict] = []
    cursor_after_by_request: dict[str, float | None] = {}
    rows_after_by_request: dict[str, list[dict]] = {}
    import time as _time
    t_start = _time.time()
    for i, r in enumerate(rows):
        units = tuple(r.get("text_units", []))
        parent = r.get("parent_request_id")
        cursor_prev = cursor_after_by_request.get(parent) if parent else None
        # review3-1：若为 C3 生成的 WAV（提供 files），用 generated wav 作为 audio 源并重算窗口
        if r.get("files"):
            a0, a1 = 0.0, (r.get("duration_sec") or 0.0) if r.get("duration_sec") else (r.get("audio_end_sec", 60.0) - r.get("audio_start_sec", 0.0))
        else:
            a0, a1 = r.get("audio_start_sec", 0.0), r.get("audio_end_sec", r.get("duration_sec", 0.0) or 60.0)
        if r.get("workflow_mode") == "strict_serial_progressive_crop" and parent:
            if cursor_prev is None:
                raise RuntimeError(f"{r.get('request_id')}: P2 requires completed parent cursor {parent}")
            a0 = max(float(a0), float(cursor_prev) - float(r.get("left_context_sec", 10.0)))
        slot = tuple(r["timestamp_slot_indices"]) if r.get("timestamp_slot_indices") is not None else None
        if r.get("provisional_policy") == "last_predicted_seconds" and parent:
            previous_rows = rows_after_by_request.get(parent, [])
            cutoff = float(cursor_prev or 0.0) - float(r.get("provisional_last_sec", 0.0))
            recent = [int(row["global_character_index"]) for row in previous_rows if float(row.get("fixed_global_end_sec", 0.0)) > cutoff]
            source_start = int(r.get("source_text_start_index", 0))
            slot_start = min(recent) if recent else source_start
            slot = tuple(range(max(0, slot_start), len(units)))
        mutation = r.get("mutation_type", "baseline")
        req = AlignmentRequest(
            request_id=r.get("request_id") or f"{r['item_id']}:{mutation}:{r.get('ratio', 1.0)}:{r.get('position', 'whole')}:{i}",
            item_id=r.get("item_id", f"r{i}"),
            parent_request_id=r.get("parent_request_id"),
            audio_source=r.get("files")[0] if r.get("files") else (r.get("audio_path", "demucs_vocal")),
            audio_start_sec=a0,
            audio_end_sec=a1,
            text_source=r.get("text_source") or r.get("gt_path") or "labels",
            text_start_index=int(r.get("text_start_index", 0)),
            text_end_index=int(r.get("text_end_index", len(units))),
            text_units=units,
            timestamp_slot_indices=slot,
            workflow_mode=r.get("workflow_mode", "behavior_suite") or "behavior_suite",
            mutation_type=mutation or "baseline",
            mutation_parameters={key: r.get(key) for key in (
                "ratio", "requested_ratio", "actual_ratio", "position", "mutation_position", "source", "text_relation",
                "audio_relation", "source_text_start_index", "source_text_end_index", "baseline_unit_count", "n_base",
                "actual_added_units", "actual_removed_units", "actual_replaced_units", "donor_song_id", "donor_start_index",
                "donor_end_index", "donor_similarity", "selection_seed", "cursor_offset_units", "provisional_policy",
                "provisional_tail_units", "provisional_last_sec", "c10_case", "repeat_gt_starts", "repeat_unit_count")},
            model_id=args.model,
            checkpoint_id=args.checkpoint,
            input_variant=r.get("input_variant", "text_mutation"),
            metadata={"dataset": r.get("dataset"), "split": r.get("split"),
                      "source_song_id": r.get("source_song_id") or r.get("song_id"),
                      "language": r.get("language") or "Chinese", "provenance": r.get("provenance", {}),
                      "request_identity": r.get("request_identity"),
                      "canonical_mapping": r.get("canonical_mapping", {})},
        )
        req.validate()
        item_dir = out_root / "items" / str(req.item_id)
        f = item_dir / f"behavior-{mutation}-{r.get('ratio', 1.0)}-{r.get('position', 'whole')}-{i}.json"
        if f.exists():
            if not args.resume:
                raise FileExistsError(f"refusing to overwrite existing evidence: {f}; use --resume after identity verification")
            existing = json.loads(f.read_text(encoding="utf-8"))
            prior = existing.get("attempt", {}).get("request")
            expected = json.loads(json.dumps(req.to_dict()))
            if prior != expected:
                raise RuntimeError(f"resume identity mismatch for {f}")
            prior_attempt = existing["attempt"]
            cursor_after_by_request[req.request_id] = prior_attempt.get("cursor_after")
            rows_after_by_request[req.request_id] = list(prior_attempt.get("decoder_outputs", {}).get("official", {}).get("rows", []))
            cache_hit += 1
            identities.append({"item_id": req.item_id, "request_id": req.request_id, "request_identity": req.request_identity(),
                               "cache": "hit", "status": prior_attempt.get("status")})
            continue
        ev = run_request(req, executor, cursor_prev=cursor_prev)
        item_dir.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(ev.to_dict(), ensure_ascii=False, indent=1))
        cursor_after_by_request[req.request_id] = ev.attempt.cursor_after
        rows_after_by_request[req.request_id] = list(ev.attempt.decoder_outputs.get("official", {}).get("rows", []))
        written += 1
        forward += 1
        identities.append({"item_id": req.item_id, "request_id": req.request_id, "request_identity": req.request_identity(),
                           "cache": "miss", "status": ev.attempt.status})

    # review3：真实运行产物 RUN_MANIFEST（含 run_id、budget、每请求 identity、cache hit/miss、forward）
    run_manifest = {
        "schema": "research_v7_long_slot_v1",
        "run_id": f"rl-{_time.strftime('%Y%m%d_%H%M%S')}",
        "code_identity": {"git_commit": _git_head(), "dirty_tree_hash": _git_dirty()},
        "runtime_budget": {"elapsed_sec": round(_time.time() - t_start, 3), "forward_count": forward,
                           "cache_hit": cache_hit, "cache_miss": forward, "cache_total": cache_hit + forward},
        "item_count": {"requests": len(rows), "written": written, "cache_hit": cache_hit, "forward": forward},
        "requests_identity": identities,
    }
    (out_root / "RUN_MANIFEST.json").write_text(json.dumps(run_manifest, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "rows": len(rows), "written": written,
                      "cache_hit": cache_hit, "forward": forward,
                      "out_root": str(out_root), "executor": "real" if args.real else "fake-smoke"}, ensure_ascii=False))
    return 0


def _git_head() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        return ""


def _git_dirty() -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
        return "dirty" if out else "clean"
    except Exception:  # noqa
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
