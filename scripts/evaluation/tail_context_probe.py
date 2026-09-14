#!/usr/bin/env python3
"""Does cutting off the audio tail hurt long notes? A direct, paired test.

Motivation (structural pre-registration §11): 83% of long characters sit at the end of their item, so
their release often falls at or beyond the crop boundary. The conditional-rate check could not resolve it
(5.6% vs 3.5%, z=+0.64, only 57 non-final long characters), so this tests it the direct way: decode the same
item twice — once as the product crops it, once with extra silent tail appended — and compare the end-boundary
error of the final long character. If tail context matters, the extra tail should reduce its error; the
non-final characters act as an internal control (their audio is unchanged, so any change there is noise).

This script has NOT been run against a GPU yet; run it with `--limit 3` first (smoke), then in full.

    PYTHONPATH=src python scripts/evaluation/tail_context_probe.py --limit 3 \
        --out results/by_run/20260914_tail_context/smoke.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics as st
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"))
    parser.add_argument("--audio-root", type=Path,
                        default=Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/training/qwen_fa_lora_from_official_20260913.yaml")
    parser.add_argument("--checkpoint", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724/checkpoints/step-012000"))
    parser.add_argument("--stage", default="r2")
    parser.add_argument("--extra-tail-sec", type=float, default=2.0)
    parser.add_argument("--long-sec", type=float, default=1.5)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import torch
    import yaml
    from lyricalign.inference.constrained_timestamps import slot_logprobs
    from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, move_inputs, read_jsonl

    TOPUP = _load("run_funnel_topup", "scripts/training/run_funnel_topup.py")
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    rows = [row for row in read_jsonl(args.labels) if str(row.get("split")) == "validation"]
    step = float(cfg["training"].get("timestamp_segment_sec", 0.08))

    def duration_of(row: dict[str, Any], index: int) -> float:
        ids = row["timestamp_class_ids"]
        return (ids[2 * index + 1] - ids[2 * index]) * step

    # keep items whose LAST character is long — that is the case the tail hypothesis is about
    picked = []
    for row in rows:
        count = len(row["timestamp_class_ids"]) // 2
        if count < 2:
            continue
        if duration_of(row, count - 1) >= args.long_sec:
            picked.append(row)
        if len(picked) >= args.limit:
            break
    if len(picked) < 5:
        raise SystemExit(f"可用条目太少（{len(picked)}），不足以做配对比较")

    model, processor = TOPUP.build_stage_model(cfg, args.stage, args.device, True)
    TOPUP.load_weights(args.checkpoint, model)
    model.eval()
    dtype = getattr(torch, cfg["training"].get("dtype", "bfloat16"))
    class TailCollator(QwenFABatchCollator):
        """Honours `_audio_override`; the base class reads the file and would ignore it silently."""

        def load_audio(self, row: dict[str, Any]):
            override = row.get("_audio_override")
            if override is not None:
                return override
            return super().load_audio(row)

    collator = TailCollator(processor, audio_root=args.audio_root, language=cfg["data"]["language"],
                            timestamp_token_id=model.config.timestamp_token_id)

    def decode(batch_rows: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
        inputs, words = collator(batch_rows)
        # 断言两次解码真的不同：否则"无差异"是假阴性而不是结论（20:51 自查抓到）
        frames = int(inputs["input_features"].shape[-1]) if hasattr(inputs.get("input_features"), "shape") else -1
        batch_rows_len = [float(np.asarray(row.get("_audio_override")).size / 16000.0)
                          if row.get("_audio_override") is not None else None for row in batch_rows]
        decode.last_frames = frames
        decode.last_tailed = bool(any(value is not None for value in batch_rows_len))
        with torch.no_grad():
            output = model(**move_inputs(inputs, args.device, dtype))
        logp = np.asarray(slot_logprobs(output.logits, inputs["input_ids"],
                                        timestamp_token_id=model.config.timestamp_token_id), dtype=np.float64)
        probs = np.exp(logp - logp.max(axis=2, keepdims=True))
        final_errors: list[float] = []
        inner_errors: list[float] = []
        offset = 0
        for row in batch_rows:
            count = min(len(row["timestamp_class_ids"]) // 2, probs.shape[0] - offset)
            for index in range(count):
                start_bin = int(probs[offset + index, 0].argmax())
                end_bin = int(probs[offset + index, 1].argmax())
                true_end = row["timestamp_class_ids"][2 * index + 1] * step
                error = abs(end_bin * step - true_end)
                (final_errors if index == count - 1 else inner_errors).append(error)
            offset += count
        return final_errors, inner_errors

    base_frames_seen = -1
    final_base: list[float] = []
    final_tail: list[float] = []
    inner_base: list[float] = []
    inner_tail: list[float] = []
    started = time.time()
    for offset in range(0, len(picked), args.batch_size):
        chunk = picked[offset:offset + args.batch_size]
        try:
            fb, ib = decode(chunk)
        except Exception as error:          # noqa: BLE001 - keep the probe honest about per-item failures
            print(f"skip {offset}: {error}", flush=True)
            continue
        tailed = []
        for row in chunk:
            path = args.audio_root / row["audio_relpath"]
            if not path.exists():
                tailed.append(row)
                continue
            samples, rate = __import__("soundfile").read(str(path), dtype="float32", always_2d=False)
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            padded = np.concatenate([samples, np.zeros(int(args.extra_tail_sec * rate), dtype=np.float32)])
            new_row = dict(row)
            new_row["_audio_override"] = padded
            tailed.append(new_row)
        try:
            ft, it = decode(tailed)
        except Exception as error:          # noqa: BLE001
            print(f"skip tail pass {offset}: {error}", flush=True)
            continue
        if not getattr(decode, "last_tailed", False):
            raise SystemExit("尾窗覆盖没有生效（两遍输入完全相同）⇒ 实验会是假阴性，已停止")
        frames_base = getattr(decode, "last_frames", -1)
        if frames_base <= base_frames_seen and offset > 0 and frames_base == base_frames_seen:
            raise SystemExit("尾窗版本的帧数没有变多 ⇒ 覆盖未生效，已停止")
        base_frames_seen = frames_base
        n = min(len(fb), len(ft))
        final_base += fb[:n]
        final_tail += ft[:n]
        m = min(len(ib), len(it))
        inner_base += ib[:m]
        inner_tail += it[:m]
        print(f"processed {offset + len(chunk)}/{len(picked)} ({time.time() - started:.0f}s)", flush=True)

    if not final_base:
        raise SystemExit("没有任何条目成功解码，无法比较")

    def summarise(base: list[float], tail: list[float], label: str) -> dict[str, Any]:
        return {"label": label, "characters": len(base),
                "median_base_ms": round(1000 * st.median(base), 1),
                "median_tail_ms": round(1000 * st.median(tail), 1),
                "miss_base": round(sum(1 for value in base if value > 0.2) / len(base), 4),
                "miss_tail": round(sum(1 for value in tail if value > 0.2) / len(tail), 4),
                "improved": sum(1 for b, t in zip(base, tail) if b - t > 0.02),
                "worsened": sum(1 for b, t in zip(base, tail) if t - b > 0.02)}

    payload = {"schema_version": "tail_context_probe_v1", "checkpoint": str(args.checkpoint),
               "extra_tail_sec": args.extra_tail_sec, "items": len(picked),
               "final_long_character": summarise(final_base, final_tail, "条目末尾的长字（受尾窗假设影响的那批）"),
               "inner_characters": summarise(inner_base, inner_tail, "非末尾字（内部对照：音频未变）")}
    tail_case = payload["final_long_character"]
    control = payload["inner_characters"]
    payload["reading"] = ("尾窗假设支持：末尾长字误差下降明显多于内部对照"
                          if (tail_case["median_base_ms"] - tail_case["median_tail_ms"]) > 2 * abs(
                              control["median_base_ms"] - control["median_tail_ms"]) + 20
                          else "看不出超出内部对照噪声的收益 ⇒ 延长尾窗对这个指标无帮助（或样本不足）")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
