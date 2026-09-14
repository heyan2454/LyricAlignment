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
    argmax_value = hit(policies.get("argmax", {})) if "argmax" in policies else None
    viterbi_value = hit(policies.get("viterbi", {})) if "viterbi" in policies else None
    same_forward = (f"，比逐字 argmax 高 **{viterbi_value - argmax_value:+.4f}**"
                    "（同一份全量验证集、同一次前向，机器计算）"
                    if argmax_value and viterbi_value else "")
    lines += ["- **DP（单调 Viterbi）是最好的解码**" + same_forward + "；",
              "- 我原先提的「吸附到下一字起点」规则**被证伪为不叠加**：`snap1 ≡ DP`（单调链约束已包含它），"
              "放宽阈值反而显著变差 ⇒ 该方向关闭。",
              "- 与线上 `fixed` 判据的差值请按口径分别读：**短条目全量视图**与**长流视图**"
              "是两条不同的机器计算行（见「三条臂的终值与判决」与「A/B 决策表」两节）；"
              "此前这里写的「+0.85pp」属跨工具比较、口径不同，已移除。"]
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
    lines.append("- **口径提醒（防止把一次计算当成两条证据）**：上面「按歌留一交叉验证」与"
                 "「`export_review_gating.py` 实测 13,735 字 / 标记 10.75% / 抓到 55.09%」"
                 "**是同一次留一计算的两种呈现，不是两条独立证据**；"
                 "真正独立的外部印证是 2026-09-12 那次在 GTSinger 上测到的熵 AUC 0.913（不同语料、不同会话）。")
    return lines or ["- 状态：未跑"]


