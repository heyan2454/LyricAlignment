"""探针 6：期望节奏参照能否补上探针5 的『整体放慢无感』盲区（纯 CPU）。

对探针5 的慢变/快变/基线行，用 expected_ref.tempo_ref_score 给定 request 提供的
total_units/duration_sec，期望节奏与实测速率比出 slow/fast/normal。

期望：慢变→slow（探针5 盲区被补上）、快变→fast、基线→normal（不误报）。
"""
from __future__ import annotations

from lyricalign.align_detect_designs.expected_ref import tempo_ref_score
from lyricalign.align_detect_designs.probes.tempo_shift_blindspot import make_tempo_rows


def run() -> int:
    n = 24
    base = make_tempo_rows(n, start=0.0, base_rate=0.5, pivot=None)
    slow = make_tempo_rows(n, start=0.0, base_rate=0.5, pivot=n // 2, factor=2.0)
    fast = make_tempo_rows(n, start=0.0, base_rate=0.5, pivot=n // 2, factor=0.25)

    # 期望时长是**外部先验**（request/window 的计划，独立于被测输出）：
    # 正常节奏 base_rate=0.5 下，末字符应有 start=(n-1)*0.5、end=+0.3 → 先验末字符时间。
    pri_norm = (n - 1) * 0.5 + 0.3

    print("=== 期望节奏参照探针（纯 CPU） ===")
    for name, rows in [("基线", base), ("慢变×2", slow), ("快变×0.25", fast)]:
        # 外部先验时长固定为 pri_norm（正常节奏下应有的时长），与行自身末时间不同源
        rep = tempo_ref_score(rows, total_units=n, duration_sec=pri_norm)
        print(f"{name:12} expected={rep.expected_rate:.3f}/s measured={rep.measured_rate:.3f}/s "
              f"ratio(meas/exp)={rep.ratio:<8} flag={rep.flag}")

    f_slow = tempo_ref_score(slow, total_units=n, duration_sec=pri_norm).flag
    f_base = tempo_ref_score(base, total_units=n, duration_sec=pri_norm).flag
    f_fast = tempo_ref_score(fast, total_units=n, duration_sec=pri_norm).flag
    ok = (f_base in ("normal", "fast") and f_slow == "slow" and f_fast == "fast")
    print("\n慢变→slow(补盲区) 基线→normal 快变→fast 成立 =", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
