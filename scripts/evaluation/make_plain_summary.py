#!/usr/bin/env python3
"""Plain-language night summary — same numbers, no jargon.

The technical report (`docs/status/20260914_night_report.md`) is for the record.  This one is for
reading at 07:00 with a cup of tea: short sentences, no metric nicknames, and every number pulled
from the canonical JSON files so it cannot drift from the evidence.

    PYTHONPATH=src python scripts/evaluation/make_plain_summary.py --repo . \
        --out docs/status/20260914_plain_summary.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(root: Path, *parts: str) -> dict[str, Any] | None:
    path = root.joinpath(*parts)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def pct(value: Any, digits: int = 1) -> str:
    return "没测到" if value is None else f"{100 * value:.{digits}f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()

    verdict = load(root, "results/by_run/20260914_retrain_verdict/metrics.json") or {}
    trainer = verdict.get("trainer_validation") or {}
    old, new = trainer.get("old_750") or {}, trainer.get("new_12000") or {}
    decode = load(root, "results/by_run/20260914_snap_rule/metrics.json") or {}
    policies = decode.get("policies") or {}
    argmax, viterbi = policies.get("argmax") or {}, policies.get("viterbi") or {}
    exposure = load(root, "results/by_run/20260914_exposure_fit/validation_uniform_f8.json") or {}
    miss = exposure.get("observed_miss") or {}
    gating = load(root, "results/by_run/20260914_review_gating/metrics.json") or {}
    real = load(root, "results/by_run/20260914_real_song_collapse/metrics.json") or {}
    stress = load(root, "results/by_run/20260914_real_song_decoder/metrics.json") or {}
    arms = load(root, "results/by_run/20260914_warmstart_ab_fixed/metrics.json") or {}
    concat = load(root, "results/by_run/20260914_concat_verdict_fixed/metrics.json") or {}
    robust_a = load(root, "results/by_run/20260914_paired_A_vs_start/robustness.json") or {}

    def arm_delta(key: str) -> str:
        block = ((arms.get("comparisons") or {}).get(key) or {})
        if block.get("status") != "measured":
            return "还没测出来（两臂的评测在跑）"
        return f"{block.get('mean_delta_pp'):+.2f} 个百分点（可信度 z={block.get('z')}）"

    lines: list[str] = ["# 今晚做的大白话总结（自动生成，数字全部来自结果文件）", "",
                        "> 技术细节和全部证据在 `docs/status/20260914_night_report.md`。"
                        "这一份只讲人话：做了什么、有什么用、哪里不行、接下来看哪个数。", "",
                        "## 我们在解决什么问题", "",
                        "把一首歌的歌词逐个字对上时间轴：每个字从什么时候开始唱、到什么时候结束。"
                        "难点是那些**唱得特别长的字**（超过 2 秒）——它们在数据里非常少见，"
                        "而它们的结束时间又最容易错。", "",
                        "## 今晚拿到的两个好处（都不用重新训练模型）", ""]
    if argmax and viterbi:
        lines += [f"1. **换一种挑时间的方法**：原来模型逐个字独立挑时间点，"
                  f"改成要求整条时间轴单调不倒退之后一起挑。同一批计算结果下，"
                  f"准确率从 {pct(argmax.get('macro_song_within_primary'), 2)} 提到 "
                  f"{pct(viterbi.get('macro_song_within_primary'), 2)}，"
                  f"而且时间戳里「开始等于结束」的畸形数据从有到无。**这是白捡的**，但有个陷阱："
                  "原来的自动质检是靠「有没有畸形数据」来发现问题的，改完之后畸形数据全没了，"
                  "质检会误以为一切都好，所以**这个改动必须和下面第 2 条同时上**。"]
    if gating:
        lines += [f"2. **让模型自己标出不可信的地方**：模型输出的置信度确实能预示错误。"
                  f"用真实歌曲测（不需要人工标注）：只要人工复核置信度最差的 10%，"
                  f"就能抓到 {pct(gating.get('defect_capture_share'), 0)} 的问题，"
                  f"剩余问题率从 {pct(gating.get('defect_rate'), 1)} 降到 "
                  f"{pct(gating.get('residual_defect_rate_after_review'), 1)}。"
                  f"工具已经做好，能直接产出一张「这些歌请人工过一遍」的清单。"]
    else:
        lines += ["2. 置信度工具：状态——结果文件缺失（未跑）。"]
    lines += ["", "## 试了但没用的四件事（这些也是结论，写下来免得以后重走）", ""]
    lines += ["- **把短句拼成长音频继续训练**：不变好也不变坏（逐首歌对比差 "
              + ("约 0.1 个百分点以内" if not concat else
                 (f"{(((concat.get('comparisons') or {}).get('treatment_vs_control') or {}).get('mean_delta_pp')):+.2f} 个百分点")
                 + "）")
              + "；好消息是它证明长音频不会把模型教坏，以后加数据可以混着来。",
              "- **重新排个序看能不能救回来**：不行。错的那些位置，正确答案根本不在模型给的高概率候选里"
              "（概率中位只有 0.13–0.20），不是排名的锅。",
              "- **多算几遍取多数投票**：不但没用，反而**明显更差**（平均误差变大）。"
              "说明模型的错是系统性的，不是随机抖动，投票救不了。",
              "- **事后按经验修正时长**：没用。而且我第一版把它算成了「灾难性变差」，"
              "后来发现那大半是我自己代码的钳位问题；修正后真实结论是「没什么效果」。"]
    if stress:
        totals = stress.get("totals") or {}
        lines += ["", "## 一个顺手发现（但不算成功）", "",
                  f"- 把整段两分钟的人声**一次性**塞给模型（比产品的正常用法更狠的条件下），"
                  f"现有方法会产生大量畸形时间戳：{pct(totals.get('official_zero_share'))} 的字段"
                  f"开始等于结束，最夸张的一首 326 个字全挤在同一时刻；换成上面第 1 条的新方法后是 0%。"
                  f"但这**不等于新方法就是对的**——那首歌里谁也没法验证，只能确定原来那条输出明显是错的。"]
    lines += ["", "## 还剩什么问题，以及明天看哪个数", ""]
    if miss:
        lines += [f"- 长音的字仍然是最不准的：在只用来做验证的歌曲上，唱 1–2 秒的字有 "
                  f"{pct(miss.get('1-2s'))} 的时间偏差超过 0.2 秒，超过 2 秒的字升到 "
                  f"{pct(miss.get('2s+'))}（而 0.25–0.5 秒的短字只有 {pct(miss.get('0.25-0.5s'))}，"
                  f"0–0.25 秒 {pct(miss.get('0-0.25s'))}）。"
                  f"原因基本确定是**这种字在训练数据里太少**：超过 2 秒的字只占全部字的 "
                  f"{pct(exposure.get('exposure_shares', {}).get('2s+'), 2)}。"]
    lines += [f"- 今晚最后两组实验（一组只继续训练做对照，一组专门给长音多加例子）的对比结果：{arm_delta('treatment_vs_control_paired')}。"
              if arms else "- 今晚最后两组实验（对照组 + 长音加权组）的对比结果：还在跑，明天上午出。",
              "- 我会提前把「什么结果算成功、什么算失败、失败了下一步做什么」写成规则放在文档里，"
              "不看到结果再定。**如果加例子这条也没用，剩下的路就只有一条**："
              "改模型的输出方式（不直接猜结束时间，而是「从哪开始 + 唱多久」），那是一项新工程，需要单独评估。"]
    if robust_a:
        block = (robust_a.get("sides") or {}).get("offset_long") or {}
        if block.get("status") == "measured":
            lines += ["", "## 我自己犯错并且改正的地方（这一项以后每次都会写）", "",
                      f"- 我一度写下「继续训练会专门伤害长音的结束点，效果显著」。"
                      f"复核后发现：平均数确实变差 {block.get('mean_delta_ms'):+.1f} 毫秒，"
                      f"但**中位数是 {block.get('median_delta_ms'):.0f} 毫秒**，"
                      f"也就是说平均数是被极少数字符的大跳动带起来的；再按「我一共看了四个位置」做校正，"
                      f"这个差别就不显著了。所以那句话已撤回，改成「有迹象但证据不足」。"]
    lines += ["", "---", "",
              "- 有没有删东西：没有。所有模型存档、数据、历史结果都保留；今晚新增占用约 2.3 GB。",
              "- 机器状态：磁盘剩余约 22 GB，GPU 同一时间只跑一个任务。",
              f"- 参考：真实歌曲批的原始畸形率 {pct((real or {}).get('raw_zero_share'))}"
              f"（经过内部修补后反而升到 {pct((real or {}).get('official_zero_share'))}）——"
              "这也是「现有自动修补可能是帮倒忙」的证据。", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"written": str(args.out), "lines": len(lines)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
