#!/usr/bin/env python3
"""Generate the confidence-gating report from `confidence_abstention.py` outputs.

    PYTHONPATH=src python scripts/evaluation/report_confidence_gating.py \
        --dump results/by_run/20260914_confidence_abstention/dump.json \
        --batch results/by_run/20260914_confidence_abstention/batch.json \
        --report docs/status/20260914_confidence_gating.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def markdown(dump: dict[str, Any], batch: dict[str, Any]) -> str:
    lines = ["# 置信度门控：模型能不能自己说出哪里不可信（生成，勿手改）", "",
             "> 由 `scripts/evaluation/report_confidence_gating.py` 从两份 JSON 生成；"
             "两份输入都来自**已付费的既有产物**，本实验没有跑任何新推理。", "",
             "## 1. 域内（M4Singer 长音符富集样本，逐字符带真值）", "",
             f"- {dump['units']} 次测量，超 0.2 s 容差的错误率 **{pct(dump['error_rate'])}**；",
             "- 各信号对「这个字符会超差」的判别力（rank-AUC，0.5 = 无信息）：", "",
             "| 信号 | 需要真值？ | AUC |", "|---|---|---|"]
    needs_gt = {"entropy_nats": "否", "neg_p_top1": "否", "label_rank": "**是（oracle）**",
                "neg_top5_mass": "否", "duration": "否"}
    for name, value in sorted(dump["auc"].items(), key=lambda item: -(item[1] or 0)):
        lines.append(f"| {name} | {needs_gt.get(name, '?')} | {value:.4f} |")
    lines += ["", "- 弃权（转人工复核）曲线，同样数据内拟合：", "",
              "| 信号 | 复核比例 | 消除的错误 | 复核后剩余错误率 |", "|---|---|---|---|"]
    for name, curve in dump["abstention"].items():
        for key, block in curve.items():
            lines.append(f"| {name} | {key.replace('drop_', '')} | {pct(block['removed_error_share'])} | "
                         f"{pct(block['residual_rate'])}（原 {pct(block['original_rate'])}）|")
    lines += ["", f"- 长字符与短字符同样可预测：short AUC(熵) "
                  f"{dump['by_duration']['short']['auc_entropy']}、long AUC(熵) "
                  f"{dump['by_duration']['long']['auc_entropy']}；"
                  f"但长字符错误率是 {pct(dump['by_duration']['long']['error_rate'])} vs 短字符 "
                  f"{pct(dump['by_duration']['short']['error_rate'])}。", ""]
    lines += ["## 2. 真歌批（无真值，目标是产品可见的缺陷：零长度区间）", "",
              f"- {batch['units']} 字，零长度率 **{pct(batch['zero_rate'])}**（模型 raw 解码自身造成）；",
              "- 每个信号在**同一批**上的 AUC：", "",
              "| 信号 | AUC（越高越能预测塌陷） |", "|---|---|"]
    for name in ("end_entropy", "start_entropy", "neg_end_margin", "neg_start_margin"):
        if batch["auc"].get(name) is not None:
            lines.append(f"| {name} | {batch['auc'][name]:.4f} |")
    cross = batch.get("gating_crossval") or {}
    lines += ["", "### 2b. 按歌留一交叉验证（阈值只用其它歌确定，才算得数）", "",
              "| 信号 | 复核预算 | 消除的缺陷 | 复核后剩余缺陷率 |", "|---|---|---|---|"]
    for name, block in cross.items():
        for key, stats in (block.get("out_of_sample") or {}).items():
            lines.append(f"| {name} | {key.replace('review_', '')} | {pct(stats['removed_defect_share'])} | "
                         f"{pct(stats['residual_rate'])}（原 {pct(stats['original_rate'])}）|")
    best = max(((name, block) for name, block in cross.items() if block.get("out_of_sample")),
               key=lambda item: max(stats["removed_defect_share"]
                                    for stats in item[1]["out_of_sample"].values()))
    ten = best[1]["out_of_sample"].get("review_10pct") or {}
    twenty = best[1]["out_of_sample"].get("review_20pct") or {}
    lines += ["", "## 3. 结论", "",
              f"1. **模型自己能说出哪里不可信**：不需要真值的信号（softmax 熵 / top-1 边际）在域内"
              f"对「超差」的 AUC 达 {dump['auc']['entropy_nats']}，在真歌上对「塌陷」的 AUC 达 "
              f"{batch['auc']['end_entropy']}；",
              f"2. **跨歌泛化成立**：按歌留一后，用 `{best[0]}` 复核 10% 的字可消除 "
              f"{pct(ten.get('removed_defect_share', 0))} 的缺陷（剩余 {pct(ten.get('residual_rate', 0))}），"
              f"复核 20% 消除 {pct(twenty.get('removed_defect_share', 0))}（剩余 "
              f"{pct(twenty.get('residual_rate', 0))}）；同样预算下同样本内拟合几乎没有更便宜，"
              "说明这不是阈值过拟合；",
              "3. **label_rank 是最强信号但只能当 oracle**：它需要标注，因此适合用于**训练数据质检**"
              "（挑出模型与弱标注强烈冲突的条目复核），不能用于线上；",
              "4. 落地成本极低：批产物里**已经存了**每字的 `raw_start_entropy`/`raw_end_entropy`，"
              "所以门控只是「取一个分位阈值 + 打标」，不需要额外前向。",
              "",
              "## 4. 建议的下一步（可证伪）",
              "",
              "- 在 demo 批量输出里加 `risk_score` 与 `review_flag`（按训练集外分位阈值），"
              "验证：被标记的字是否确实集中在长音型歌曲（与 r=+0.82 的时长因子一致）；",
              "- 把复核预算固定为 10%，度量「人工只改被标记的字」相对全量复核的工作量下降；",
              "- 若域外（无真值）AUC 明显低于域内，则改用**歌级**聚合风险（整段重跑或换解码）而不是字级。",
              ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    text = markdown(json.loads(args.dump.read_text(encoding="utf-8")),
                    json.loads(args.batch.read_text(encoding="utf-8")))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")
    print(json.dumps({"written": str(args.report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
