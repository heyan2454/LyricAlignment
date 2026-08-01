"""探针 3：分段漂移 vs 整首漂移 —— 全局维度该在什么粒度上算？

背景：探针2/方向A 的全球一致性评分在“整段均匀漂移”下工作良好。
但长序列（如 ~150s、多窗口）更可能发生的是**分段漂移**：不同窗口/段各有不同（或相反）的
整体偏移。此时对整首只算一个 global_shift_score 会因 mean 相互抵消/同向占比下降而漏检。
本探针验证：若把全局评分**按段（window）分别计算**，能正确检出每段内部的一致偏移，
从而确认 global_dims 需要 per-window/per-segment 版本（粒度是结构问题）。

纯 CPU；用探针1/2 的合成行 + 分两段造漂移。不占 GPU、不碰 production。
"""
from __future__ import annotations

from lyricalign.align_detect_designs.contracts import pack_rows
from lyricalign.align_detect_designs.global_dims import (
    global_shift_score,
    global_shift_score_by_segments,
)
from lyricalign.align_detect_designs.probes.error_type_discrimination import make_rows


def segment_des(rows, segments: list[tuple[tuple[int, int], float]]) -> list[dict]:
    """对 segments: ((char_lo,char_hi), delta_sec) 的每一段做整体平移。"""
    out = [dict(r) for r in rows]
    for (lo, hi), delta in segments:
        for r in out:
            i = int(r["global_character_index"])
            if lo <= i <= hi:
                for k in ("start_sec", "end_sec", "selected_start_sec", "selected_end_sec"):
                    if r.get(k) is not None:
                        r[k] = float(r[k]) + delta
    return pack_rows(out)


def run() -> int:
    n = 16
    base = pack_rows(make_rows(n, start=0.0, step=0.5, dur=0.35))
    half = n // 2  # 8
    # 两段相反漂移：前段+1s，后段-1s（均值相抵，整首一致性会被稀释）
    two_seg = segment_des(base, [((0, half - 1), 1.0), ((half, n - 1), -1.0)])
    # 两段同向但幅度不同：前+1s、后+0.5s（整首仍偏正，但 spread 变大）
    graded = segment_des(base, [((0, half - 1), 1.0), ((half, n - 1), 0.5)])

    def flag(rows):
        return global_shift_score(rows).flag

    whole_two = flag(two_seg)
    whole_graded = flag(graded)

    def seg_flags(rows):
        return (
            global_shift_score(pack_rows([r for r in rows if int(r["global_character_index"]) < half])).flag,
            global_shift_score(pack_rows([r for r in rows if int(r["global_character_index"]) >= half])).flag,
        )

    seg_two = seg_flags(two_seg)
    seg_graded = seg_flags(graded)

    print("=== 分段漂移粒度探针（纯 CPU） ===")
    print(f"两段相反(+1/-1)：整首={whole_two:24} 分段={seg_two}")
    print(f"两段同向(1/0.5)：整首={whole_graded:24} 分段={seg_graded}")

    # 期望：分段计算能检出每段漂移；整首对“相反段”漏检
    ok_seg_two = (seg_two == ("global_consistent_shift", "global_consistent_shift"))
    ok_whole_two_miss = (whole_two != "global_consistent_shift")
    ok_graded = (seg_graded == ("global_consistent_shift", "global_consistent_shift"))
    print("\n结论：分段计算能检出 相反段={} 同向段={}；整首对相反段会漏检={}"
          .format(ok_seg_two, ok_graded, ok_whole_two_miss))

    # 追加验证：global_shift_score_by_segments API（探针3 结论的编码实现）
    key_by_half = lambda row: "a" if int(row["global_character_index"]) < half else "b"
    gr = global_shift_score_by_segments(two_seg, key_fn=key_by_half)
    flags = gr.per_segment
    by = {k: r.flag for k, r in flags}
    ok_api = all(v == "global_consistent_shift" for v in by.values()) and len(by) == 2
    # char_to_segment 映射应可查到具体字符属于哪段并给出其段 flag
    idx0 = gr.flag_for_index(0)
    idx_last = gr.flag_for_index(n - 1)
    ok_map = (idx0 == "global_consistent_shift") and (idx_last == "global_consistent_shift")
    print(f"API by_segments: flags={by} 映射(0/th)={idx0}/{idx_last} -> ok={ok_api and ok_map}")

    return 0 if (ok_seg_two and ok_whole_two_miss and ok_graded and ok_api and ok_map) else 1


if __name__ == "__main__":
    raise SystemExit(run())
