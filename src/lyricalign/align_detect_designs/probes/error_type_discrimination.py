"""微探针：当前 detector 能否在特征层区分两类结构错误？

假设（结构性探索，非调参）：
- 「全局偏移型」错误：整段边界整体平移（窗口/歌词错位所致），所有字符 margin/movement 近似恒定。
- 「局部 decoder 失效型」错误：个别字符 raw 时长异常（零时长/重叠/回归），其余正常。

若 detector 的 risk 模式能明显区分两者，则说明框架可进一步让 detector 从「标风险」
升级为「归因·全局错位 vs 局部崩坏」，支撑自适应分割等结构改造；若不能，则需在特征层补
全局一致性维度。这是微型 CPU smoke，不涉及模型/GPU。

用法：PYTHONPATH=src python -m lyricalign.align_detect_designs.probes.error_type_discrimination
"""
from __future__ import annotations

from typing import Callable, Sequence

from lyricalign.research_v6.detector import DetectorConfig, extract_features, rule_risk_score
from lyricalign.align_detect_designs.contracts import pack_rows

# --------------------------------------------------------------------------- #
# 合成行构造（纯几何，无真实 logits；足以驱动 extract_features）
# --------------------------------------------------------------------------- #


def make_rows(n: int, start: float, step: float, dur: float) -> list[dict]:
    rows = []
    for i in range(n):
        s = start + i * step
        e = s + dur
        rows.append(
            {
                "global_character_index": i,
                "character_index": i,
                "raw_global_start_sec": s,
                "raw_global_end_sec": e,
                "official_fixed_global_start_sec": s,
                "official_fixed_global_end_sec": e,
                "start_sec": s,
                "end_sec": e,
                "raw_start_margin": 0.5,
                "raw_end_margin": 0.5,
                "raw_start_entropy": 0.1,
                "raw_end_entropy": 0.1,
            }
        )
    return rows


def global_shift(rows: Sequence[dict], delta_sec: float) -> list[dict]:
    """全局均匀偏移：模拟窗口/歌词错位（边界整体平移）。"""
    out = []
    for r in rows:
        r = dict(r)
        for k in ("raw_global_start_sec", "official_fixed_global_start_sec", "start_sec"):
            r[k] = float(r[k]) + delta_sec
        for k in ("raw_global_end_sec", "official_fixed_global_end_sec", "end_sec"):
            r[k] = float(r[k]) + delta_sec
        out.append(r)
    return pack_rows(out)


def local_decay(rows: Sequence[dict], span: tuple[int, int], mode: str = "zero") -> list[dict]:
    """局部 decoder 失效：把 span 内字符 raw 时长压坏。"""
    out = [dict(r) for r in rows]
    lo, hi = span
    for r in out:
        i = int(r["global_character_index"])
        if lo <= i <= hi:
            if mode == "zero":
                r["raw_global_end_sec"] = float(r["raw_global_start_sec"])  # 零时长
                r["end_sec"] = float(r["start_sec"])
            elif mode == "overlap":
                r["raw_global_start_sec"] = float(r["raw_global_start_sec"]) - 0.2  # 与前重叠
            elif mode == "regress":
                r["raw_global_end_sec"] = float(r["raw_global_start_sec"]) - 0.1  # 逆序
    return pack_rows(out)


# --------------------------------------------------------------------------- #
# 判定工具
# --------------------------------------------------------------------------- #


def score_rows(rows: Sequence[dict], config: DetectorConfig) -> list[tuple[int, float]]:
    feats = extract_features(rows, config=config)
    return [(int(f["global_character_index"]), float(rule_risk_score(f))) for f in feats]


def summarize(scores: list[tuple[int, float]], *, label: str) -> dict:
    vals = [s for _, s in scores]
    mean = sum(vals) / len(vals) if vals else 0.0
    maxv = max(vals) if vals else 0.0
    nz = sum(1 for s in vals if s > 0.5)
    return {"label": label, "mean": round(mean, 3), "max": round(maxv, 3), "n_high(>0.5)": nz}


def run() -> int:
    cfg = DetectorConfig(short_duration_sec=0.15, long_duration_sec=0.9)
    n = 20
    base = pack_rows(make_rows(n, start=0.0, step=0.5, dur=0.35))

    correct = score_rows(base, cfg)
    shifted = score_rows(global_shift(base, delta_sec=1.0), cfg)
    decay = score_rows(local_decay(base, span=(9, 11), mode="zero"), cfg)

    def spread(s: list[tuple[int, float]]) -> float:
        v = [x for _, x in s]
        return max(v) - min(v) if v else 0.0

    print("=== 结构错误判别探针（纯 CPU） ===")
    for name, s in [("正确基线", correct), ("全局偏移(+1s)", shifted), ("局部失效(中段3字zero)", decay)]:
        sm = summarize(s, label=name)
        print(f"{name:24} mean={sm['mean']:>6} max={sm['max']:>6} high(>0.5)={sm['n_high(>0.5)']:>3} spread={spread(s):.3f}")

    # 区分判据：全局偏移应是「平稳低分+小 spread」（结构一致，唯 margin 恒定），
    # 局部失效应是「少数高分+大 spread」（峰值集中某处）。
    spread_shift = spread(shifted)
    spread_decay = spread(decay)
    peak_decay = max(s for _, s in decay)
    shifted_max = max(s for _, s in shifted)
    separable = (
        peak_decay > shifted_max + 0.5
        and spread_decay > spread_shift + 0.5
        and summarize(shifted, label="shift")["n_high(>0.5)"] <= 1
    )
    print()
    print("结论：局部失效 vs 全局偏移 在当前 rule_risk_score 特征下可区分 =", separable)
    return 0 if separable else 1


if __name__ == "__main__":
    raise SystemExit(run())
