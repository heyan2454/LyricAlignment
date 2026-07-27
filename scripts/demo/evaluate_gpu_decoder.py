#!/usr/bin/env python3
"""Evaluate raw, official and one GPU decoder checkpoint on cached evidence."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.gpu_boundary_decoder import GpuBoundaryDecoderRuntime, monotonic_project


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_items(root: Path) -> list[dict[str, Any]]:
    import torch

    rows: list[dict[str, Any]] = []
    for path in sorted((root / "shards").glob("*.pt")):
        payload = torch.load(path, map_location="cpu", weights_only=False)
        rows.extend(payload["items"])
    return rows


def metric(accumulator: dict[str, float], prefix: str, errors: Any, segment: float) -> None:
    accumulator[f"{prefix}_abs_sec_sum"] += float(errors.sum()) * segment
    accumulator[f"{prefix}_within_0p08"] += float((errors * segment <= 0.0800001).sum())
    accumulator[f"{prefix}_within_0p16"] += float((errors * segment <= 0.1600001).sum())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--split", action="append", default=[])
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--allow-cpu", action="store_true")
    args = parser.parse_args()

    import torch

    items = load_items(args.cache_root)
    wanted = set(args.split)
    if wanted:
        items = [item for item in items if str(item.get("split")) in wanted]
    if not items:
        raise ValueError(f"no items for splits {sorted(wanted) if wanted else 'all'}")
    runtime = GpuBoundaryDecoderRuntime(args.checkpoint, device=args.device, allow_cpu=args.allow_cpu)
    architecture = runtime.config.architecture
    totals = {key: 0.0 for key in (
        "raw_abs_sec_sum", "raw_within_0p08", "raw_within_0p16",
        "official_abs_sec_sum", "official_within_0p08", "official_within_0p16",
        "decoder_abs_sec_sum", "decoder_within_0p08", "decoder_within_0p16",
    )}
    slot_count = 0
    collapse = {"raw": 0, "official": 0, "decoder": 0}
    started = time.perf_counter()
    with torch.inference_mode():
        for item in items:
            features = item["features"].float().to(args.device)
            raw = item["raw_classes"].float().to(args.device)
            target = item["target_classes"].float().to(args.device)
            official = item["official_classes"].float().to(args.device)
            mask = torch.ones((1, len(raw)), dtype=torch.bool, device=args.device)
            output = runtime.model(features.unsqueeze(0), mask)
            gate = torch.sigmoid(output["gate_logit"])[0]
            corrected = raw + gate * output["residual_classes"][0]
            decoder = monotonic_project(
                corrected,
                maximum=int(item["num_timestamp_labels"]) - 1,
            ).round()
            segment = float(item["timestamp_segment_sec"])
            for name, values in (("raw", raw), ("official", official), ("decoder", decoder)):
                errors = (values - target).abs()
                metric(totals, name, errors, segment)
                collapse[name] += int((values[1::2] <= values[0::2]).sum())
            slot_count += len(raw)
    elapsed = time.perf_counter() - started
    result = {
        "architecture": architecture,
        "item_count": len(items),
        "slot_count": slot_count,
        "split": sorted(wanted) if wanted else ["all_cached"],
        "wall_sec": elapsed,
        "slots_per_sec": slot_count / max(elapsed, 1e-9),
        "decoder_checkpoint": runtime.identity,
        "metrics": {
            name: {
                "boundary_mae_sec": totals[f"{name}_abs_sec_sum"] / max(1, slot_count),
                "within_0p08_rate": totals[f"{name}_within_0p08"] / max(1, slot_count),
                "within_0p16_rate": totals[f"{name}_within_0p16"] / max(1, slot_count),
                "nonpositive_duration_count": collapse[name],
            }
            for name in ("raw", "official", "decoder")
        },
    }
    atomic_json(args.out_dir / "metrics.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
