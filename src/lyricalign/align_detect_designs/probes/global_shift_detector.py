"""微探针 2：能否用一个「无 GT、纯几何」的全局一致性评分检出「整体一致偏移」？

探针 1 结论：当前 detector 特征全是局部“曲率/边际”，对全局均匀平移完全免疫（risk=0）。
本探针尝试构造一个全局维度：
- 对每个字符，取 raw 与 “无偏移参考”（如当前 selected/起始锚点）之间的边界差异 dx_i；
- 若 dx_i 在所有字符上**同向、量级相近**（low spread / high一致方向），则判为“整体偏移”；
- 若差异只集中在个别字符，则判为“局部异常”（应归给探针1的局部机制）。

这不需要 GT：仅用 raw 与 selected 的差异分布。合成行仍为纯几何。纯 CPU，无模型，不碰 production。

运行：PYTHONPATH=src python -m lyricalign.align_detect_designs.probes.global_shift_detector
"""
from __future__ import annotations

import statistics
from typing import Sequence

from lyricalign.align_detect_designs.probes.error_type_discrimination import (
    local_decay,
    make_rows,
)
from lyricalign.align_detect_designs.contracts import pack_rows


def selected_drift(rows: Sequence[dict], delta_sec: float) -> list[dict]:
    """只把 selected/start 侧整体漂移 delta，raw 不动。

    模拟“最终对齐输出相对底层测量(raw)整体错开”，使 raw−selected 差向量整体同向。
    （探针1 的 global_shift 是 raw 与 selected 一起平移，故 detctorure 检测不到；
     本探针制造“输出整体漂移”这一真实结构情形。）
    """
    out = []
    for r in rows:
        r = dict(r)
        for k in ("start_sec", "end_sec","selected_start_sec","selected_end_sec"):
            if r.get(k) is not None:
                r[k.replace("selected_","") if False else k] = float(r[k]) + delta_sec
        out.append(r)
    return pack_rows(out)


def global_offset_score(rows: Sequence[dict], *, ref: str = "selected") -> dict:
    """无 GT 的全局偏移一致性评分。

    对每字符算 raw_start 与 ref_start 的差 time差异，并统计其均值和 spread：
    - 若所有字符差异同向且集中（|mean| 大、spread 小）→ 疑似整体一致偏移；
    - 若差异散乱/个别集中 → 非整体偏移。
    """
    diffs: list[tuple[int, float]] = []
    for r in rows:
        raw = r.get("raw_global_start_sec")
        if ref == "selected":
            base = r.get("start_sec", r.get("selected_start_sec"))
        elif ref == "previous_anchor":
            base = r.get("raw_global_start_sec") - r.get("start_sec", 0.0)
        else:
            base = r.get(ref)
        if raw is None or base is None:
            continue
        diffs.append((int(r["global_character_index"]), float(raw) - float(base)))
    if not diffs:
        return {"mean": 0.0, "spread": 0.0, "n": 0, "flag": "no_data"}

    vals = [d for _, d in diffs]
    mean = statistics.fmean(vals)
    # spread：绝对离差中位数（对离群更稳）
    spread = statistics.median(abs(v - mean) for v in vals)
    n_right = sum(1 for v in vals if v > 0)
    n_left = sum(1 for v in vals if v < 0)
    consistency = max(n_right, n_left) / len(vals)  # 同向占比
    # 判定：整体偏移 → 均值显著 + 离差小(集中) + 同向占比高
    flag = (
        "global_consistent_shift"
        if abs(mean) > 0.4 and spread < 0.15 and consistency >= 0.9
        else ("local_only" if spread > 0.4 else "ambiguous")
    )
    return {"mean": round(mean, 3), "spread": round(spread, 3), "n": len(vals),
            "consistency_right": round(consistency, 3), "flag": flag}


def run() -> int:
    base = pack_rows(make_rows(20, start=0.0, step=0.5, dur=0.35))

    def show(name, rows):
        s = global_offset_score(rows)
        print(f"{name:22} mean={s['mean']:>7} spread={s['spread']:>6} right%={s['consistency_right']:>6} flag={s['flag']}")
        return s

    print("=== 全局偏移一致性探针（无 GT，纯 CPU） ===")
    s0 = show("正确基线", base)
    s1 = show("selected 整体漂移 +1s", selected_drift(base, 1.0))
    s2 = show("局部失效3字", local_decay(base, (9, 11), "zero"))

    # 期望：全局偏移 → global_consistent_shift；基线→非偏移；局部→local_only
    ok = (
        s1["flag"] == "global_consistent_shift"
        and s0["flag"] != "global_consistent_shift"
        and s2["flag"] != "global_consistent_shift"
    )
    print("\n结论：全局偏移可被无 GT 几何信号专门检出 =", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
