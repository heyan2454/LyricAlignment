"""探针 5：时间去尺度盲区 —— detector 能否感知「整段节奏慢/快不一致」？

方向：detector 特征是“局部曲率+局部 rate_z”，其 local_rate_z 衡量相邻时长相对局部中位数
的离群程度。若后半段**整体**放慢/变快（step 变大/变小但单调、无重叠/零时长/回归），
局部仍“一致”，rate_z 未必升高 → 潜在盲区：detector 无“整首/分段节奏参考”。

本探针合成 3 类行：
- 基线：均匀 step。
- 慢变：中段起 step 增大（整体放慢但单调无异常）。
- 快变：中段起 step 减小。
对每类跑 rule_risk_score，比较中段前后 risk 分布 / 是否出现 peaks。

纯 CPU、纯几何、无模型。用于判断 detector 是否需要“节奏参考”这一类结构维度。
"""
from __future__ import annotations

import statistics
from typing import Sequence

from lyricalign.align_detect_designs.contracts import pack_rows
from lyricalign.research_v6.detector import DetectorConfig, extract_features, rule_risk_score


def make_tempo_rows(n: int, *, start: float, base_rate: float, pivot: int | None,
                    factor: float = 2.0) -> list[dict]:
    """构造行：pivot 之后节奏按因子缩放（仍单调递增、无局部破坏）。"""
    rows = []
    t = start
    rate = base_rate
    for i in range(n):
        e = t + 0.3
        rows.append({
            "global_character_index": i,
            "character_index": i,
            "raw_global_start_sec": t,
            "raw_global_end_sec": e,
            "official_fixed_global_start_sec": t,
            "official_fixed_global_end_sec": e,
            "start_sec": t,
            "end_sec": e,
            "raw_start_margin": 0.5,
            "raw_end_margin": 0.5,
            "raw_start_entropy": 0.1,
            "raw_end_entropy": 0.1,
        })
        if pivot is not None and i >= pivot - 1:
            rate = base_rate * factor
        t += rate
    return pack_rows(rows)


def risk_series(rows: Sequence[dict], cfg: DetectorConfig) -> list[float]:
    feats = extract_features(rows, config=cfg)
    return [rule_risk_score(f) for f in feats]


def run() -> int:
    cfg = DetectorConfig(rate_window_units=5, rate_z_threshold=3.0, short_duration_sec=0.15, long_duration_sec=0.9)
    n = 24
    base = make_tempo_rows(n, start=0.0, base_rate=0.5, pivot=None)
    slow = make_tempo_rows(n, start=0.0, base_rate=0.5, pivot=n // 2, factor=2.0)   # 后段放慢
    fast = make_tempo_rows(n, start=0.0, base_rate=0.5, pivot=n // 2, factor=0.25)  # 后段变快

    rb = risk_series(base, cfg)
    rs = risk_series(slow, cfg)
    rf = risk_series(fast, cfg)

    def stats(name, s):
        mid = s[n // 2:]
        return f"{name:12} mean(全部)={statistics.fmean(s):.3f} 后段mean={statistics.fmean(mid):.3f} 后段max={max(mid):.3f} 后段>0.5数={sum(1 for v in mid if v>0.5)}"

    print("=== 时间尺度（节奏漂移）盲区探针（纯 CPU） ===")
    print(stats("基线", rb))
    print(stats("慢变(×2)", rs))
    print(stats("快变(×0.25)", rf))

    # 判据：若 detector 对节奏漂移“无感”，则慢/快变的后段 risk 不应显著高于基线；
    # 若“有感”，则应有明显 peak。我们报告差异，直接看。
    def late_diff(b, x):
        return statistics.fmean(x[n // 2:]) - statistics.fmean(b[n // 2:])

    d_slow = round(late_diff(rb, rs), 3)
    d_fast = round(late_diff(rb, rf), 3)
    print(f"\n后段相对基线 risk 差：慢变={d_slow:+} 快变={d_fast:+}")
    # “盲区”定义：|差|<0.25 即几乎无感知（可作为 detector 需要节奏参考的证据）
    blind_slow = abs(d_slow) < 0.25
    blind_fast = abs(d_fast) < 0.25
    print("慢变动变速几乎无感（潜在盲区）=", blind_slow and blind_fast)
    return 0 if (blind_slow and blind_fast) else 1


if __name__ == "__main__":
    raise SystemExit(run())
