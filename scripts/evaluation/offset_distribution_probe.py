#!/usr/bin/env python3
"""Dump the *full* offset-slot distribution per character, to ask whether duration information exists.

Tonight's error decomposition says the model's implied duration is worse than its direct end prediction
(≥2 s: 60 ms vs 35 ms) and that end errors are unrelated to start errors.  Before spending GPU-hours on a
structural change, we need to know whether the missing duration information is *present but mis-read*
(a decoding/calibration problem, cheap) or *absent from the representation* (architecture problem,
expensive).  This script stores the distribution so that readout estimators can be compared off-GPU.

    PYTHONPATH=src python scripts/evaluation/offset_distribution_probe.py \
        --checkpoint /home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724/checkpoints/step-012000 \
        --limit 900 --batch-size 4 --out results/by_run/20260914_offset_dist/rows.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import importlib.util
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 与 ②b 测量工具同一条构造路径：TOPUP 提供 build_stage_model / load_weights，
# 避免两边"看起来一样、其实模型装配不同"的隐性偏差。
TOPUP = _load_module("run_funnel_topup", ROOT / "scripts" / "training" / "run_funnel_topup.py")
from lyricalign.inference.constrained_timestamps import slot_logprobs  # noqa: E402

TOP_K = 32


def distribution_summary(row_probs: np.ndarray) -> dict[str, Any]:
    """Compact, loss-enough description of one slot's categorical distribution over bins.

    Input must already be probabilities: `slot_logprobs` returns log-probabilities, so the caller
    exponentiates first (same as the ②b dump does) — means and quantiles on log-space would be garbage.
    """
    probs = np.asarray(row_probs, dtype=np.float64)
    total = float(probs.sum())
    if total <= 0:
        return {}
    probs = probs / total
    bins = np.arange(probs.size, dtype=np.float64)
    order = np.argsort(probs)[::-1][:TOP_K]
    cdf = np.cumsum(probs)
    quantile = lambda q: int(np.searchsorted(cdf, q))  # noqa: E731
    return {
        "top_bins": [int(b) for b in order],
        "top_probs": [round(float(probs[b]), 5) for b in order],
        "mean_bin": round(float((probs * bins).sum()), 3),
        "median_bin": quantile(0.5),
        "q25_bin": quantile(0.25),
        "q75_bin": quantile(0.75),
        "argmax_bin": int(probs.argmax()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"))
    parser.add_argument("--audio-root", type=Path,
                        default=Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/training/qwen_fa_lora_from_official_20260913.yaml")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--stage", default="r2")
    parser.add_argument("--splits", default="validation")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--long-sec", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=900)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sample-seed", type=int, default=20260913)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--local-files-only", action="store_true", default=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # 导入必须在函数开头：放在后面会让 read_jsonl 成为"先用后绑定"的局部变量
    import torch
    import yaml
    from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, move_inputs, read_jsonl

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    wanted = {name.strip() for name in args.splits.split(",") if name.strip()}
    if "test" in wanted and not args.allow_test:
        raise SystemExit("refusing to sample test items without --allow-test (selection firewall)")
    rows = [row for row in read_jsonl(args.labels) if str(row.get("split")) in wanted]
    rows = [row for row in rows if (args.audio_root / row["audio_relpath"]).exists()]
    rows = [row for row in rows
            if any((row["timestamp_class_ids"][2 * index + 1] - row["timestamp_class_ids"][2 * index]) * 0.08
                   >= args.long_sec for index in range(len(row["timestamp_class_ids"]) // 2))]
    random.Random(args.sample_seed).shuffle(rows)
    if args.limit:
        rows = rows[: args.limit]

    model, processor = TOPUP.build_stage_model(cfg, args.stage, args.device, True)
    TOPUP.load_weights(args.checkpoint, model)
    model.eval()
    collator = QwenFABatchCollator(processor, audio_root=args.audio_root,
                                   language=cfg["data"]["language"],
                                   timestamp_token_id=model.config.timestamp_token_id)
    dtype = getattr(torch, cfg["training"].get("dtype", "bfloat16"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    written = 0
    with args.out.open("w", encoding="utf-8") as handle:
        for offset in range(0, len(rows), args.batch_size):
            chunk = rows[offset: offset + args.batch_size]
            inputs, words = collator(chunk)
            with torch.no_grad():
                output = model(**move_inputs(inputs, args.device, dtype))
            for sample, record in enumerate(chunk):
                log_probs = slot_logprobs(output.logits[sample: sample + 1],
                                          inputs["input_ids"][sample: sample + 1],
                                          timestamp_token_id=model.config.timestamp_token_id)
                # slot_logprobs 已经在内部取过 batch 维：返回 (字符数, 2, 类别数)，不能再 [0]
                array = np.asarray(log_probs, dtype=np.float64)
                if array.ndim == 2:      # 防御：某些路径只返回一个槽位
                    array = array[:, np.newaxis, :]
                probabilities = np.exp(array - array.max(axis=2, keepdims=True))
                step = float(record["timestamp_segment_sec"])
                class_ids = record["timestamp_class_ids"]
                characters = min(len(words[sample]), probabilities.shape[0])
                if characters < 2:
                    continue
                for index in range(characters):
                    start_bin, end_bin = int(class_ids[2 * index]), int(class_ids[2 * index + 1])
                    onset_summary = distribution_summary(probabilities[index, 0])
                    offset_summary = distribution_summary(probabilities[index, 1])
                    handle.write(json.dumps({
                        "item_id": record["item_id"], "song": "#".join(str(record["item_id"]).split("#")[:2]),
                        "index": index, "step_sec": step,
                        "gt_start_bin": start_bin, "gt_end_bin": end_bin,
                        "gt_duration": round((end_bin - start_bin) * step, 4),
                        "onset": onset_summary, "offset": offset_summary}, ensure_ascii=False) + "\n")
                    written += 1
            print(f"processed {offset + len(chunk)}/{len(rows)} items ({time.time() - started:.0f}s)", flush=True)
    summary = {"schema_version": "offset_distribution_v1", "checkpoint": str(args.checkpoint),
               "items": len(rows), "characters": written, "top_k": TOP_K, "out": str(args.out)}
    args.out.with_name("summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                                  encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
