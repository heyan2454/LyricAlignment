#!/usr/bin/env python3
"""OpenCPOP → 字符级评测条目派生（只读标注；产 gzip evidence，供域外复评链消费）。

    # 句级视图（官方 3,756 段切段）
    PYTHONPATH=src python scripts/datasets/prepare_opencpop_items.py --view sentence \
        --out /home/hyan/Data/lyricalign/derived/20260924_opencpop_eval/evidence_sentence.jsonl.gz \
        --stats-out /home/hyan/Data/lyricalign/derived/20260924_opencpop_eval/STATS_sentence.json

    # 整曲 60s 窗口视图（物化裁剪音频后再跑）
    PYTHONPATH=src python scripts/datasets/prepare_opencpop_items.py --view window --max-sec 60 \
        --out .../evidence_window.jsonl.gz --stats-out .../STATS_window.json \
        --clip-dir .../windows60
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.datasets.opencpop import DEFAULT_ROOT, evidence_rows, sentence_items, window_items


def summarize(items: list[dict], extra: dict) -> dict:
    units = [u for item in items for u in item["units"]]
    durations = sorted(u.duration for u in units)
    text_kinds = Counter("hanzi" if "\u4e00" <= ch <= "\u9fff" else "other" for u in units for ch in u.text)
    at = lambda share: durations[min(len(durations) - 1, int(share * len(durations)))] if durations else None
    return {
        "items": len(items), "units": len(units),
        "songs": len({i["song"] for i in items}),
        "item_dur_sec": {"p50": _round(_median([i.get("audio_dur_sec", 0) for i in items])),
                          "max": _round(max((i.get("audio_dur_sec", 0) for i in items), default=0))},
        "units_per_item_p50": _round(_median([len(i["units"]) for i in items])),
        "unit_dur_sec": {"p10": _round(at(0.10)), "p50": _round(at(0.50)), "p90": _round(at(0.90)),
                          "max": _round(durations[-1]) if durations else None},
        "long_supply": {f">={s}s": sum(1 for d in durations if d >= s) for s in (1.0, 1.5, 2.0, 3.0)},
        "char_kinds": dict(text_kinds),
        **extra,
    }


def _median(values: list[float]) -> float | None:
    values = sorted(v for v in values if v)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def clip_windows(items: list[dict], clip_dir: Path) -> int:
    """把窗口音频物化到 clip_dir（16k mono，够评测用且省盘）。

    `-ss` 放在 `-i` **之后**（输出侧 seek）：输入侧 seek 对长文件可能带偏移，而窗口绝对时间
    平移后的字级 GT 必须与音频严格同基——偏移一旦进入就会污染域外绝对值（配对差虽不受影响）。
    切完再校验时长与预期一致，误差 >20 ms 直接失败，不静默放行。
    """
    clip_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    for item in items:
        target = clip_dir / f"{item['utt']}.wav"
        source = item["audio_path"]
        item["audio_path"] = str(target)
        if not target.exists():
            command = ["ffmpeg", "-v", "error", "-y", "-i", source,
                       "-ss", str(item["window_start_sec"]), "-t", str(item["audio_dur_sec"]),
                       "-ac", "1", "-ar", "16000", str(target)]
            subprocess.run(command, check=True)
            made += 1
        import wave
        with wave.open(str(target), "rb") as handle:
            actual = handle.getnframes() / float(handle.getframerate())
        if abs(actual - item["audio_dur_sec"]) > 0.02:
            raise SystemExit(f"{target.name}: 裁剪时长 {actual:.3f} 与预期 {item['audio_dur_sec']:.3f} 不一致")
    return made


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--view", choices=("sentence", "window"), required=True)
    parser.add_argument("--max-sec", type=float, default=60.0)
    parser.add_argument("--min-units", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stats-out", type=Path, required=True)
    parser.add_argument("--clip-dir", type=Path, default=None, help="window 视图需要物化裁剪音频时给出")
    args = parser.parse_args()

    if args.view == "sentence":
        items, extra = sentence_items(args.root)
    else:
        items, extra = window_items(args.root, max_sec=args.max_sec, min_units=args.min_units)
        if args.clip_dir:
            extra = {**extra, "clips_materialized": clip_windows(items, args.clip_dir)}
    if args.limit:
        items = items[:args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as handle:
        for row in evidence_rows(items):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats = summarize(items, extra)
    stats["view"] = args.view
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()
