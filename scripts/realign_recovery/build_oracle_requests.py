#!/usr/bin/env python3
"""E1 oracle REPAIR 请求构建 CLI（纯 CPU，不做推理）。

从 LABELS.jsonl（label=="unsafe" && gt_unavailable==false 的真实确认灾难区段）出发，
经 select_catastrophic_regions 选出 oracle 区域，再由 build_oracle_requests 写
research_v7 兼容的 no-GT REQUESTS.jsonl（每 region x mode 一行，含 provenance）。

额外产物（均在 --out 同目录）：
- REGIONS.json：OracleRegion.to_dict() 序列化，供审计 / evaluate 对照；
- NO_GT_CHECK.json：逐行 validate_no_gt_request 校验结果 {n_rows, violations: []}。

纯 CPU，不加载模型；正式 GPU forward 由 scripts/research_v7/run_behavior_suite.py --real 消费。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request  # noqa: E402
from lyricalign.realign_recovery.oracle import (  # noqa: E402
    ORACLE_MODES_SEC,
    build_oracle_requests,
    select_catastrophic_regions,
)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--labels", required=True, help="LABELS.jsonl（unsafe 标记真实确认）")
    p.add_argument("--timeline-manifest", required=True, help="LONG_TIMELINE_MANIFEST.jsonl")
    p.add_argument("--out", required=True, help="REQUESTS.jsonl 输出路径（同目录写 REGIONS.json / NO_GT_CHECK.json）")
    p.add_argument("--modes", default="O0,O1,O2,O3", help="oracle 模式，逗号分隔（默认全部）")
    p.add_argument("--audio-extra-sec", type=float, default=None, help="覆盖 mode 的音频扩展秒数")
    p.add_argument("--text-extra-units", type=int, default=0, help="文本单轴扩展邻居 unit 数")
    p.add_argument("--min-region-units", type=int, default=1, help="region 最小 unit 数过滤")
    p.add_argument("--model-id", default="Qwen3-ForcedAligner-0.6B-hf", help="默认同 oracle.py")
    p.add_argument("--checkpoint-id", default="r2-step-000750", help="默认同 oracle.py")
    args = p.parse_args(argv)

    modes = tuple(m.strip() for m in args.modes.split(",") if m.strip())
    unknown = [m for m in modes if m not in ORACLE_MODES_SEC]
    if unknown:
        raise SystemExit(f"未知 oracle mode: {unknown}（可用 {sorted(ORACLE_MODES_SEC)}）")

    regions = select_catastrophic_regions(
        args.labels, args.timeline_manifest, min_units_per_region=args.min_region_units)

    rows, out_path = build_oracle_requests(
        regions, args.timeline_manifest, args.out,
        modes=modes,
        audio_extra_sec=args.audio_extra_sec,
        text_extra_units=args.text_extra_units,
        model_id=args.model_id,
        checkpoint_id=args.checkpoint_id,
    )

    out_dir = Path(out_path).parent
    reg_path = out_dir / "REGIONS.json"
    reg_path.write_text(
        json.dumps([r.to_dict() for r in regions], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    violations = []
    for row in rows:
        found = validate_no_gt_request(row)
        if found:
            violations.append({"request_id": row.get("request_id"), "fields": sorted(found)})
    no_gt = {"n_rows": len(rows), "violations": violations}
    ng_path = out_dir / "NO_GT_CHECK.json"
    ng_path.write_text(json.dumps(no_gt, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    per_song = defaultdict(lambda: {"regions": 0, "units": 0})
    for r in regions:
        per_song[r.song_id]["regions"] += 1
        per_song[r.song_id]["units"] += len(r.unit_ids)
    per_mode = Counter(row.get("provenance", {}).get("mode") or row.get("input_variant") for row in rows)

    print(json.dumps({
        "ok": True,
        "n_regions": len(regions),
        "n_request_rows": len(rows),
        "per_song": {s: v for s, v in per_song.items()},
        "per_mode": dict(per_mode),
        "regions_json": str(reg_path),
        "no_gt_check": no_gt,
        "out": out_path,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
