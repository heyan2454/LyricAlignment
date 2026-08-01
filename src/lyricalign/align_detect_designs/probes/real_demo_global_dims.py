"""方向 F（CPU 版）：真实多窗 demo 上的全局一致性维度验证。

用 v3 baseline 的真实 demo 多窗项（characters 含 window_index 0..n，多窗齐全），
CPU 只读验证：
1) global_shift_score（整首）与 global_shift_score_by_segments（按 window_index 分段）
   在真实多窗行上的 flag 分布是否合理、无崩溃、非全 no_data。
2) 是否存在「整首漏检但某 window 检出一致偏移」的项（检验探针3结论在真实数据）。
3) global_dims 对真实行字段（str 值/'None'/多窗口）的健壮性。

纯只读 v3 baseline；不触发模型、不占用 GPU、不触碰正在进行的任何进程。
"""
from __future__ import annotations

import json
import os
from collections import Counter

from lyricalign.align_detect_designs.contracts import pack_rows
from lyricalign.align_detect_designs.global_dims import (
    global_shift_score,
    global_shift_score_by_segments,
)

BASELINE = "/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal_20260731_e9_lazy_compact_v3_gtintervalfix/baseline/items"


def _clean(v):
    if v is None:
        return None
    s = str(v)
    if s.lower() in {"none", "nan", "null", ""}:
        return None
    return v


def load_demo_characters(item_dir: str) -> list[dict]:
    cand = os.path.join(item_dir, "branches", "B4_60_silence_official", "alignment.json")
    if not os.path.isfile(cand):
        return []
    data = json.load(open(cand))
    out = []
    for c in data.get("characters", []):
        row = {k: _clean(v) for k, v in c.items()}
        try:
            row["global_character_index"] = int(row.get("global_character_index"))
        except (TypeError, ValueError):
            continue
        out.append(row)
    return out


def run(limit: int = 30) -> int:
    items = sorted(
        n for n in os.listdir(BASELINE) if n.startswith("demo_") and os.path.isdir(os.path.join(BASELINE, n))
    )[:limit]

    whole_flags: Counter = Counter()
    seg_flags_all: Counter = Counter()
    multi_win = 0
    miss_seg_hit = 0
    any_seg_consist = 0
    loaded = 0
    for name in items:
        rows = load_demo_characters(os.path.join(BASELINE, name))
        if not rows:
            continue
        loaded += 1
        win_dist = {int(r.get("window_index", -1)) for r in rows}
        if len(win_dist) >= 2:
            multi_win += 1
        whole = global_shift_score(pack_rows(rows))
        whole_flags[whole.flag] += 1
        seg = global_shift_score_by_segments(pack_rows(rows), key_fn=lambda r: str(r.get("window_index", "?")))
        flags = {k: r.flag for k, r in seg.per_segment}
        for f in flags.values():
            seg_flags_all[f] += 1
        if any(f == "global_consistent_shift" for f in flags.values()):
            any_seg_consist += 1
        if whole.flag != "global_consistent_shift" and any(f == "global_consistent_shift" for f in flags.values()):
            miss_seg_hit += 1

    print(f"=== 方向F CPU：真实 demo 多窗全局一致性（读 {loaded}/{len(items)}） ===")
    print("多窗项:", multi_win)
    print("整首 flag 分布:", dict(whole_flags))
    print("按 window 分段 flag 分布:", dict(seg_flags_all))
    print(f"出现某 window 一致偏移 项: {any_seg_consist}/{loaded}")
    print(f"整首漏检但某 window 检出 项: {miss_seg_hit}/{loaded}")

    healthy = loaded > 0 and whole_flags["no_data"] <= loaded * 0.5
    print("真实多窗数据上可评估 =", healthy)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(run())
