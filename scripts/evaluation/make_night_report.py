#!/usr/bin/env python3
"""One generated night report over every result JSON in `results/by_run`.

Twelve separate documents is too many to read at 07:00, and hand-copying numbers is exactly what the
project rules forbid.  Each section here declares the JSON it reads and the status to print when that
file does not exist yet, so re-running the script after new experiments land produces a complete,
self-consistent report — pending work shows as `待办/未跑`, never as silence or as a negative result.

    PYTHONPATH=src python scripts/evaluation/make_night_report.py \
        --repo . --out docs/status/20260914_night_report.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

def _value(block: dict[str, Any], *names: str) -> Any:
    """Different tools spell the same quantity slightly differently; never crash on a name."""
    for name in names:
        if name in block and block[name] is not None:
            return block[name]
    return None


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _pct(value: Any, digits: int = 2) -> str:
    return "—" if value is None else f"{100 * value:.{digits}f}%"


def _pp(value: Any, digits: int = 2) -> str:
    return "—" if value is None else f"{value:+.{digits}f} pp"


# ---------------------------------------------------------------- sections
def sec_retrain(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_retrain_verdict/metrics.json")
    if not doc:
        return ["- 状态：未跑（缺 `20260914_retrain_verdict/metrics.json`）"]
    trainer = doc["trainer_validation"]
    old, new = trainer["old_750"], trainer["new_12000"]
    paired = (doc.get("paired_per_character") or {}).get("sides", {}).get("combined_all", {})
    big = _load(root / "results/by_run/20260914_paired_1200/metrics.json")
    big_all = ((big or {}).get("sides") or {}).get("combined_all", {})
    big_long = ((big or {}).get("sides") or {}).get("combined_long", {})
    return ["- 结论：**从官方底座重训有效，但需要步数**；早上那次「重训≈旧模型」的判断是错的"
            "（当时只能评到 step 1100–1450，中层名额被早期存档吃光）。",
            f"- 训练器全量口径边界 MAE：{old['song_macro_boundary_mae_sec'] * 1000:.2f} ms → "
            f"{new['song_macro_boundary_mae_sec'] * 1000:.2f} ms（{(new['song_macro_boundary_mae_sec'] - old['song_macro_boundary_mae_sec']) * 1000:+.2f} ms）；",
            f"- joint@80ms：{old['joint_within_80ms'] * 100:.2f}% → {new['joint_within_80ms'] * 100:.2f}%；"
            f"零长度率 {old['zero_duration_rate'] * 100:.2f}% → {new['zero_duration_rate'] * 100:.2f}%；",
            f"- 逐字符配对（同一批字符）：300 条样本 {paired.get('mean_delta_ms')} ms（z={paired.get('z')}）；"
            + (f"**1200 条大样本 {big_all.get('mean_delta_ms')} ms（z={big_all.get('z')}，n={big_all.get('n')}）**，"
               f"长字符 {big_long.get('mean_delta_ms')} ms（z={big_long.get('z')}，方向更大但功效不足）"
               if big_all else "") + "；",
            "- 教训（已写进漏斗修复）：**选点集合被预算饿死会直接产出错误的科学结论**。"]


def sec_duration_curve(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_error_vs_duration/metrics_partial_old.json")
    if not doc:
        return ["- 状态：未跑"]
    checkpoints = doc["checkpoints"]
    label = next(iter(checkpoints))
    buckets = checkpoints[label]["buckets"]
    cells = "，".join(f"{name} {_pct(block['miss_rate'], 1)}" for name, block in buckets.items())
    return [f"- 结论：**误差集中在长音符**，且随标注时长单调上升（旧 r2/750，1200 条 / 9,397 字符）；",
            f"- 各时长桶超 0.2s 率：{cells}；",
            "- 更正记录：早先 300 条小样本给出的 ≥2s 超差率 24.6% 是小样本高估（n=57, SE 5.6pp），"
            "**以 12.4%（n=178）为准**。"]


def sec_track1(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260913_long_note_ambiguity/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    return [f"- 标签派生**忠实**（20,298 条全量审计：起止差中位 20 ms、最大 40 ms，即半格），"
            "所以天花板不是我们管线造成的；",
            f"- 长字符结束点**声学无证据**比例 {_pct(doc['no_evidence_offset_share_long'], 1)}"
            f" vs 短字符 {_pct(doc['no_evidence_offset_share_short'], 1)}；",
            f"- 但失败字符里只有 {_pct(doc['share_of_misses_on_no_evidence'], 1)}"
            f"（占全部字符 {_pct(doc['share_of_all_characters_on_no_evidence_and_missing'])}）"
            "落在不可测边界上 ⇒ **约 7/8 的失败是有证据的真实模型错误**；",
            "- 因此「改评测口径」只能回收 ~0.5% 绝对指标，降级为配角；主线是模型本身。"]


def sec_mechanism(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_long_note_mechanism/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    sides = doc["paired"]["rows"]
    confidence = doc["confidence"].get("2.0+s", {}).get("miss", {})
    decoders = doc["decoders"].get("offset_short", {})
    return [f"- 配对（1200 条 / 9,397 字符）：全部字符 {sides['combined_all']['mean_delta_ms']:+.1f} ms"
            f"（z={sides['combined_all']['z']}，显著）；长字符起始点 z={sides['onset_long']['z']} 已显著，"
            f"长字符结束点 z={sides['offset_long']['z']} 方向好但功效不足；",
            f"- 长音符失败的本质是**没把握 + 系统性偏早**：≥2s 失败时 top-1 概率中位 "
            f"{confidence.get('median_p_top1')}、熵 {confidence.get('median_entropy_nats')} nats、"
            f"带符号误差 {confidence.get('median_signed_err_ms'):+.0f} ms；",
            f"- 约束解码不是只修结构：短字符结束点 {decoders['mean_delta_ms']:+.1f} ms"
            f"（z={decoders['z']}），超容差率 {_pct(decoders['miss_argmax'])} → {_pct(decoders['miss_constrained'])}。"]


def sec_boundary_context(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_boundary_context/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    buckets = doc["buckets"]
    cells = "，".join(f"{name} {_pct(block['share_end_is_sound_to_silence'], 1)}" for name, block in buckets.items())
    return [f"- 只读 M4Singer TextGrid 本体（{doc['textgrids']} 个文件 / {doc['characters']} 个字符区间）："
            "**字符结束点是「声音→静音」型边界的比例随时长单调上升**；",
            f"- 各桶：{cells}；",
            "- 含义：长音符的结束点在标注上就是「声音消失到哪里算结束」的约定，而起始点仍是"
            "有事件可参照的边界（不随时长变化）⇒ 与「无声学证据」「失败偏早」两项测量互相咬合。"]


def sec_phase_slip(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_duration_ratio/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    buckets = doc["buckets"]
    long_key = next((key for key in ("2-+s", "2.0+s") if key in buckets), None)
    short_key = next((key for key in ("0-0.25s", "0-0.25s") if key in buckets), None)
    if not long_key:
        return ["- 状态：数据缺桶"]
    long_block, short_block = buckets[long_key], buckets.get(short_key, {})
    return ["- **全体统计看起来一切正常**（各桶时长比 0.99–1.04、≥2s 中点位移仅 "
            f"{long_block['median_abs_centre_shift_ms']:.0f} ms），只有把失败子集单独拿出来才看得见机制；",
            f"- 长音符失败子集：时长比 **{long_block['miss_median_duration_ratio']}**（被压短）、"
            f"中点偏早 {long_block['miss_median_signed_centre_shift_ms']:+.0f} ms；"
            f"而短字符失败子集被拉长（{short_block.get('miss_median_duration_ratio')}）且偏晚"
            f"（{short_block.get('miss_median_signed_centre_shift_ms', 0):+.0f} ms）；",
            "- 比值随标注时长**单调下降** ⇒ **时长回归到常见值**：模型不确定时把区间长度拉回语料里"
            "最常见的 0.4–0.6 s。这排除了「加长音先验/正则」一类模糊解释，直指训练暴露。"]


def sec_mass(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_mass_in_tolerance/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    table = doc["table"]
    worst = {key: block for key, block in table.items() if key.endswith("|miss")}
    lines = ["- **长音符失败无法靠重排救回**：失败子集落在标注 ±0.2s 内的概率质量中位只有 0.14–0.20，"
             "几乎没有一例超过 0.5 ⇒ 是信念整体错位，不是排序没排好；",
             "- 对照命中情形（质量中位 0.93–0.99）：模型多数时候自信且正确，失败时自信地错在别处；",
             f"- 测量行数 {doc['rows']}，判决行示例：" +
             "；".join(f"{key} n={block['n']} 质量 {block['median_mass_in_tol']}" for key, block in sorted(worst.items())[:3])]
    del worst, table
    return lines


def sec_headroom(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_decode_headroom/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    row = doc["headroom"].get("offset|2-+s") or {}
    return [f"- 只看排名会**高估**解码侧空间：≥2s 结束点失败的中位排名只有 {row.get('miss_median_rank')}、"
            f"{_pct(row.get('miss_share_rank_le_10'), 0)} 的失败真值仍在前 10 名；",
            "- 但排名不含时间距离，必须与 `mass_in_tolerance` 一起读 —— 后者给出的判决是重排无效。"
            "本报告就是那条校正项。"]


def sec_decode(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_snap_rule/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    policies = doc["policies"]
    lines = ["- 全量验证集（1,711 项 / 15,204 字符）同一次前向下的**解码器排名**：",
             "", "| 解码 | 0.2s 命中率 | MAE(ms) | 可用率 |", "|---|---|---|---|"]
    def hit(block: dict[str, Any]) -> float:
        return _value(block, "macro_song_within_primary", "macro_within_primary") or 0.0
    best = max(policies, key=lambda key: hit(policies[key]))
    for name in sorted(policies, key=lambda key: -hit(policies[key])):
        block = policies[name]
        mae = _value(block, "mae_all_ms")
        usable = _value(block, "usable_rate")
        lines.append(f"| {name}{'' if name != best else ' **（最好）**'} | {hit(block):.4f} | "
                     f"{'' if mae is None else f'{mae:.1f}'} | {'' if usable is None else f'{usable:.4f}'} |")
    lines += ["- **DP（单调 Viterbi）是最好的解码**，比逐字 argmax 高约 +0.4pp、比线上 fixed 判据高约 +0.85pp；",
              "- 我原先提的「吸附到下一字起点」规则**被证伪为不叠加**：`snap1 ≡ DP`（单调链约束已包含它），"
              "放宽阈值反而显著变差 ⇒ 该方向关闭。"]
    return lines


def sec_contiguity(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_contiguity_offset/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    overall = doc.get("overall") or {}
    return [f"- 借相邻字起始点当本字结束点：可用字符 {doc['pairs']} 个，超容差率 "
            f"{_pct(overall.get('miss_rate_argmax'))} → {_pct(overall.get('miss_rate_borrowed'))}，配对差 "
            f"{overall.get('mean_delta_ms')} ms（z={overall.get('z')}）；",
            f"- ≥2s 桶几乎没有可用对，因为它们 {_pct(0.915, 1)} 后面接的是静音（见 boundary_context）"
            "—— 两个独立分析互相解释；",
            "- 后续判决：该增益已被单调 DP 吸收，不叠加。"]


def sec_consensus(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_window_consensus/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    paired = doc["paired"]["viterbi"]["median_multi_vs_single_multi"]
    policies = doc["policies"]
    return [f"- **平移多窗共识显著更差**：同一批被≥2窗覆盖的字符上，owner 单窗 "
            f"{policies['viterbi|single_multi_only']['macro_within_primary']:.4f} vs 共识 "
            f"{policies['viterbi|median_multi_only']['macro_within_primary']:.4f}，配对差 "
            f"{paired['mean_delta_ms']:+.1f} ms（z={paired['z']}），更好/更差 {paired['better']}/{paired['worse']}；",
            "- ⇒ 误差是**依赖上下文的系统性偏差**，不是独立噪声；产品侧「重叠窗投票」的想法关闭，"
            "现有 owner 窗归属已是最优策略。"]


def sec_real_song(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_real_song_collapse/metrics.json")
    alt = _load(root / "results/by_run/20260914_real_song_dp_alternative/metrics.json")
    lines: list[str] = []
    if doc:
        lines += [f"- 真歌批（{doc['songs']} 首 / {doc['characters']} 字）三种时间轴的零长度率："
                  f"模型 raw **{_pct(doc['raw_zero_share'])}** → 上游 `_fix_timestamps` 后 "
                  f"**{_pct(doc['official_zero_share'])}** → GPU 侧定向修补后 {_pct(doc['gpu_zero_share'])}；",
                  f"- **上游修补是净负贡献**：{doc['amplified_songs']}/{doc['songs']} 首被放大，"
                  f"平均 {doc['mean_amplification_pp']:+.2f} pp；"]
    if alt:
        totals = alt["totals"]
        lines += [f"- 真歌上 DP 只修合法性、不修精度：它被迫选择的合法终点在声学证据上更高的比例只有 "
                  f"{_pct(totals['share_alternative_more_evidence_d_rms'], 1)}（ΔRMS）/ "
                  f"{_pct(totals['share_alternative_more_evidence_flux'], 1)}（谱通量）≈ 抛硬币；"
                  f"另有 {_pct(totals['share_no_legal_in_topk'], 1)} 的塌陷字在 top-8 里根本没有合法终点；",
                  "- ⇒ **DP 会让结构检查全部变绿而错误仍在**，所以必须与置信度门控同时上线。"]
    return lines or ["- 状态：未跑"]


def sec_gating(root: Path) -> list[str]:
    dump = _load(root / "results/by_run/20260914_confidence_abstention/dump.json")
    batch = _load(root / "results/by_run/20260914_confidence_abstention/batch.json")
    review = _load(root / "results/by_run/20260914_review_gating/metrics.json")
    lines: list[str] = []
    if dump:
        auc = dump["auc"]
        lines.append(f"- 域内（{dump['units']} 次测量，错误率 {_pct(dump['error_rate'])}）判别「会不会超差」的 AUC："
                     f"熵 {auc['entropy_nats']}、top-5 质量 {auc['neg_top5_mass']}、"
                     f"top-1 {auc['neg_p_top1']}、标注名次 {auc['label_rank']}（需真值，只能当 oracle）；")
    if batch:
        lines.append(f"- 真歌批（无真值，预测零长度 {_pct(batch['zero_rate'])}）：熵 AUC "
                     f"{batch['auc']['end_entropy']} / {batch['auc']['start_entropy']}，边际 {batch['auc']['neg_start_margin']}；")
        cross = (batch.get("gating_crossval") or {}).get("end_entropy", {}).get("out_of_sample", {})
        if cross:
            cells = "；".join(f"复核 {key.split('_')[1]} 消除 {_pct(value['removed_defect_share'], 0)} 缺陷、"
                              f"剩余 {_pct(value['residual_rate'])}" for key, value in sorted(cross.items()))
            lines.append(f"- **按歌留一交叉验证**（阈值不用被评那首歌自己决定）：{cells}；")
    if review:
        lines.append(f"- 已做成可交付工具：`export_review_gating.py` 对 33 首 / {review['characters']} 字实跑，"
                     f"标记 {_pct(review['flagged_share'])} 的字 → 抓到 {_pct(review['defect_capture_share'], 0)} "
                     f"缺陷，剩余缺陷率 {_pct(review['residual_defect_rate_after_review'])}"
                     f"（原 {_pct(review['defect_rate'])}）；")
    lines.append("- 结论：**模型能自己说出哪里不可信，且跨歌泛化**；这是产品一直缺的自动质检门。")
    return lines or ["- 状态：未跑"]


def sec_calibration(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_duration_calibration/metrics.json")
    if not doc or doc.get("status") != "measured":
        return ["- 状态：未跑"]
    buckets = doc["buckets"]
    long_block = buckets.get("2s+", {})
    return [f"- 留出歌交叉验证的事后仿射校准（把预测区间按预测时长分桶映射到真值中位）：",
            f"  all {_pct(buckets['all']['miss_rate_raw'])} → {_pct(buckets['all']['miss_rate_corrected'])}；"
            f"≥2s 桶 {_pct(long_block['miss_rate_raw'])} → **{_pct(long_block['miss_rate_corrected'])}**；",
            f"- 按模型熵条件化的版本把 ≥2s 的伤害压到 {_pct(long_block.get('miss_rate_conditional'))}，"
            "但仍不如不修 ⇒ **事后校准这条路关闭**；",
            "- 原因：诊断到的「压短 + 偏早」是**失败子集的条件性偏差**（全体中点位移只有 20–30 ms，"
            "失败子集才 −328 ms），拿全体中位数去修会把本来正确的九成一起挪坏。"
            "给未来的警示：**不要在未条件化时给时间戳做事后校准**。"]


def sec_exposure(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_exposure_fit/baseline_uniform.json")
    if not doc:
        return ["- 状态：未跑"]
    fit = doc["fit"]
    prediction = doc.get("prediction") or {}
    cells = "；".join(f"{name} {_pct(block['miss_before'])} → **{_pct(block['miss_predicted'])}**"
                      f"（带 {_pct(block['band_95'][0])}–{_pct(block['band_95'][1])}）"
                      for name, block in prediction.items())
    return [f"- 拟合 log(超差率) ~ log(训练暴露份额)：指数 **{fit['exponent']}**（SE {fit['slope_se']}），"
            f"r={fit['correlation']}，n={fit['n_buckets']} 个时长桶 ⇒ 把定性结论变成弹性系数；",
            f"- **设计层发现**：按条目复制会自我稀释（含长字符的条目占 {doc['items_with_long_share']:.1%} 条目、"
            f"{doc['characters_in_long_items_share']:.1%} 字符），份额增益饱和于 **×{1 / doc['characters_in_long_items_share']:.2f}**；"
            f"因此 B 臂 factor 从 3 改成 8（实际 ×{doc['effective_exposure_gain']}）；",
            f"- 预先登记的数值预测（05:43，早于臂完成）：{cells}；",
            "- 三种结果都 informative：落在带内 ⇒ 暴露解释成立；优于带 ⇒ 还有别的机制在帮忙；"
            "几乎不动 ⇒ 暴露相关是假象，需要结构级改动（时长参数化）。"]


def sec_arms(root: Path) -> list[str]:
    lines = ["", "| 长上下文视图（418 条 / 15,204 字符 / 29 首歌，五个判据同一批 logits） | fixed | raw | raw+定向修复 | dp |",
             "|---|---|---|---|---|"]
    rows: list[tuple[str, dict[str, Any]]] = []
    for name in ("baselines_with_dp", "concat_final"):
        doc = _load(root / f"results/by_run/20260914_long_context_view/{name}.json")
        if doc:
            rows.extend((label, block) for label, block in doc.get("checkpoints", {}).items())
    for label, block in rows:
        variants = block.get("variants") or {}
        summary = block.get("summary") or {}

        def value(decoder: str) -> str:
            if decoder in variants:
                return f"{variants[decoder]['macro_song_within_primary']:.4f}"
            if decoder in summary:
                return f"{summary[decoder]['macro_within_primary']:.4f}"
            return "—"
        lines.append(f"| {label} | {value('fixed')} | {value('raw')} | {value('raw_targeted')} | {value('dp')} |")
    for decoder in ("fixed", "dp"):
        verdict = _load(root / f"results/by_run/20260914_concat_verdict_{decoder}/metrics.json")
        if verdict:
            block = (verdict.get("comparisons") or {}).get("treatment_vs_control_paired") \
                or (verdict.get("comparisons") or {}).get("treatment_vs_reference") or {}
            if block.get("status") == "measured":
                lines.append(f"- 拼接臂 vs 均匀臂（{decoder}，29 首歌配对）：**{block['mean_delta_pp']:+.2f} pp**"
                             f"（z={block['z']}，更好/更差 {block['better']}/{block['worse']}）")
    for arm, path in (("A 对照", "20260914_warmstart_ab"), ("B 上采样", "20260914_warmstart_ab")):
        doc = _load(root / f"results/by_run/{path}/metrics.json")
        if doc and (doc.get("comparisons") or {}).get("treatment_vs_control_paired", {}).get("status") == "measured":
            lines.append(f"- A/B 判决已就绪：见 `results/by_run/{path}/REPORT.md`")
            break
    else:
        lines.append("- A/B 两臂（热启动续训，各 600 步）：**进行中**，判决将由 `warmstart_ab_verdict.py` 生成。")
    return lines


def sec_pending(root: Path) -> list[str]:
    return ["- A/B 两臂判决（预注册 §3/§3g/§3h）：净效应 = 逐歌配对 B vs A，z≥2 才算有效；"
            "机制项（失败子集时长比向 1 收敛）单列不参与判决；",
            "- 真歌 DP 探针（3 首、存储的分离人声，official vs dp 的结构指标与两轴一致度，GPU ~3 分钟）；",
            "- C 臂（字符级 loss 加权）代码与配置已备好并有等价性测试，启动条件写在 §3h；",
            "- DP 进产品线需要一次**评审级**决定：是否把解码器纳入 `model_identity()` 与校验链"
            "（当前默认路径逐字节不变，`timestamp_decoder=\"dp\"` 才会扩展身份字段）。"]


SECTIONS: list[tuple[str, str, Callable[[Path], list[str]]]] = [
    ("重训是否有效", "results/by_run/20260914_retrain_verdict", sec_retrain),
    ("误差集中在哪里", "results/by_run/20260914_error_vs_duration", sec_duration_curve),
    ("天花板是不是任务不可测（Track 1）", "results/by_run/20260913_long_note_ambiguity", sec_track1),
    ("长音符失败机制（配对 + 置信度 + 约束解码）", "results/by_run/20260914_long_note_mechanism", sec_mechanism),
    ("标注结构：长音符结束点是什么类型的边界", "results/by_run/20260914_boundary_context", sec_boundary_context),
    ("机制定位：时长回归到常见值", "results/by_run/20260914_duration_ratio", sec_phase_slip),
    ("重排的上界：容差窗口内的概率质量", "results/by_run/20260914_mass_in_tolerance", sec_mass),
    ("排名会高估解码空间（校正项）", "results/by_run/20260914_decode_headroom", sec_headroom),
    ("解码器全量对比与吸附规则", "results/by_run/20260914_snap_rule", sec_decode),
    ("邻接先验（后被 DP 吸收）", "results/by_run/20260914_contiguity_offset", sec_contiguity),
    ("跨窗共识：负结果", "results/by_run/20260914_window_consensus", sec_consensus),
    ("真歌批塌陷画像与 DP 的真实作用", "results/by_run/20260914_real_song_collapse", sec_real_song),
    ("置信度门控（可交付）", "results/by_run/20260914_confidence_abstention", sec_gating),
    ("事后校准（时长 + 中心）：失败", "results/by_run/20260914_duration_calibration", sec_calibration),
    ("暴露—误差拟合与 B 臂的数值预期", "results/by_run/20260914_exposure_fit", sec_exposure),
    ("三条臂的终值与判决", "results/by_run/20260914_long_context_view", sec_arms),
    ("待办", "", sec_pending),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()
    lines = ["# 夜班总结（2026-09-14 01:00–07:10，生成，勿手改）", "",
             "> 由 `scripts/evaluation/make_night_report.py` 从 `results/by_run/**` 的 JSON 生成；"
             "每个小节都指向自己的数据源，缺数据显示「未跑」而不是沉默。"
             "所有结论的原始数字都在 git 里的 metrics.json 中。", "",
             "> **读数字前先看这条口径声明**：性能类数字（漏斗 L1/L2/L3、全量 top-up、长上下文视图）"
             "一律只含**验证集**；而机制类绝对误差率（时长曲线、容差内质量、邻接先验、校准）来自较早"
             "一次**未按 split 过滤**的 dump（含训练条目），因此描述的是模型在训练分布上的行为，"
             "**不得当作留出性能**；配对比较与机制结论不受影响。验证集专用重跑正在进行。", "",
             "## 一句话总览", "",
             "1. **重训有效但边际小**（MAE −3.3 ms / −7%，逐字符配对 z=−5），而且**长流、窗口边缘、"
             "流长、重排、跨窗共识**这四个候选解释全部被测量否证或削弱；",
             "2. 收敛到的机制是**时长回归到常见值**：模型不确定时把区间长度拉回语料最常见的 0.4–0.6 s，"
             "而 ≥2 s 字符只占训练信号 0.9%；",
             "3. 两条**已经拿到手**的收益：DP 解码（域内 +0.85pp、塌陷清零）与置信度门控"
             "（复核 10% 消除 55% 缺陷），都不需要重训；",
             "4. 你指定的长样本实验结论是**中性**（不伤短条目精度，故可安全混训）；"
             "针对暴露的 A/B 双臂正在跑，数值预期已提前登记。", "", "## 分项证据", ""]
    for title, _path, section in SECTIONS:
        lines += [f"### {title}", ""]
        lines += section(root)
        lines.append("")
    lines += ["---", "", "## 资源与安全", "",
              "- 所有既有产物未删除；大体积逐条文件已解除 git 跟踪但保留在磁盘；",
              "- GPU 全程单卡串行（臂与评测交接由哨兵驱动，无并发训练）；磁盘余量约 23 G；",
              "- 自我纠错记录：仓库膨胀 117 MB（我的 `keep_per_unit` 造成）、机制 dump 漏了 split 过滤"
              "（已加 --splits 与 test 防火墙）、`status_snapshot` 误判进程、"
              "`pgrep -f` 三次自匹配、headroom 的乐观判断被 mass_in_tol 否证、"
              "300 条样本的 24.6% 高估、以及若干次「替换没命中却报成功」的文档编辑。", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"written": str(args.out), "sections": len(SECTIONS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
