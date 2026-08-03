#!/usr/bin/env python3
"""阶段 B：run_behavior_suite —— 从 behavior_manifest 批量跑 alignment 行为用例。

对 manifest 每条（baseline/extra/missing/replace/no_match）构造 v7 AlignmentRequest，
支持 sparse-slot 骨架（slot mask），用可注入 executor 产出 EvidencePack 到 <out-root>/items。

用法：
  PYTHONPATH=src python scripts/research_v7/run_behavior_suite.py \
      --manifest <behavior_manifest.jsonl> --out-root runs/research_v7_align_behavior/run \
      --smoke                      # fake executor，纯 CPU 验证
  # 真模型推理：pilot 阶段注入 --executor 或实现 real executor；本骨架用 --smoke 验证契约。

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
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--model", default="Qwen3-ForcedAligner-0.6B-hf")
    p.add_argument("--checkpoint", default="r2-step-000750")
    args = p.parse_args(argv)

    rows = [json.loads(l) for l in Path(args.manifest).read_text().splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    executor = _fake_executor(None) if args.smoke else None
    out_root = Path(args.out_root)
    written = 0
    for i, r in enumerate(rows):
        units = tuple(r.get("text_units", []))
        a0, a1 = audio_range(r.get("duration_sec"))
        # sparse-slot 骨架：baseline 全放；其他默认 None（正式 slot 策略在 pilot）
        slot = None
        mutation = r.get("mutation_type", "baseline")
        req = AlignmentRequest(
            request_id=f"{r['item_id']}:{mutation}:{r.get('ratio', 1.0)}",
            item_id=r.get("item_id", f"r{i}"),
            parent_request_id=None,
            audio_source="demucs_vocal",
            audio_start_sec=a0,
            audio_end_sec=a1,
            text_source="labels",
            text_start_index=0,
            text_end_index=len(units),
            text_units=units,
            timestamp_slot_indices=slot,
            workflow_mode="behavior_suite",
            mutation_type=mutation,
            mutation_parameters={"ratio": r.get("ratio"), "position": r.get("position"), "source": r.get("source")},
            model_id=args.model,
            checkpoint_id=args.checkpoint,
            input_variant="text_mutation",
        )
        req.validate()
        ev = run_request(req, executor)
        item_dir = out_root / "items" / str(req.item_id)
        item_dir.mkdir(parents=True, exist_ok=True)
        f = item_dir / f"behavior-{mutation}-{r.get('ratio', 1.0)}.json"
        f.write_text(json.dumps(ev.to_dict(), ensure_ascii=False, indent=1))
        written += 1

    print(json.dumps({"ok": True, "rows": len(rows), "written": written,
                      "out_root": str(out_root), "executor": "fake-smoke" if args.smoke else "pending-real"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
