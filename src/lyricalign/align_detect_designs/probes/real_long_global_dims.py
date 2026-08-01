"""方向 B：真实 long 序列上的全局一致性维度（只读、纯 CPU）。

用 v3 formal baseline（已完成、静态只读）的 m4long characters 行验证：
1) global_shift_score（整首）与 global_shift_score_by_segments（按 window_index 分段）在
   真实 long 序列上的 flag 分布是否合理/健康（不崩、非全 no_data、有区分）。
2) 是否存在被「整首漏检但分段检出」的项（验证探针3 结论在真实数据上的体现）。
3) global_dims 对真实行字段（字符串值 / 'None' / 多窗口）的健壮性。

不占 GPU、不触发模型、只读 v3 baseline 目录，不触碰正在进行的 formal 写入。
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

BASELINE_ITEMS = "/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal_20260731_e9_lazy_compact_v3_gtintervalfix/baseline/items"


def _clean(value):
    """真实行把 None 存成字符串 'None'，转回 None，保留数值字段为 float/str 均可用。"""
    if value is None:
        return None
    s = str(value)
    if s.lower() in {"none", "nan", "null", ""}:
        return None
    return value


def load_characters(item_dir: str) -> list[dict]:
    cand = os.path.join(item_dir, "branches", "B4_60_silence_official", "alignment.json")
    if not os.path.isfile(cand):
        return []
    data = json.load(open(cand))
    chars = data.get("characters", [])
    out = []
    for c in chars:
        row = dict(c)
        for k, v in row.items():
            row[k] = _clean(v)
        if "global_character_index" in row:
            try:
                row["global_character_index"] = int(row["global_character_index"])
            except (TypeError, ValueError):
                continue
        out.append(row)
    return out


def run(limit: int = 40) -> int:
    items = sorted(
        (n for n in os.listdir(BASELINE_ITEMS) if n.startswith("m4long") and os.path.isdir(os.path.join(BASELINE_ITEMS, n)))
    )[:limit]

    whole_flags: Counter = Counter()
    seg_report_kinds: Counter = Counter()
    whole_miss_seg_hit = 0   # 整首非consistent 但某段consistent
    any_seg_consistent = 0
    loaded = 0
    n_windows_seg = 0
    for name in items:
        rows = load_characters(os.path.join(BASELINE_ITEMS, name))
        if not rows:
            continue
        loaded += 1
        whole = global_shift_score(pack_rows(rows))
        whole_flags[whole.flag] += 1

        key_by_window = lambda r: str(r.get("window_index", "?"))
        seg = global_shift_score_by_segments(pack_rows(rows), key_fn=key_by_window)
        seg_flags = {k: r.flag for k, r in seg.per_segment}
        n_windows_seg += len(seg_flags)
        for f in seg_flags.values():
            seg_report_kinds[f] += 1
        if any(f == "global_consistent_shift" for f in seg_flags.values()):
            any_seg_consistent += 1
        if whole.flag != "global_consistent_shift" and any(
            f == "global_consistent_shift" for f in seg_flags.values()
        ):
            whole_miss_seg_hit += 1

    print(f"=== 方向B 真实 long CPU 验证（读 {loaded}/{len(items)} 项, {limit} 上限） ===")
    print("整首 flag 分布:", dict(whole_flags))
    print("按 window 分段 flag 分布:", dict(seg_report_kinds))
    print(f"平均每项 window 数: {n_windows_seg / max(loaded,1):.1f}")
    print(f"出现【某段 consistent 偏移】的项: {any_seg_consistent}/{loaded}")
    print(f"整首漏检(file 但某段一致) 项: {whole_miss_seg_hit}/{loaded}")

    healthy = loaded > 0 and whole_flags["no_data"] <= loaded * 0.3
    print("结论：真实数据上全局维度健康可评估 =", healthy)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(run())
