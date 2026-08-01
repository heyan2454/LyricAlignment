"""方向 A 自洽探针：global_dims 纯函数的行为与叠加性（纯 CPU）。

验证：
1) global_shift_score 对基线=ambiguous、对 selected 整体漂移=global_consistent_shift、
   对局部失效=ambiguous（与探针2 结论一致）。
2) extend_features_with_global 能并入 extract_features 的输出，不改变原局部特征。
3) extend 后的 feature_rows 含有 global_consistent_shift 特征。
"""
from __future__ import annotations

from lyricalign.align_detect_designs.contracts import pack_rows
from lyricalign.align_detect_designs.global_dims import (
    extend_features_with_global,
    global_shift_score,
)
from lyricalign.align_detect_designs.probes.error_type_discrimination import (
    local_decay,
    make_rows,
)
from lyricalign.align_detect_designs.probes.global_shift_detector import selected_drift
from lyricalign.research_v6.detector import DetectorConfig, extract_features


def run() -> int:
    base = pack_rows(make_rows(20, start=0.0, step=0.5, dur=0.35))

    def flag(rows):
        return global_shift_score(rows).flag

    f_base = flag(base)
    f_drift = flag(selected_drift(base, 1.0))
    f_decay = flag(local_decay(base, (9, 11), "zero"))
    print("=== global_dims 行为（方向 A） ===")
    print(f"  基线           -> {f_base}")
    print(f"  selected漂移+1s -> {f_drift}")
    print(f"  局部失效3字     -> {f_decay}")

    ok1 = (f_base == "ambiguous" and f_drift == "global_consistent_shift" and f_decay == "ambiguous")

    # 叠加性：extract_features 后再 extend
    feats = extract_features(base, config=DetectorConfig())
    extended = extend_features_with_global(feats, base)
    assert len(extended) == len(feats) == 20
    g_keys = {"global_shift_mean_sec", "global_shift_spread_sec", "global_consistent_shift"}
    ok2 = all(g_keys.issubset(row) for row in extended)
    # 局部特征未被覆盖（抽查一个局部键仍存在）
    ok2 = ok2 and all("raw_negative_duration" in row and "raw_overlap_sec" in row for row in extended)
    print(f"  叠加后 global 特征存在={ok2}，每行含 global_shift_mean_sec/...")

    # extend 用漂流行应得到 global_consistent_shift=1，基线得到 0
    feats_drift = extend_features_with_global(extract_features(selected_drift(base, 1.0)), selected_drift(base, 1.0))
    feats_base = extend_features_with_global(feats, base)
    ok3 = all(row["global_consistent_shift"] == 1.0 for row in feats_drift) and \
          all(row["global_consistent_shift"] == 0.0 for row in feats_base)

    print("结论：行为=#{} 叠加=#{} 特征区分=#{}".format(ok1, ok2, ok3))
    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == "__main__":
    raise SystemExit(run())
