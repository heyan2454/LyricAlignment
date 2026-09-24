#!/usr/bin/env python3
"""Out-of-domain replay of the two selection rules, against human ground truth.

Why this exists: the monotone whole-sequence decode is measured in-domain only.  This script re-decodes the
GTSinger panel (which carries per-unit human timings) and compares, on the SAME forward pass:
  * the product selection (`official`, via the processor — untouched, imported as-is), and
  * the monotone DP decode via the separate helper `dp_timestamp_items` (a new function; nothing about the
    original decoder is modified).

Input is the existing per-unit evidence archive, which already stores audio path, unit text, and GT times,
so no new dataset plumbing is invented.  GTSinger is treated as test-only: reported, never used for
checkpoint selection (same discipline the archive itself declares).

    PYTHONPATH=src python scripts/evaluation/ood_dp_replay.py --limit-items 3 \
        --out results/by_run/20260914_ood_dp_replay/smoke.json
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import statistics as st
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

TOL = 0.2
LONG_SEC = 1.5


def _load(name: str, rel: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_items(evidence: Path, *, limit_items: int) -> "OrderedDict[str, dict[str, Any]]":
    """Collapse the per-unit evidence rows into items: audio + transcript + per-unit GT."""
    items: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    with gzip.open(evidence, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("model")) != "r2":
                continue
            audio = str(row.get("audio_path") or "")
            text = str(row.get("text") or "").strip()
            start, end = row.get("gt_start_sec"), row.get("gt_end_sec")
            if not audio or not text or start is None or end is None:
                continue
            item = items.setdefault(audio, {"audio_path": Path(audio), "units": []})
            key = (float(start), float(end), text)
            if all((float(u["gt_start"]), float(u["gt_end"]), u["text"]) != key for u in item["units"]):
                item["units"].append({"gt_start": float(start), "gt_end": float(end), "text": text})
            if limit_items and len(items) >= limit_items:
                break
    for item in items.values():
        item["units"].sort(key=lambda unit: unit["gt_start"])
    return items


def bucket(errors: list[float]) -> dict[str, Any]:
    if not errors:
        return {"units": 0}
    return {"units": len(errors),
            "miss_share": round(sum(1 for value in errors if value > TOL) / len(errors), 4),
            "median_err_ms": round(1000 * st.median(errors), 1),
            "mean_err_ms": round(1000 * st.mean(errors), 1)}


def compute_structure(rows_by_name: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """塌陷画像：零长度/负长度/重叠/起始倒退/共用同一结束点的连续块。

    与产品成品审计同一把尺（`src/lyricalign/analysis/structural_compliance.py`），分组键是单个音频条目，
    所以不会产生跨条目的假重叠。**注意 DP 会把零长度与重叠这两个探针全部抹平**——单独看 DP 的
    illegal_share=0 不代表铺得对，必须与 official 的读数并排看（`AI_SESSION_ENTRY.md` 第 5 条）。
    """
    out: dict[str, Any] = {}
    try:
        import pandas as pd
        from lyricalign.analysis import structural_compliance as SC
    except Exception as error:  # noqa: BLE001 缺 pandas 时如实报告，不伪造结构读数
        return {"unavailable": f"{type(error).__name__}: {error}"}
    for name, rows in rows_by_name.items():
        if not rows:
            out[name] = {"units": 0}
            continue
        frame = pd.DataFrame(rows).dropna(subset=["start_sec", "end_sec"])
        frame = frame.sort_values(["song", "unit_index"]).reset_index(drop=True)
        flagged = SC.flag_violations(frame)
        blocks = 0
        longest = 0
        worst = ""
        for song, sub in flagged.groupby("song", sort=False):
            ends = sub["end_sec"].to_numpy(dtype=float)
            run = 1
            for index in range(1, len(ends)):
                if ends[index] == ends[index - 1]:
                    run += 1
                else:
                    blocks += 1 if run >= 5 else 0
                    if run > longest:
                        longest, worst = run, str(song)
                    run = 1
            blocks += 1 if run >= 5 else 0
            if run > longest:
                longest, worst = run, str(song)
        out[name] = {
            "units": int(len(flagged)), "items": int(flagged["song"].nunique()),
            "zero_or_negative_share": round(float(flagged["flag_zero_or_negative"].mean()), 4),
            "overlap_next_share": round(float(flagged["flag_overlaps_next"].mean()), 4),
            "start_regression_share": round(float(flagged["flag_start_regression"].mean()), 4),
            "overshoot_share": round(float(flagged["flag_overshoot"].mean()), 4),
            "illegal_share": round(float(flagged["is_illegal"].mean()), 4),
            "collapse_blocks_ge5": int(blocks),
            "longest_same_end_block": int(longest),
            "worst_item": worst.rsplit("/", 1)[-1],
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/training/qwen_fa_lora_from_official_20260913.yaml")
    parser.add_argument("--checkpoint", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724/checkpoints/step-012000"))
    parser.add_argument("--stage", default="r2")
    parser.add_argument("--base-model-only", action="store_true",
                        help="跳过 checkpoint 权重加载，测**未微调的官方底座**（此时 --stage 用 r0；"
                             "build_stage_model 在 r0 下只 freeze_all，不加 LoRA、不动 projector）")
    parser.add_argument("--limit-items", type=int, default=0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dataset-label", default="GTSinger",
                        help="域外数据集名，只写进产物元数据，便于区分不同语料的复评")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dump-units", type=Path, default=None,
                        help="把逐单元的 gt/official/dp 起止时间、top-1、熵、容差内质量落成 jsonl.gz，"
                             "供零人工的塌陷画像脚本消费（纯新增产物，不影响任何既有读数）")
    args = parser.parse_args()

    import torch
    import yaml
    from lyricalign.inference.constrained_timestamps import (dp_timestamp_items, slot_logprobs)
    from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, move_inputs

    TOPUP = _load("run_funnel_topup", "scripts/training/run_funnel_topup.py")

    items = collect_items(args.evidence, limit_items=args.limit_items)
    if not items:
        raise SystemExit(f"从 {args.evidence} 没取到条目（检查音频路径是否存在）")
    usable = [(path, item) for path, item in items.items() if item["audio_path"].exists() and len(item["units"]) >= 3]
    print(f"取到 {len(items)} 条，其中音频存在且单元数≥3 的 {len(usable)} 条", flush=True)
    if not usable:
        raise SystemExit("没有可用条目")

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    model, processor = TOPUP.build_stage_model(cfg, args.stage, args.device, True)
    if args.base_model_only:
        source_label = f"base-model-only:{cfg['model']['id']}@{cfg['model'].get('revision', '?')}"
        print(f"[baseline] 不加载任何 checkpoint：{source_label}", flush=True)
    else:
        loaded = TOPUP.load_weights(args.checkpoint, model)
        source_label = f"{args.checkpoint} (step {loaded})"
    model.eval()
    dtype = getattr(torch, cfg["training"].get("dtype", "bfloat16"))
    # 注意：这里用的仍是产品原来的 collator/解码；整句挑走独立函数 dp_timestamp_items，
    # 不改动 official / processor.decode_forced_alignment 的任何行为。
    collator = QwenFABatchCollator(processor, audio_root=Path("/"), language=cfg["data"]["language"],
                                   timestamp_token_id=model.config.timestamp_token_id)

    def read_audio_16k(path: Path) -> Any:
        """Same loader the product path uses (ffmpeg → mono 16 kHz float32); GTSinger files are 44.1 kHz."""
        import numpy as np
        import subprocess
        result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                                 "-f", "f32le", "-"], check=True, capture_output=True)
        return np.frombuffer(result.stdout, dtype=np.float32)

    def records_for(chunk: list[tuple[Path, dict[str, Any]]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path, item in chunk:
            seconds = max(unit["gt_end"] for unit in item["units"])
            samples = read_audio_16k(path)
            # 音频可能比标注跨度长（GTSinger 单元片段），裁到标注末尾 + 0.5s，避免无尾静音把 bin 网格推歪
            cut = int((seconds + 0.5) * 16000)
            step = float(cfg["training"].get("timestamp_segment_sec", 0.08))
            out.append({"item_id": str(path), "audio_relpath": Path(path).name,
                        # collator 一定要这个字段；值不参与解码（我们只用 logits），故给零占位，
                        # 槽位数与单元数一致即可，对不上的条目在下面被跳过并计数。
                        "timestamp_class_ids": [0] * (2 * len(item["units"])),
                        "lyrics_normalized": " ".join(unit["text"] for unit in item["units"]),
                        "audio_seconds": min(len(samples) / 16000.0, cut / 16000.0),
                        "_samples": samples[:cut]})
        return out

    class SamplesCollator(QwenFABatchCollator):
        """Reads the already-loaded waveform from the record; no behaviour change elsewhere."""

        def load_audio(self, row: dict[str, Any]):
            return row["_samples"]

    loader = SamplesCollator(processor, audio_root=Path("/"), language=cfg["data"]["language"],
                             timestamp_token_id=model.config.timestamp_token_id)

    errors: dict[str, dict[str, list[float]]] = {
        name: {"all": [], "short": [], "long": []} for name in ("official", "dp")}
    # 结构探针（塌陷/零长度/重叠/起始倒退）：与 GT 无关，只看解码出来的时间轴本身。
    # 口径复用 src/lyricalign/analysis/structural_compliance.py，与产品成品审计同一把尺；
    # 这里以"单个音频条目"为分组键，避免跨条目边界的假重叠。
    structure_rows: dict[str, list[dict[str, Any]]] = {"official": [], "dp": []}
    dump_handle = None
    if args.dump_units is not None:
        args.dump_units.parent.mkdir(parents=True, exist_ok=True)
        dump_handle = gzip.open(args.dump_units, "wt", encoding="utf-8")
    matched_units = 0
    compared_items = 0
    skipped_items = 0
    for offset in range(0, len(usable), 1):
        chunk = usable[offset:offset + 1]
        records = records_for(chunk)
        try:
            inputs, words = loader(records)
        except Exception as error:      # noqa: BLE001 单元数与时间戳占位符不一致时跳过该条并计数
            skipped_items += len(chunk)
            print(f"跳过 {len(chunk)} 条：{str(error)[:80]}", flush=True)
            continue
        with torch.no_grad():
            output = model(**move_inputs(inputs, args.device, dtype))
        official_decode = processor.decode_forced_alignment(output.logits, inputs["input_ids"], words,
                                                            model.config.timestamp_token_id)
        # 整句挑：独立函数、独立调用，不改动上面那条 official 路径
        dp_decode = dp_timestamp_items(output.logits, inputs["input_ids"], words,
                                       timestamp_token_id=model.config.timestamp_token_id,
                                       segment_sec=float(cfg["training"].get("timestamp_segment_sec", 0.08)))
        slots = None
        if dump_handle is not None:
            import numpy as np
            slots = slot_logprobs(output.logits, inputs["input_ids"],
                                  timestamp_token_id=model.config.timestamp_token_id)
            seg = float(cfg["training"].get("timestamp_segment_sec", 0.08))
        for (path, item), official_items, dp_items in zip(chunk, official_decode, dp_decode, strict=False):
            unit_rows: list[dict[str, Any]] = []
            for name, decoded in (("official", official_items), ("dp", dp_items)):
                pairs = [(float(unit["gt_start"]), float(unit["gt_end"]), str(unit["text"])) for unit in item["units"]]
                got = [(float(unit["start_time"]), float(unit["end_time"]), str(unit.get("text", ""))) for unit in decoded]
                for index, (ps, pe, _pt) in enumerate(got):   # 结构指标看全部单元，不按文本匹配筛
                    structure_rows[name].append({"song": str(item["audio_path"]), "unit_index": index,
                                                 "start_sec": ps, "end_sec": pe})
                    while len(unit_rows) <= index:
                        unit_rows.append({})
                    unit_rows[index][f"{name}_start_sec"] = ps
                    unit_rows[index][f"{name}_end_sec"] = pe
                for index, (gt_start, gt_end, text) in enumerate(pairs):
                    if index >= len(got):
                        continue
                    _ps, pe, pt = got[index]
                    if pt and pt != text:      # 单元错位就不比，避免把对齐差异算成解码差异
                        continue
                    error = abs(pe - gt_end)
                    errors[name]["all"].append(error)
                    duration = gt_end - gt_start
                    errors[name]["long" if duration >= LONG_SEC else "short"].append(error)
                    matched_units += 1
            if dump_handle is not None:
                for index, unit in enumerate(item["units"]):
                    row = dict(unit_rows[index]) if index < len(unit_rows) else {}
                    row.update({"view": args.dataset_label, "utt": str(item["audio_path"]),
                                "unit_index": index, "text": str(unit["text"]),
                                "gt_start_sec": float(unit["gt_start"]), "gt_end_sec": float(unit["gt_end"])})
                    if slots is not None and index < len(slots):
                        for which, axis, gt in (("start", 0, unit["gt_start"]), ("end", 1, unit["gt_end"])):
                            logp = slots[index, axis]
                            probs = np.exp(logp)
                            row[f"{which}_top1"] = round(float(probs.max()), 4)
                            row[f"{which}_entropy"] = round(float(-(probs * logp).sum()), 3)
                            low = max(0, int((float(gt) - TOL) / seg))
                            high = min(len(probs) - 1, int((float(gt) + TOL) / seg))
                            row[f"{which}_mass_in_tol"] = round(float(probs[low:high + 1].sum()), 4)
                    dump_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            compared_items += 1
        print(f"已比较 {offset + len(chunk)}/{len(usable)} 条", flush=True)

    buckets = {name: {key: bucket(values) for key, values in groups.items()}
               for name, groups in errors.items()}
    structure = compute_structure(structure_rows)
    payload = {"schema_version": "ood_dp_replay_v1", "evidence": str(args.evidence),
               "checkpoint": source_label, "stage": args.stage,
               "tolerance_sec": TOL, "long_sec": LONG_SEC,
               "dataset": args.dataset_label,
               "discipline": f"{args.dataset_label} 只作域外报告，不参与选点/调参",
               "items_compared": compared_items, "units_matched": matched_units,
               "items_skipped": skipped_items,
               "by_selection": buckets, "structure": structure}
    deltas: dict[str, Any] = {}
    for bucket_key in ("all", "short", "long"):
        official_bucket = buckets["official"][bucket_key]
        dp_bucket = buckets["dp"][bucket_key]
        if official_bucket.get("units") and dp_bucket.get("units") and official_bucket["units"] > 20:
            deltas[bucket_key] = {
                "miss_share_delta_pp": round(100 * (dp_bucket["miss_share"] - official_bucket["miss_share"]), 3),
                "median_err_delta_ms": round(dp_bucket["median_err_ms"] - official_bucket["median_err_ms"], 1)}
    payload["dp_minus_official"] = deltas
    if dump_handle is not None:
        dump_handle.close()
        print(f"[dump] 逐单元产物：{args.dump_units}（{matched_units} 次比较之外的全部单元）", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"units_matched": matched_units, "by_selection": payload["by_selection"],
                      "dp_minus_official": deltas}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
