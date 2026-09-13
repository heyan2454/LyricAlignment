#!/usr/bin/env python3
"""Fit error against training exposure, then predict what the oversampling arm *should* achieve.

The night's evidence says long characters fail because they are rare (≥2 s is 0.9% of the training
signal but 12.4% of the misses).  "Rare causes failure" is qualitative; this makes it quantitative by
fitting log(miss rate) against log(exposure share) over duration buckets, and then turning the planned
sampling change into a **number to beat**:

    predicted miss rate after oversampling = miss_rate * (exposure_gain) ** slope

If arm B lands near the prediction, the exposure story explains the effect size; if it lands far below,
something else is the bottleneck; if it does not move at all, the exposure story is wrong even though
the correlation looked convincing.  Registering this before the arms finish is the point.

    PYTHONPATH=src python scripts/evaluation/exposure_response_fit.py \
        --labels /home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl \
        --dump results/by_run/20260914_long_mech_old750/per_character.jsonl \
        --split train --out results/by_run/20260914_exposure_fit/metrics.json \
        --report docs/status/20260914_exposure_prediction.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

EDGES = (0.0, 0.25, 0.5, 1.0, 2.0, 99.0)
TOL = 0.2


def bucket_name(low: float, high: float) -> str:
    return f"{low:g}-{high:g}s" if high < 99 else "2s+"


def buckets() -> list[tuple[float, float]]:
    return list(zip(EDGES[:-1], EDGES[1:]))


def exposure_shares(labels_path: Path, split: str) -> dict[str, float]:
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("split") != split:
            continue
        classes = row.get("timestamp_class_ids") or []
        step = float(row.get("timestamp_segment_sec", 0.08))
        for index in range(len(classes) // 2):
            duration = (classes[2 * index + 1] - classes[2 * index]) * step
            for low, high in buckets():
                if low <= duration < high:
                    counts[bucket_name(low, high)] += 1
                    total += 1
                    break
    return {name: counts[name] / total for name in counts} if total else {}


def miss_rates(dump_path: Path) -> dict[str, float]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in dump_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
    buckets_data: dict[str, list[int]] = defaultdict(list)
    for kinds in per.values():
        if len(kinds) != 2:
            continue
        duration = float(kinds["onset"]["duration"])
        error = max(float(kinds["onset"]["abs_err_argmax"]), float(kinds["offset"]["abs_err_argmax"]))
        for low, high in buckets():
            if low <= duration < high:
                buckets_data[bucket_name(low, high)] += [int(error > TOL)]
                break
    return {name: sum(values) / len(values) for name, values in buckets_data.items() if len(values) >= 20}


def fit(exposure: dict[str, float], miss: dict[str, float]) -> dict[str, Any]:
    names = sorted(set(exposure) & set(miss), key=lambda name: float(name.split("-")[0].rstrip("s+")))
    points = [(exposure[name], miss[name]) for name in names if exposure[name] > 0 and miss[name] > 0]
    if len(points) < 3:
        return {"status": "insufficient_data", "buckets": names}
    xs = [math.log10(share) for share, _ in points]
    ys = [math.log10(value) for _, value in points]
    mx, my = st.mean(xs), st.mean(ys)
    denominator = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denominator if denominator else 0.0
    intercept = my - slope * mx
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(value ** 2 for value in residuals) / max(1, len(xs) - 2) / denominator) if denominator else 0.0
    correlation = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) /
                   math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)))
    return {"status": "fitted", "buckets": names, "slope": round(slope, 3),
            "slope_se": round(se, 3), "correlation": round(correlation, 3),
            "exponent": round(slope, 3), "n_buckets": len(points),
            "observed": [{"bucket": name, "exposure_share": round(exposure[name], 4),
                          "miss_rate": round(miss[name], 4)} for name in names]}


def predict(fitted: dict[str, Any], exposure: dict[str, float], miss: dict[str, float],
            *, gain_by_bucket: dict[str, float]) -> dict[str, Any]:
    if fitted.get("status") != "fitted":
        return {"status": fitted.get("status", "unavailable")}
    exponent = fitted["exponent"]
    out: dict[str, Any] = {}
    for name, gain in gain_by_bucket.items():
        if name not in miss or name not in exposure:
            continue
        predicted = miss[name] * (gain ** exponent)
        band_low = miss[name] * (gain ** (exponent + 2 * fitted["slope_se"]))
        band_high = miss[name] * (gain ** (exponent - 2 * fitted["slope_se"]))
        low, high = sorted([band_low, band_high])
        out[name] = {"exposure_gain": round(gain, 2), "miss_before": round(miss[name], 4),
                     "miss_predicted": round(predicted, 4),
                     "band_95": [round(low, 4), round(high, 4)]}
    return out


def markdown(payload: dict[str, Any]) -> str:
    fitted = payload["fit"]
    lines = ["# 暴露—误差拟合与 B 臂的数值预期（生成，勿手改）", "",
             f"> 暴露份额来自 `{payload['labels']}` 的 `{payload['split']}` 切分；"
             f"误差来自 `{payload['dump']}`（旧 r2/750 在长音符富集样本上的逐字符超容差率）。", ""]
    if fitted.get("status") != "fitted":
        lines += [f"拟合不可用：{fitted.get('status')}。", ""]
        return "\n".join(lines)
    observed = {row["bucket"]: row for row in fitted["observed"]}
    lines += ["| 时长桶 | 训练暴露份额 | 实测超差率 |", "|---|---|---|"]
    for name in fitted["buckets"]:
        row = observed[name]
        lines.append(f"| {name} | {100 * row['exposure_share']:.2f}% | {100 * row['miss_rate']:.2f}% |")
    lines += ["",
              f"- log-log 拟合（n={fitted['n_buckets']} 个桶）：指数 **{fitted['exponent']}**"
              f"（SE {fitted['slope_se']}），r={fitted['correlation']}；"
              "指数为负 ⇒ 暴露越少、误差越高；",
              f"- 上采样名义 factor={payload['oversample_factor']}，但它是**按条目**复制："
              f"含 ≥{payload['long_sec']:g}s 字符的条目占 {100 * payload['items_with_long_share']:.1f}%，"
              f"所以长字符的**实际暴露倍数≈×{payload['effective_exposure_gain']}**（低于名义值）。", ""]
    prediction = payload.get("prediction") or {}
    useful = {name: block for name, block in prediction.items() if isinstance(block, dict)}
    if useful:
        lines += [f"## B 臂的数值预期（实际暴露倍数 ×{payload['effective_exposure_gain']}）", "",
                  "| 时长桶 | 当前超差率 | 预期超差率 | 95% 带 |", "|---|---|---|---|"]
        for name, block in useful.items():
            lines.append(f"| {name} | {100 * block['miss_before']:.2f}% | "
                         f"**{100 * block['miss_predicted']:.2f}%** | "
                         f"{100 * block['band_95'][0]:.2f}%–{100 * block['band_95'][1]:.2f}% |")
        lines += ["", "## 怎么用它", "",
                  "- 这不是达标门槛，而是把「B 涨了没有」升级成「B 涨的幅度是否符合暴露机制的预测」；",
                  "- 三种结果都 informative：① 落在带内 ⇒ 效应量可由暴露解释；"
                  "② 明显优于带 ⇒ 还有别的机制在起作用，值得追；"
                  "③ 几乎不动 ⇒ 暴露相关是假象，长音符问题不在数据配比，需要结构级改动；",
                  "- 已知偏差：(a) 按条目复制会把同条目里的短字符一起放大；"
                  "(b) 最短两桶误差几乎相同（1.7% vs 1.8%）而暴露差一倍 ⇒ 关系在高暴露端饱和，"
                  "斜率主要由稀有的长音端决定，因此外推到极端长音时要谨慎。", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--split", default="train")
    parser.add_argument("--factor", type=int, default=3)
    parser.add_argument("--long-sec", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    exposure = exposure_shares(args.labels, args.split)
    miss = miss_rates(args.dump)
    fitted = fit(exposure, miss)
    # 上采样按条目复制：含 ≥long_sec 字符的条目占比 p，则该条目里的字符（含长字符）暴露倍数 =
    # (1 + (factor-1) * p_share_of_long_items) / 1，近似取长字符所在条目占全部条目的比例
    counts = _item_stats(args.labels, args.split, args.long_sec)
    items_total = max(1, int(counts["items_total"]))
    characters_total = max(1, int(counts["characters_total"]))
    characters_in_long = max(0, int(counts["characters_in_long_items"]))
    p_items = int(counts["items_with_long"]) / items_total
    # share gain = factor * C_total / (C_total + (factor-1) * C_in_long_items)
    gain = args.factor * characters_total / (characters_total + (args.factor - 1) * characters_in_long)
    prediction = predict(fitted, exposure, miss,
                         gain_by_bucket={name: gain for name in miss if float(name.split("-")[0].rstrip("s+")) >= args.long_sec})
    payload = {"schema_version": "exposure_fit_v1", "labels": str(args.labels), "dump": str(args.dump),
               "split": args.split, "oversample_factor": args.factor, "long_sec": args.long_sec,
               "items_with_long_share": round(p_items, 4),
               "characters_in_long_items_share": round(characters_in_long / characters_total, 4),
               "pool_multiplier": round(1 + (args.factor - 1) * characters_in_long / characters_total, 4),
               "effective_exposure_gain": round(gain, 3),
               "gain_semantics": "share multiplier（拟合自变量是暴露份额）；旧版误用了条目复制的总数乘子",
               "counts": counts,
               "exposure_shares": {k: round(v, 5) for k, v in exposure.items()},
               "observed_miss": {k: round(v, 5) for k, v in miss.items()},
               "fit": fitted, "prediction": prediction}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({"fit": {key: fitted.get(key) for key in ("status", "exponent", "slope_se", "correlation", "n_buckets")},
                      "effective_exposure_gain": gain, "prediction": prediction}, indent=2, ensure_ascii=False))


def _item_stats(labels_path: Path, split: str, long_sec: float) -> dict[str, float]:
    """Counts needed for the *share* multiplier that the fit is actually expressed in.

    Oversampling replicates whole items, so a ≥1 s character is seen `factor` times while the pool
    also grows — the quantity that moves is its share of all characters, not its raw multiplier.
    Using the raw multiplier overstates the predicted gain.
    """
    items_with_long = items_total = characters_total = characters_in_long_items = 0
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("split") != split:
            continue
        classes = row.get("timestamp_class_ids") or []
        step = float(row.get("timestamp_segment_sec", 0.08))
        characters = len(classes) // 2
        if not characters:
            continue
        items_total += 1
        characters_total += characters
        if any((classes[2 * index + 1] - classes[2 * index]) * step >= long_sec
               for index in range(characters)):
            items_with_long += 1
            characters_in_long_items += characters
    return {"items_with_long": items_with_long, "items_total": items_total,
            "characters_total": characters_total, "characters_in_long_items": characters_in_long_items}


if __name__ == "__main__":
    main()