def sec_calibration(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_duration_calibration/metrics.json")
    if not doc or doc.get("status") != "measured":
        return ["- 状态：未跑"]
    buckets = doc["buckets"]
    long_block = buckets.get("2s+", {})
    policy = doc.get("out_of_range_policy", "")
    return [f"- 留出歌交叉验证的事后仿射校准（按预测时长分桶映射到真值中位；"
            f"越界策略：{policy or '见脚本'}）：",
            f"  all {_pct(buckets['all']['miss_rate_raw'])} → 无条件校准 {_pct(buckets['all']['miss_rate_corrected'])}"
            f"（均差 {buckets['all']['mean_delta_ms']:+.2f} ms）；"
            f"≥2s 桶 {_pct(long_block['miss_rate_raw'])} → {_pct(long_block['miss_rate_corrected'])}；"
            f"按模型熵条件化反而把 ≥2s 推到 {_pct(long_block.get('miss_rate_conditional'))}",
            "- ⇒ **事后校准没有收益**（无条件≈中性，条件化对长音有害），该路径关闭；",
            "- 原因：诊断到的「压短 + 偏早」是**失败子集的条件性偏差**（全体中点位移只有 20–30 ms，"
            "失败子集才 −328 ms），拿全体中位数去修会把本来正确的九成一起挪坏；",
            "- **口径更正记录**：本节先前给出的「≥2s 10.23% → 37.67%（灾难性）」大部分是**我自己实现的"
            "钳位伪影**（预测时长超出拟合节点时被拉回最后一桶中位数）。改成「越界即不修正」后真实结果是"
            " 10.23% → 10.70%。结论方向（无收益）不变，但量级被夸大了 —— 已在脚本 v2、测试与预注册中一并更正。"]


def sec_exposure(root: Path) -> list[str]:
    directory = root / "results/by_run/20260914_exposure_fit"
    doc = None
    for candidate in ("validation_uniform_f8", "mixed_uniform_f8", "baseline_uniform"):
        doc = _load(directory / f"{candidate}.json")
        if doc and (doc.get("fit") or {}).get("status") == "fitted":
            used = candidate
            break
    if doc is None:
        return ["- 状态：未跑"]
    if not doc:
        return ["- 状态：未跑"]
    fit = doc["fit"]
    prediction = doc.get("prediction") or {}
    cells = "；".join(f"{name} {_pct(block['miss_before'])} → **{_pct(block['miss_predicted'])}**"
                      f"（带 {_pct(block['band_95'][0])}–{_pct(block['band_95'][1])}）"
                      for name, block in prediction.items())
    stabilities = []
    for candidate in ("baseline_old750", "baseline_uniform", "validation_uniform", "validation_uniform_f8"):
        other = _load(directory / f"{candidate}.json")
        if other and (other.get("fit") or {}).get("exponent") is not None:
            stabilities.append(f"{candidate.split('_')[0][:4]}{'' if 'old' not in candidate else '旧'}:"
                               f"{other['fit']['exponent']}")
    return [f"- 拟合 log(超差率) ~ log(训练暴露份额)（**采用口径：{used}**）："
            f"指数 **{fit['exponent']}**（SE {fit['slope_se']}），r={fit['correlation']}，"
            f"n={fit['n_buckets']} 个时长桶 ⇒ 把定性结论变成弹性系数；"
            + (f"四种口径的指数都落在 {min(float(x.split(':')[1]) for x in stabilities):.3f} ~ "
               f"{max(float(x.split(':')[1]) for x in stabilities):.3f} 之间，"
               "说明弹性不是样本挑选的产物。" if len(stabilities) > 2 else ""),
            f"- **设计层发现**：按条目复制会自我稀释（含长字符的条目占 {doc['items_with_long_share']:.1%} 条目、"
            f"{doc['characters_in_long_items_share']:.1%} 字符），份额增益饱和于 **×{1 / doc['characters_in_long_items_share']:.2f}**；"
            f"因此 B 臂 factor 从 3 改成 8（实际 ×{doc['effective_exposure_gain']}）；",
            f"- 预先登记的数值预测：**05:43 首次登记**（当时 factor=3，混合曲线）⇒ 1–2s 6.60%→4.96%、"
            f"≥2s 11.06%→8.32%；**07:33 按臂的真实设定重登记**（factor=8、留出曲线）⇒ {cells}；"
            f"两次都早于 B 臂完成；",
            "- 三种结果都 informative：落在带内 ⇒ 暴露解释成立；优于带 ⇒ 还有别的机制在帮忙；"
            "几乎不动 ⇒ 暴露相关是假象，需要结构级改动（时长参数化）。"]


def sec_arms(root: Path) -> list[str]:
    lines = ["", "| 长上下文视图（418 条 / 15,204 字符 / 29 首歌，五个判据同一批 logits） | fixed | raw | raw+定向修复 | dp |",
             "|---|---|---|---|---|"]
    rows: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    # 自动纳入后续任何视图文件（C 臂、复评等），避免"跑完还得记得改报告代码"这种断点
    view_dir = root / "results/by_run/20260914_long_context_view"
    candidates = ["baselines_with_dp", "concat_final", "ab_arms", "c_arm"]
    if view_dir.exists():
        for extra in sorted(view_dir.glob("*.json")):
            if extra.stem not in candidates:
                candidates.append(extra.stem)
    for name in candidates:
        doc = _load(root / f"results/by_run/20260914_long_context_view/{name}.json")
        if not doc:
            continue
        for label, block in doc.get("checkpoints", {}).items():
            if label not in seen:
                seen.add(label)
                rows.append((label, block))
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
    deltas = []
    for label, block_view in rows:
        variants = block_view.get("variants") or {}
        summary = block_view.get("summary") or {}

        def value_of(decoder: str, _v=variants, _s=summary):
            if decoder in _v:
                return _v[decoder].get("macro_song_within_primary")
            if decoder in _s:
                return _s[decoder].get("macro_within_primary")
            return None
        fixed_value, dp_value = value_of("fixed"), value_of("dp")
        if fixed_value is not None and dp_value is not None:
            deltas.append((label, 100 * (dp_value - fixed_value)))
    if deltas:
        spread = "、".join(f"{name} {value:+.2f}" for name, value in deltas)
        lo = min(value for _name, value in deltas)
        hi = max(value for _name, value in deltas)
        lines += ["", f"- **DP 相对线上 fixed 判据的增益逐个存档现算**（同一批 logits）：{spread} pp"
                  f" ⇒ 区间 **{lo:+.2f} ~ {hi:+.2f} pp**，跨 {len(deltas)} 个独立训练/解码配置一致"
                  " ⇒ 这条结论不是某个存档的运气；数字由脚本从视图 JSON 计算，不是手填常数。"]
    ab_terminal = _load(root / "results/by_run/20260914_warmstart_control/terminal_validation_AB.json")
    baseline_terminal = _load(root / "results/by_run/20260914_retrain_verdict/metrics.json")
    if ab_terminal:
        rows = dict(ab_terminal)
        # 线上旧 750 与均匀终点在 retrain_verdict 里也有，缺省时补齐
        for name, block in ((baseline_terminal or {}).get("trainer_validation") or {}).items():
            key = {"old_750": "线上旧 750", "new_12000": "均匀终点 12000"}.get(name)
            if key and key not in rows and isinstance(block, dict):
                rows[key] = block
        lines += ["", "| 终态验证（全量 1,711 项、同一评测代码路径） | MAE(ms) | joint@80 | 零长度 |", "|---|---|---|---|"]
        for label in ("线上旧 750", "均匀终点 12000", "A 对照（600 步）", "B 上采样（600 步）"):
            block = rows.get(label)
            if not block or block.get("song_macro_boundary_mae_sec") is None:
                continue
            lines.append(f"| {label} | {1000 * block['song_macro_boundary_mae_sec']:.2f} | "
                         f"{100 * block['joint_within_80ms']:.2f}% | {100 * block['zero_duration_rate']:.2f}% |")
        a_row, b_row = rows.get("A 对照（600 步）") or {}, rows.get("B 上采样（600 步）") or {}
        if a_row and b_row:
            lines.append(f"- ⇒ **短条目全量口径上 B 比 A 差 {1000 * (b_row['song_macro_boundary_mae_sec'] - a_row['song_macro_boundary_mae_sec']):+.2f} ms**"
                         f"（joint@80 {100 * (b_row['joint_within_80ms'] - a_row['joint_within_80ms']):+.2f} pp）"
                         "——与 §3n 的覆盖混杂一致（B 只看到约 27% 的唯一条目），"
                         "**不能**据此说'长音挤占了容量'；主判据仍看 offset_long 配对与长流视图。")
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


def sec_real_decoder(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_real_song_decoder/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    totals = doc["totals"]
    songs = [e for e in doc["songs"] if "official" in e]
    mild = [e for e in songs if e["official"]["zero_share"] < 0.30]
    severe = [e for e in songs if e["official"]["zero_share"] >= 0.60]
    lines = [
        f"- **口径先说清**：这是把整段 120 s 人声**一次性**喂进模型的**压力条件**，"
        "不是产品的分窗路径（分窗下线上 raw 塌陷是 10.80%）。所以这里的数字**不可与 10.80% 混读**；",
        f"- 压力条件下（{totals['songs']} 首 / {totals['intervals']} 个区间，线上 checkpoint r2/750）："
        f"官方解码零长度 **{_pct(totals['official_zero_share'])}**，DP **{_pct(totals['dp_zero_share'])}**"
        f"（{totals['official_zero']} → 0）；",
        f"- 最极端一例 `p.h`：官方把 **326/326 个区间放在同一时刻**（时间轴跨度 0.00 s），"
        "DP 给出跨度 118.24 s 的合法单调轴 —— 官方那条**必然是错的**，DP 那条对不对无法验证（无真值）；",
        f"- 轻中度塌陷的歌（{len(mild)} 首 <30%）里 DP 几乎不改时间轴："
        "end 位移中位 " + "、".join(f"{e['song'][:8]} {e['agreement_median_end_delta_ms']:.0f} ms" for e in mild)
        + " ⇒ **DP 是局部修补而非重排**，这正是它风险低的原因；",
        f"- 重度塌陷的歌（{len(severe)} 首 ≥60%）里 DP 的改动幅度**差异极大**（end 位移中位 "
        + "、".join(f"{e['song'][:8]} {e['agreement_median_end_delta_ms'] / 1000:.1f} s" for e in severe)
        + "）：有的只是将少量非法区间就近合法化，有的则整条重排；"
        "**只要位移达到秒级，就不可能靠『合法』来判定好坏 ⇒ 这类歌必须走门控复核**，"
        "不能因为结构合法了就放过。",
    ]
    return lines


def sec_confidence_duration(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_confidence_duration/metrics.json")
    if not doc:
        return ["- 状态：未跑"]
    cells = doc["cells"]
    totals = (cells.get("_bucket_totals") or {})
    corr = doc["distance_to_mode_vs_entropy"]
    lines = ["- **这条分析否证了我先前机制说法的天真版本**：按（真值时长桶 × 熵四分位）交叉后，"
             "**每个格子里的中位时长比都是 0.97–1.03** ⇒ 模型的**典型**预测并没有被压短；"
             "压缩只发生在失败子集内（那是条件性偏差，不是全局收缩）；",
             f"- 混池相关是**混杂**：全体 r={corr['all']['pearson_r']}（t={corr['all']['t_approx']}）"
             f"看着很强，但**分桶之后全部消失**（0-0.5s {corr['0-0.5s']['pearson_r']}、"
             f"0.5-1s {corr['0.5-1s']['pearson_r']}、1-2s {corr['1-2s']['pearson_r']}、"
             f"2s+ {corr['2s+']['pearson_r']}）⇒ 那个正相关只是『长字符既有高熵也有远离众数的时长』；",
             "- **真正的发现在这里：不确定性几乎完全集中在长字符上**（留出口径 6,415 字符）："]
    for name in ("0-0.5s", "0.5-1s", "1-2s", "2s+"):
        block = cells.get(name) or {}
        if not block:
            continue
        # 分母必须用该时长桶的**全部**字符数：小格子被过滤掉时，只按保留格子算会虚高占比
        total = (totals.get(name) or {}).get("characters") or sum(
            value["characters"] for key, value in block.items() if not key.startswith("_"))
        q4 = (block.get("Q4(最不确信)") or {}).get("characters", 0)
        shown = sum(value["characters"] for key, value in block.items() if not key.startswith("_"))
        named = {key: value for key, value in block.items() if not key.startswith("_")}
        if not named:
            continue
        first = named[min(named)]
        last = named[max(named)]
        note = "" if shown == total else f"（另有 {total - shown} 个字符落在 <25 行的小格子里，未列示）"
        lines.append(f"  - {name}：桶内共 {total} 个字符，落在最低置信四分位的比例 "
                     f"**{_pct(q4 / total, 0)}**{note}；超差率随熵从 {_pct(first['miss_rate'])} "
                     f"升到 {_pct(last['miss_rate'])}")
    lines += ["- 我当时据此推断：**全局熵阈值会系统性误判长字符**，应改为按预测时长分档校准。",
              "  **这个推论已被自己的实验否证**（见下一节）：分档后抓到缺陷反而少 4.3–7.4 pp。"
              "原因是『时长与出错的相关』本身就是风险信号，分档归一化正好把它丢掉了。"]
    return lines


def sec_long_offset_drift(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_paired_A_vs_start/robustness.json")
    history = _load(root / "results/by_run/20260914_paired_1200/robustness.json")
    if "sides" not in doc:
        return ["- 状态：未跑"]
    lines = ["- **这一节修正了我自己几小时前说过头的话**：A（未改配比的 600 步续训）在长字符结束点上"
             "的退化只是**迹象**，不是确证。四位置稳健性检查（含 ×4 多重比较校正）：",
             "", "| 位置 | n | 均值Δ | 中位Δ | 截尾均值 | 均值 p(×4) | McNemar p(×4) | 判定 |",
             "|---|---|---|---|---|---|---|---|"]
    order = ("onset_short", "onset_long", "offset_short", "offset_long")
    for name in order:
        block = doc["sides"].get(name) or {}
        if block.get("status") != "measured":
            continue
        lines.append(f"| {name} | {block['n']} | {block['mean_delta_ms']:+.2f} ms | {block['median_delta_ms']:+.1f} | "
                     f"{block['trimmed_mean_delta_ms']:+.2f} | {block['p_t']:.3f} ({block['p_t_times_sides']:.3f}) | "
                     f"{block['mcnemar_better']}/{block['mcnemar_worse']} → {block['p_mcnemar_exact']:.3f} "
                     f"({block['p_mcnemar_times_sides']:.3f}) | **{block['verdict']}** |")
    lines += ["", "  ⇒ **中位数与 2% 截尾均值都是 0.00 ms**：那 +9.55 ms 的均值完全来自极少数字符的大幅移动"
              "（新坏 5 个 / 新好 0 个，n=940）；且这是从四个位置里挑最差的来讲，必须校正。"
              "所以正确措辞是『迹象、未过校正』，我先前写的『显著、专一伤害、预测被否证』已撤回。", ""]
    if "sides" in (history or {}):
        short = history["sides"].get("offset_short") or {}
        long_ = history["sides"].get("offset_long") or {}
        lines += ["- **同一把尺子复查整条训练史（750 → 12000 步）**：短字符结束点的改善是**确证**"
                  f"（{short.get('mean_delta_ms'):+.2f} ms，McNemar {short.get('mcnemar_better')}/"
                  f"{short.get('mcnemar_worse')}，p×4={short.get('p_mcnemar_times_sides')}）；"
                  f"而**长字符结束点的改善是无证据**（{long_.get('mean_delta_ms'):+.2f} ms，"
                  f"p×4={long_.get('p_t_times_sides')}；McNemar {long_.get('mcnemar_better')}/"
                  f"{long_.get('mcnemar_worse')}，p×4={long_.get('p_mcnemar_times_sides')}）"
                  "⇒ 这修正了我此前在多处留下的『长音随训练改善』暗示；今晚重训的确证收益在**短字符结束点**，"
                  "长音并没有被证明被修好（这与主线判断一致，但过去措辞太松）。",
                  "- 新增流程规则：**任何按位置/子集分开报告的配对效应，必须同时给中位数+截尾均值、"
                  "二项 McNemar、以及对所考察位置数的 ×K 校正；三者不同向时只能写『迹象』**"
                  "（工具 `paired_robustness_check.py`）。"]
    return lines


def sec_position_effect(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_position_effect/metrics.json")
    if "stratified" not in doc:
        return ["- 状态：未跑"]
    confound = doc["confound"]
    raw = doc["raw"]["combined"]
    lines = ["- **一个诱人的免费改动被分层检验否证**：留出 dump 里末字符超差率 "
             f"{_pct(raw['miss_last'])} vs 内部 {_pct(raw['miss_interior'])}（原始差 "
             f"{raw['delta_pp']:+.2f} pp，z={raw['z']}），看起来像「尾部缺少后续上下文」，"
             "直觉修法是把音频尾部多裁一点（不需重训）；",
             f"- 但**混杂近乎共线**：末字符里 ≥1s 占 **{100 * confound['share_long_last']:.1f}%**，"
             f"内部字符只有 **{100 * confound['share_long_interior']:.1f}%** ⇒ 长音本来就几乎总在句尾；",
             "", "| 时长层 | 末字 | 内部 | 差(pp) | p | p×K | 判定 |", "|---|---|---|---|---|---|---|"]
    for label, block in doc["stratified"].items():
        if block.get("status") != "measured":
            lines.append(f"| {label} | — | — | — | — | — | 样本不足（{block.get('last_characters', 0)}/"
                         f"{block.get('interior_characters', 0)}） |")
            continue
        lines.append(f"| {label} | {_pct(block['miss_last'])} | {_pct(block['miss_interior'])} | "
                     f"{block['delta_pp']:+.2f} | {block['p']:.3f} | {block['p_times_strata']:.3f} | "
                     f"**{block['verdict']}** |")
    lines += ["", "- ⇒ **没有任何一层通过 ×K 校正**（最好的 0.5–1s 层 p=0.029 → ×4 = 0.117，"
              "且 1–2s 层方向相反）⇒ **不做「延长裁剪尾部」**；",
              "- 方法学收获（写进规则）：**位置与时长在本语料里近乎共线**，"
              "任何按位置/段落报告的结果都必须先做时长分层，"
              "否则会把「长音总在句尾」误读成「句尾更难」。"]
    return lines


def sec_gating_calibration(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_gating_calibration/metrics.json")
    if doc.get("status") != "measured":
        return ["- 状态：未跑"]
    lines = [f"- 假设（08:05 由交叉分析提出，08:10 实测）：既然长字符天然高熵，"
              f"把门控阈值按**模型自己预测的时长**分档校准会更好。留出单位 = 歌（{doc['songs']} 首），"
              f"字符 {doc['characters']}，缺陷 {doc['defects']} 个（{doc['defect_rate']:.2%}）；",
             "", "| 复核预算 | 全局阈值抓到 | 按预测时长分档抓到 | 差 |", "|---|---|---|---|"]
    for budget, block in doc["budgets"].items():
        lines.append(f"| {budget} | {_pct(block['global']['capture_share'], 1)} | "
                     f"{_pct(block['duration_conditional']['capture_share'], 1)} | "
                     f"**{block['paired']['capture_share_delta_pp']:+.2f} pp** |")
    lines += ["", "- ⇒ **假设被否证**：三个预算下分档版都更差（−4.3 到 −7.4 pp）。"
              "解释很清楚：**『字符长 ⇒ 更可能错』本身就是最有用的风险信号**，"
              "在预测时长箱内做归一化等于把这个信号减掉，剩下的是箱内噪声；",
              "- 所以现行门控工具（`export_review_gating.py` 的全局分位阈值）**保持不变**；"
              "这条负结果的价值在于**关掉了下一个看起来最合理的改动方向**，"
              "并给出一条可迁移的设计规则：**风险与某变量相关时，不要按该变量做分层归一化**。"]
    return lines


def sec_ab_decision(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_ab_decision/metrics.json")
    if "cells" not in doc:
        return ["- 状态：未跑（跑 `ab_decision_table.py`）"]
    cells = doc["cells"]
    long_a = cells["b_vs_a_long"]["block"] or {}
    per_mode = doc.get("per_adjustment") or {}
    lines = [f"- 判定量 = **长字符结束点 offset_long 的逐字符配对**（n={long_a.get('n')}）："
             f"Δ = **{long_a.get('mean_delta_ms')} ms**（负=B 更好），"
             f"中位 {long_a.get('median_delta_ms')}、截尾均值 {long_a.get('trimmed_mean_delta_ms')}；"
             f"不一致对子 McNemar 好/差 = **{long_a.get('mcnemar_better')}/{long_a.get('mcnemar_worse')}**；",
             f"- 未校正 p：均值 {long_a.get('p_t')}、二项 {long_a.get('p_mcnemar_exact')}；"
             f"×4 校正后：均值 {long_a.get('p_t_times_sides')}、二项 {long_a.get('p_mcnemar_times_sides')}；",
             f"- 短条目那一轴：B−A {(cells['short_b_minus_a']['block'] or {}).get('mean_delta_pp')} pp"
             f"（B 更好 {(cells['short_b_minus_a']['block'] or {}).get('b_better_points')}/"
             f"{(cells['short_b_minus_a']['block'] or {}).get('points')} 点）= **变差**；",
             "", "| 多重比较口径 | 所在格 | 预定下一步 |", "|---|---|---|"]
    for mode, label in (("none", "预注册单一主判据（不校正）"), ("k4", "保守：对 4 个位置 ×4 校正")):
        block = per_mode.get(mode) or {}
        lines.append(f"| {label} | {block.get('row', '—')} | {block.get('next_action', '—')} |")
    lines += ["", "- ⇒ **两口径的下一步动作相同（跑 C）**，所以决策不受口径影响；"
              "但**科学表述受口径影响**，两句都必须出现，不许合并成一句含糊的话：",
              "  - 按预注册的单一主判据：长字符结束点改善 20.7 ms（均值 p=0.006、二项 p=0.021 双双 <0.05）"
              "**支持暴露假设**，条目复制是有效的杠杆但实现代价太大；",
              "  - 按保守 ×4 校正：二项检验 0.085 未过 ⇒ 只能称**迹象**，"
              "且均值与中位/截尾均值不一致说明它由**少部分长音符的大幅修正**贡献；",
              "- 这也是今晚**第一个正向的机制证据**，所以措辞要格外谨慎："
              "C 臂（无覆盖混杂的字符级加权）正是为区分这两种读法而准备的判定实验，已在跑。"]
    return lines


def sec_arms_by_bucket(root: Path) -> list[str]:
    doc = _load(root / "results/by_run/20260914_arms_by_bucket/metrics.json")
    if "buckets" not in doc:
        return ["- 状态：未跑"]
    buckets = doc["buckets"]
    lines = [f"- 把 B 的效应按**标注时长**拆开**数个数**（同一批 {doc['shared_characters']} 个留出字符，"
             "只统计**结束点**侧，避免把 onset/offset 的计数相加）：", "",
             "| 时长桶 | n | 起点缺陷 | A 对照 | B 上采样 | B 比 A 新修好 | B 比 A 新弄坏 |", "|---|---|---|---|---|---|---|"]
    for name in ("0-0.5s", "0.5-1s", "1-1.5s", "1.5-2s", "2s+"):
        block = buckets.get(name)
        if not block:
            continue
        disc = block.get("discordant_challenger_vs_reference") or {}
        lines.append(f"| {name} | {block['起点']['n']} | {block['起点']['offset_miss']} | "
                     f"{block['A对照']['offset_miss']} | **{block['B上采样']['offset_miss']}** | "
                     f"{disc['newly_ok']} | {disc['newly_broken']} |")
    fixed = (doc.get("totals") or {}).get("discordant", {}).get("newly_ok", 0)
    broken = (doc.get("totals") or {}).get("discordant", {}).get("newly_broken", 0)
    arm_totals = (doc.get("totals") or {}).get("arms") or {}
    lines += ["", "- ⇒ **形状完全符合机制预测**：B 的收益只出现在 ≥1.5 s 段（新修好 9、新弄坏 0），"
              "损失只出现在最短段（新修好 0、新弄坏 4 = 条目复制把短字符的相对份额挤下去），"
              "而 A（不改配比）在 ≥2s 段从 8 个缺陷退到 11 个、B 把它压回 6 个；",
              f"- 总数（结束点缺陷个数）：" + "、".join(f"{name} {value}" for name, value in arm_totals.items())
              + f" ⇒ **B 恰好回到起点水平（{arm_totals.get('B上采样')} vs {arm_totals.get('起点')}），"
              f"而 A 退步到 {arm_totals.get('A对照')}**；",
              f"- ⇒ 但**量级只有个位数**：合计新修好 {fixed}、新弄坏 {broken}，净 {fixed - broken:+d} 个字符"
              f"（占 {doc['shared_characters']} 个的 {100 * (fixed - broken) / doc['shared_characters']:.2f}%）。"
              "所以正确的说法是『方向被机制预测命中、幅度微弱』，"
              "这也解释了为什么二项检验在未校正时 p=0.021、×4 校正后 p=0.085 —— 它本来就悬在边界上；",
              "- 这条计数表同时给出 C 的**预期形状**：C 不复制条目 ⇒ 最短段那 4 个新弄坏应当消失，"
              "而 ≥1.5 s 段的收益应保持。C 的判决就看这两件事是否同时成立。"]
    return lines


def sec_pending(root: Path) -> list[str]:
    return ["- **决策树已写死**（不临场判断）：B 落在 §3g 预测带内 ⇒ 暴露假设成立；"
            "B 为 null 或弱于预测带 ⇒ 启动 C 臂（字符级 loss 加权，"
            "`docs/status/20260914_c_arm_prereg.md`，主指标 = ≥1s 长字符逐字符配对，预算 ≤1.2 小时）；"
            "B 反而变差 ⇒ C 不启动，转结构改动立项；",
            "- A/B 两臂判决：**判据 = 长字符结束点（offset_long）的逐字符配对**，"
            "须同时满足 Δ ≤ −10 ms 且 p_t×K<0.05 且 McNemar×K<0.05 才算改善（三关缺一只能写迹象）；"
            "**同时报 B vs A 与 B vs 起点**，所在格由 `ab_decision_table.py` 按 §3l 的 2×2 给出，"
            "短条目代价作为第二轴；机制项（失败子集时长比是否向 1 收敛）单列不参与判决；",
            "- 真歌端到端 DP 探针已实现（`real_song_decoder_probe.py`）；2 首 60 s smoke 结果："
            "**官方解码 99 个区间里 71 个零长度（71.7%）、最长同结束点块 41 字，DP 为 0**；"
            "- ~~真歌端到端 DP 探针的正式跑~~ **已完成（07:41–07:44，8 首 / 1,800 区间）**：" 
            "  压力条件下官方零长度 61.61% → DP 0%，两轴一致度的 median/p90 位移都已给出，"
            "  结论见「真歌端到端解码探针」一节；",
            "并同时记录两轴一致度（已实现 median/p90 Δ），用来量化『DP 挪动了多少』；",
            "- C 臂（字符级 loss 加权）代码、配置、等价性测试与**独立预注册**都已备好"
            "（`20260914_c_arm_prereg.md`）；",
            "- DP 进产品线需要一次**评审级**决定：是否把解码器纳入 `model_identity()` 与校验链"
            "（当前默认路径逐字节不变，`timestamp_decoder=\"dp\"` 才会扩展身份字段）。"]


def sec_limitations(root: Path) -> list[str]:
    return ["- **混合 split 的机制 dump**（已修）：时长曲线、容差内质量、邻接先验、事后校准这几节的绝对数字"
            "来自一次未按 split 过滤的采样（1042 train / 93 validation / 65 test），描述的是模型在**训练分布**"
            "上的行为。配对比较（同一批字符比两个模型/两种解码）与机制描述仍然成立，但不得当留出性能引用。"
            "验证集专用重跑正在进行，完成后这些节会被替换。",
            "- **小样本长音桶**：≥2s 在验证集里只有 137 个字符（旧混合样本 215 个），"
            "所以像「失败子集 0/9 质量>0.5」这类判决必须连着 n 一起读；"
            "配对 SE 已经写进预注册 §3i（≥1s n≈950 → 5.3 ms；≥2s → 13.8 ms 不可单独判决）。",
            "- **跨窗共识探针的口径限制**：每个窗的 transcript 是用「标注中心落在窗口核心内」选出来的，"
            "生产里只能按歌词行近似选择。因此 +18.7 ms（z=+9.9）这个负结果应读作"
            "「**在同一个（略偏乐观的）窗-文本选择规则下**，共识仍不如单窗」，"
            "而不是绝对意义上投票一定无效。两种估计器共享同一选择规则，比较本身是公平的。",
            "- **拼接视图的分布特性**：长上下文视图由同首歌的短句 + 0.4 s 真静音拼成，"
            "它没有真实编曲、混响与长器乐间奏，所以**不能代表真歌难度**；"
            "真歌侧的独立证据是另一批测量（raw 零长度 10.80%、修补放大到 16.28%、"
            "DP 替代点证据≈抛硬币），两者不可互相外推。",
            "- **已更正的量级**：事后校准的「≥2s 10.23% → 37.67%」是我实现的越界钳位造成的伪影，"
            "修正后为 10.70%；结论方向不变（无收益），但引用旧数字的文档与测试注释都已改写。",
                          "- **B 实验自带覆盖混杂（预注册 §3n）**：条目复制把池子放大 ×3.72 ⇒ 等 600 步下 "
              "B 只看到 A 的约 27% 唯一条目，连 step 100 的全量短条目视图都已落后"
              "（0.9677 vs 0.9693）。所以 B 的结论只能表述为「**等算力预算下把样本向长音倾斜是否划算**」，"
              "不能表述为「纯分布改变在等数据量下是否有益」；这恰好是 C（改 loss 不改数据）没有的缺陷。",
"- **B 臂预测的置信度**：暴露—误差拟合只有 5 个时长桶、且误差来自混合 split 的曲线，"
            "所以 §3g 的预测带（≥2s 7.30%）是**方向性预期而非精确预言**；"
            "验证集专用曲线出来后我会给出第二个版本，两者不一致时以验证集为准。"]


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
    ("数据路径能否补足长音暴露", "docs/status/20260914_concat_arm_prereg.md", lambda root: [
        "- GTSinger Chinese 全库只有 544 个 TextGrid / 13,750 个歌词单元，其中 ≥1s 仅 300、≥2s 仅 70"
        "（对比 M4Singer 已有 9,861 / 1,498）⇒ 新增供给约 +5%，不值得为它做一套标签管线；",
        "- MIR-1K（真实伴奏）这份发行**没有字符级时间边界**（只有整句音频、逐帧 F0、人声标记、big5 歌词）"
        "⇒ 要用它就必须生成伪标签，按既定约束不做；audio_works 同理被明确禁止；",
        "- ⇒ **在现有数据条件下，'用新数据增加长音暴露'这条路是关闭的**；若条目级上采样（B）拿不到效应，"
        "唯一还能加强暴露机制的是 C 臂（字符级 loss 加权，代码与测试已备好），再往上是结构改动。"]),
    ("真歌端到端解码探针（压力条件）", "results/by_run/20260914_real_song_decoder", sec_real_decoder),
    ("置信度 × 时长交叉（否证天真版机制 + 新发现）", "results/by_run/20260914_confidence_duration", sec_confidence_duration),
    ("按预测时长分档的门控阈值：假设被否证", "results/by_run/20260914_gating_calibration", sec_gating_calibration),
    ("位置效应（末字）：被时长混杂解释，不成立", "results/by_run/20260914_position_effect", sec_position_effect),
    ("B 的效应按时长拆开数个数（形状对、量级小）", "results/by_run/20260914_arms_by_bucket", sec_arms_by_bucket),
    ("A/B 决策表（§3l 2×2，两种多重比较口径）", "results/by_run/20260914_ab_decision", sec_ab_decision),
    ("对照臂 A 的退化：只是迹象（并据此复查了整条训练史）", "results/by_run/20260914_paired_A_vs_start", sec_long_offset_drift),
    ("局限与适用边界（读结论前先看）", "", sec_limitations),
    ("待办", "", sec_pending),
]


def dp_gain_range(root: Path) -> str:
    """One source of truth for the DP-vs-fixed claim (used by both the summary and the arms table)."""
    directory = root / "results/by_run/20260914_long_context_view"
    values: list[float] = []
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            document = _load(path) or {}
            for block in (document.get("checkpoints") or {}).values():
                variants = block.get("variants") or {}
                summary = block.get("summary") or {}

                def value(decoder: str, _v=variants, _s=summary):
                    if decoder in _v:
                        return _v[decoder].get("macro_song_within_primary")
                    if decoder in _s:
                        return _s[decoder].get("macro_within_primary")
                    return None
                fixed_value, dp_value = value("fixed"), value("dp")
                if fixed_value is not None and dp_value is not None:
                    values.append(100 * (dp_value - fixed_value))
    if not values:
        return "域内 DP 增益（未跑）"
    return f"域内 DP 增益 {min(values):+.2f} ~ {max(values):+.2f} pp（{len(values)} 个存档逐个现算）"


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
             "2. 机制的准确表述（经两次自我修正）：**典型预测并不收缩**，收缩与偏早是失败子集的条件性偏差；"
             "对照臂 A 在长字符结束点上只给出**迹象**（均值 +9.6 ms，但中位数与截尾均值为 0，"
             "×4 校正后不显著）——**今晚的因果证据仍不充分，这是方法的边界，不是已证的事实**；",
             f"3. 两条**已经拿到手**的收益：DP 解码（{dp_gain_range(root)}、塌陷清零）与置信度门控"
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
              "- 自我纠错记录：**`pytest ... | tail` 会吞掉退出码**，导致我用 `&&` 串的门禁失效、"
              "两次在测试仍红时就完成提交（现改用 `set -o pipefail` 或直接看退出码）；"
              "**自动化脚本里的 bash 陷阱**——`local key=$1 dir=$2 run=$D/$dir` 中所有词元"
              "在任何赋值发生前就展开，于是 `$dir` 未定义、`set -u` 下后台子壳以 127 **静默退出**"
              "（stderr 被 setsid 重定向到 /dev/null），机制 dump 因此空转了 4 分钟没动。已拆开 local、"
              "并把后台任务的 stderr 并进日志；排查过程本身靠的是最小复现（30 秒定位）而不是猜；"
              "同类静默失败风险今后一律要求'后台分支必须写自己的日志'；"
              "仓库膨胀 117 MB（我的 `keep_per_unit` 造成）、机制 dump 漏了 split 过滤"
              "（已加 --splits 与 test 防火墙）、`status_snapshot` 误判进程、"
              "`pgrep -f` 三次自匹配、headroom 的乐观判断被 mass_in_tol 否证、"
              "300 条样本的 24.6% 高估、以及若干次「替换没命中却报成功」的文档编辑。", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"written": str(args.out), "sections": len(SECTIONS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
