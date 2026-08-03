#!/usr/bin/env python3
"""research_v7 align_behavior 单 case 运行入口（可注入 executor）。

用法：
  # fake/smoke executor —— 不依赖模型/GPU，验证契约与流水线
  PYTHONPATH=src python scripts/research_v7/run_alignment_behavior.py \
      --item fake_001 --audio 0.0 60.0 --text-units a b c d e \
      --mutation-type extra --ratio 0.5 --out-root runs/research_v7_align_behavior/smoke \
      --smoke

  # real executor（pilot 阶段由 pilot 注册/注入；此处骨架不内置 GPU 推理）

CLI 把 请求/basline mutation 说明转成 v7 契约，跑一个 attempt，写 evidence json
到 <out-root>/items/<item>/attempt-<id>.json。路径与模型必须通过参数传入，不硬编码。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

try:
    from lyricalign.research_v7.attempt import run_request
    from lyricalign.research_v7.mutations import (
        DonorSpec,
        MutationCatalog,
        extra_ratio,
        missing_ratio,
        no_match,
        replace_ratio,
    )
    from lyricalign.research_v7.requests import AlignmentRequest
except ImportError as e:  # pragma: no cover
    print(f"[error] cannot import research_v7: {e}", file=sys.stderr)
    sys.exit(3)


def _fake_executor(rng_units: list):
    """smoke 用假的 executor：返回一个占位 attempt，验证数据流而非真实推理。"""
    import random

    rnd = random.Random(0)

    def ex(request: AlignmentRequest) -> object:
        from lyricalign.research_v7.attempt import AlignmentAttempt

        n = len(request.text_units)
        # 伪造几何：每 unit 约 0.5s 起止
        rows = [
            {"global_character_index": i, "start_sec": i * 0.5 - 0.1, "end_sec": i * 0.5 + 0.4}
            for i in range(n)
        ]
        return AlignmentAttempt(
            request=request,
            attempt_id=f"fake-{uuid.uuid4().hex[:8]}",
            decoder_outputs={"official": {"rows": rows}, "raw": {"rows": rows}},
            cursor_after=float(n) * 0.5 if request.text_units else 0.0,
            committed=True,
            runtime_sec=0.01,
            status="ok",
        )

    return ex


def _apply_mutation(base_units, mtype, ratio, position, source, donor, seed):
    if mtype == "extra":
        return extra_ratio(base_units, ratio, source=source or "future", position=position or "tail")
    if mtype == "missing":
        return missing_ratio(base_units, ratio, position=position or "tail", seed=seed)
    if mtype == "replace":
        d = DonorSpec(
            donor_song_id=donor.get("song", "donor"),
            donor_start_index=donor.get("start", 0),
            donor_units=tuple(donor.get("units", ["X", "Y", "Z"])),
            language=donor.get("language", "zh"),
            unit_mode="char",
        )
        return replace_ratio(base_units, ratio, donor=d, position=position or "whole", seed=seed)
    if mtype == "no_match":
        d = DonorSpec(
            donor_song_id=donor.get("song", "donor"),
            donor_start_index=donor.get("start", 0),
            donor_units=tuple(donor.get("units", ["X", "Y", "Z"])),
            language=donor.get("language", "zh"),
            unit_mode="char",
        )
        return no_match(base_units, donor=d, language="zh", unit_mode="char")
    raise ValueError(f"unknown mutation type: {mtype}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--item", required=True)
    p.add_argument("--audio", nargs=2, type=float, required=True, help="audio_start end")
    p.add_argument("--text-units", nargs="+", required=True)
    p.add_argument("--text-source", default="lyrics")
    p.add_argument("--audio-source", default="demucs_vocal")
    p.add_argument("--mutation-type", default="extra", choices=["extra", "missing", "replace", "no_match", "baseline"])
    p.add_argument("--ratio", type=float, default=0.0)
    p.add_argument("--position", default=None, choices=["head", "tail", "middle", "dispersed", "whole", None])
    p.add_argument("--source", default="future")
    p.add_argument("--donor", default=None, help="JSON {song,start,units,language}")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--model", default="Qwen3-ForcedAligner-0.6B-hf")
    p.add_argument("--checkpoint", default="r2-step-000750")
    p.add_argument("--out-root", required=True)
    p.add_argument("--smoke", action="store_true", help="use fake executor (no model/GPU)")
    args = p.parse_args(argv)

    base_units = tuple(args.text_units)
    if args.mutation_type == "baseline":
        mutated_units = base_units
        mtype = "baseline"
        mparams = {}
    else:
        donor = json.loads(args.donor) if args.donor else {}
        m = _apply_mutation(base_units, args.mutation_type, args.ratio, args.position,
                            args.source, donor, args.seed)
        mutated_units = m.mutated_units
        mtype = m.mutation_type
        mparams = {
            "ratio": m.requested_ratio,
            "actual_ratio": m.actual_ratio,
            "position": m.position,
            "source": m.source,
        }

    req = AlignmentRequest(
        request_id=f"{args.item}:{mtype}:{args.ratio}",
        item_id=args.item,
        parent_request_id=None,
        audio_source=args.audio_source,
        audio_start_sec=args.audio[0],
        audio_end_sec=args.audio[1],
        text_source=args.text_source,
        text_start_index=0,
        text_end_index=len(mutated_units),
        text_units=mutated_units,
        timestamp_slot_indices=None,
        workflow_mode="single_attempt",
        mutation_type=mtype,
        mutation_parameters=mparams,
        model_id=args.model,
        checkpoint_id=args.checkpoint,
        input_variant="text_mutation",
    )
    req.validate()

    executor = _fake_executor(list(mutated_units)) if args.smoke else _no_real  # real 由 pilot 接入
    ev = run_request(req, executor)

    out_dir = Path(args.out_root) / "items" / args.item
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"attempt-{mtype}-{args.ratio}.json"
    out_file.write_text(json.dumps(ev.to_dict(), ensure_ascii=False, indent=1))
    digest = hashlib.sha256(out_file.read_bytes()).hexdigest()[:16]

    print(json.dumps({
        "ok": True,
        "item": args.item,
        "mutation": mtype,
        "requested_ratio": args.ratio,
        "units_before": len(base_units),
        "units_after": len(mutated_units),
        "evidence": str(out_file),
        "sha256": digest,
        "executor": "fake-smoke" if args.smoke else "pending-real",
    }, ensure_ascii=False))
    return 0


def _no_real(_req):
    raise NotImplementedError("real executor not injected yet; use --smoke")


if __name__ == "__main__":
    raise SystemExit(main())
