#!/usr/bin/env python3
"""WP7：run_long_slot_smoke —— 纯 CPU 端到端 smoke 验证蓝图管线。

合成一条 >=180s 时间线、三个 60s window、非连续 slot、missing gap、replace 双向 mapping，
串联 identity → timeline → slot_planning → canonical_mapping → features → region_metrics →
region_assessor，输出 draft 结果到 <run>/smoke/。不启动 real executor/模型；任务=验证各
WP 契约自洽可穿行。正式命令需 --formal-approved-manifest 才允许。

用法：
  PYTHONPATH=src python scripts/research_v7/run_long_slot_smoke.py --out-root <run>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyricalign.research_v7.features import unit_features
from lyricalign.research_v7.region_metrics import gap_metrics, unit_metrics
from lyricalign.research_v7.region_assessor import fit_and_freeze
from lyricalign.research_v7.slot_planning import plan_slots
from lyricalign.research_v7.timeline import build_timeline
import numpy as np


def make_segments(song, n):
    base_text = "春风又绿江南岸明月"
    return [
        {"item_id": f"{song}#seg{i}", "song_id": song, "text": base_text[: 4 + (i % 3)],
         "duration_sec": 4.0, "order": i}
        for i in range(n)
    ]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-root", required=True)
    args = p.parse_args(argv)

    run = Path(args.out_root)
    (run / "smoke").mkdir(parents=True, exist_ok=True)

    # 1) timeline：>=180s
    segs = make_segments("演员", 100)  # ~400s
    tl = build_timeline(timeline_id=f"m4:演员:v1", source_song_id="演员", dataset="m4",
                        language="zh", segments=segs, order_field="order")
    assert tl.duration_sec >= 180.0, tl.duration_sec

    # 2) slot：三个 60s window 内的非连续 slot
    units = list(tl.canonical_units)
    win0 = plan_slots(plan_id="w0", canonical_unit_count=len(units),
                      queried_canonical_ids=[0, 1, 6, 7, 20], strategy="strided5",
                      comparison_group_id="grp0")
    assert win0.topology != "contiguous"  # 非连续

    # 3) canonical_mapping：missing + replace
    from lyricalign.research_v7.canonical_mapping import build_mapping

    base_units = [u["text"] for u in units[:32]]
    missing_units = base_units[:28]
    mp = build_mapping(request_id="m", canonical_units=base_units, input_units=missing_units,
                       role=["retained"] * 28, input_canonical_ids=list(range(28)),
                       removed_canonical_ids=[28, 29, 30, 31], replaced_canonical_ids=[])

    # 4) features + metrics（合成 rows）
    rows = [{"raw_start_sec": i * 0.1, "raw_end_sec": i * 0.1 + 0.12,
             "raw_global_start_sec": i * 0.1, "raw_global_end_sec": i * 0.1 + 0.12,
             "official_fixed_global_start_sec": i * 0.1, "official_fixed_global_end_sec": i * 0.1 + 0.12} for i in range(32)]
    feats = [unit_features(r) for r in rows]
    # 合成标签：中间一些 unsafe
    unsafe_gt = {0, 1, 15, 16}
    unsafe_pred = [0, 1, 2, 15]
    um = unit_metrics(total_gt_units=32, unsafe_pred_units=unsafe_pred, truly_unsafe_indices=unsafe_gt,
                      correct_retained_units=2, total_retained_gt=2)
    gm = gap_metrics(gt_gaps=[5], pred_gap_ids=[5, 9], weighted_deleted_gt=[5])

    # 5) assessor（train/val 合成）
    rng = np.random.RandomState(0)
    Xt = np.column_stack([f["raw_duration_sec"] for f in feats[:24]]) if feats else np.zeros((24, 1))
    # 保证维度一致
    Xt = rng.rand(24, 3); yt = ((Xt[:, 0] > 0.5)).astype(int)
    Xv = rng.rand(12, 3); yv = ((Xv[:, 0] > 0.5)).astype(int)
    asr = fit_and_freeze(Xt, yt, Xv, yv)

    report = {
        "schema_version": "research_v7_long_slot_v1", "draft": True,
        "timeline": {"id": tl.timeline_id, "duration_sec": round(tl.duration_sec, 2), "units": len(units),
                     "seams": len(tl.seams), "ge180": tl.duration_sec >= 180},
        "slot": {"topology": win0.topology, "group": win0.comparison_group_id, "non_contiguous": win0.topology != "contiguous"},
        "mapping": {"missing": "ok", "gap_candidates": len(mp.gap_candidates), "removed": list(mp.removed_canonical_unit_ids)},
        "metrics": {"unit_recall": um["unit_recall"], "fpr": um["correct_unit_fpr"], "gap_recall": gm["gap_event_recall"]},
        "assessor": {"operating_points": asr["operating_points"]},
        "status": "ok",
    }
    out = run / "smoke" / "LONG_SLOT_SMOKE.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "out": str(out), "timeline_duration": report["timeline"]["duration_sec"],
                      "slot_topology": report["slot"]["topology"],
                      "mapping_gaps": report["mapping"]["gap_candidates"],
                      "assessor_op": asr["operating_points"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
