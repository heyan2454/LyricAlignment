#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the session handoff page from the canonical metrics files (no hand-copied numbers).

    PYTHONPATH=src python scripts/evaluation/make_session_handoff.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BY_RUN = REPO / "results" / "by_run"
OUT = REPO / "docs" / "status" / "20260912_session_handoff.md"

# which metrics dirs hold which headline facts, and how each should be labelled
SECTIONS = [
    ("已确认（可据此行动）", [
        ("20260912_gtsinger_gt_deep", "GTSinger 人工真值上的逐单元效应与证据"),
        ("20260912_mir1k_natural_panel", "MIR-1K 自然收尾人工真值面板"),
        ("20260912_structural_compliance", "交付时间线结构合规 + 后处理净新增零长"),
        ("20260912_raw_degeneracy", "raw 起止倒序取证（塌陷前兆 lift 与覆盖）"),
        ("20260912_measurement_validity", "测量有效性：绝对精度是含退化单元的保守下界"),
        ("20260912_decodability_ceiling", "可解码上限（真值是否在 top-2 候选内）"),
        ("20260912_multi_view_ceiling", "多视图并集 oracle 与错误相关性"),
        ("20260912_metric_stability", "指标可分辨限（格点余量、带边稳定性）"),
        ("20260912_gate_operating_points", "gate 工作点的标签侧天花板（SAFE 边选择）"),
        ("20260912_gate_band_policy", "gate 实测 vs 天花板 + 分数阶梯（含免费信号增量）"),
        ("20260912_gate_batch_application", "真实歌批上的无真值结构审计（放行集合安全性）"),
        ("20260912_label_noise_ceiling", "标签量化噪声与阈值敏感性"),
        ("20260912_zero_length_profile", "零长度字的块状分布与位置效应"),
        ("20260912_degenerate_run_lineage", "超长塌陷的逐阶段归因（fixed 阶段）"),
        ("20260912_fixed_stage_root_cause", "根因：上游 _fix_timestamps 常数填充"),
        ("20260912_shadow_repair_value", "修塌陷的代价（一刀切 vs 定向）"),
        ("20260912_combined_repair_shadow", "组合修复影子对照（最终建议：只改塌陷）"),
        ("20260912_shadow_batch_audit", "改前/改后批次自检预览（33 首逐首）"),
        ("20260912_eval_contamination", "评测集污染度（历史精度须并列去退化值）"),
        ("20260912_bias_excluding_degenerate", "长音反向偏置的去退化复核"),
        ("20260912_longform_pipeline_candidate", "长时序端到端候选（联合求解 vs 现装）"),
        ("20260912_cross_window_selection", "跨窗共识/选择（含选择器无效证据）"),
        ("20260912_gtsinger_multiview", "多视图选择实验 + 因子内容审计"),
        ("20260912_real_song_views", "真实歌多视图可比性与后处理归因"),
        ("20260912_joint_cleanup", "联合约束求解 vs 顺序规则（结构会计）"),
    ]),
    ("已否证 / 已降级（不要重复投入）", [
        ("20260912_tail_acoustics", "事后声学阈值修末字/长音"),
        ("20260912_inversion_policy", "局部修补倒序（交换/顺延）"),
        ("20260912_trigger_replication", "间隙触发器跨语料复现"),
        ("20260912_evidence_identity_audit", "历史批次对比的可归因性"),
        ("20260912_separation_leakage", "分离泄漏强形式被反驳（产品批 demucs 输入）"),
    ]),
    ("预算与决策", [
        ("20260912_redecode_budget", "重解码预算的可达上界"),
        ("20260912_trigger_fusion", "免费触发器的召回/精度"),
        ("20260912_gap_shape", "字间隙触发器（GTSinger 口径）"),
    ]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    L: list[str] = []
    w = L.append
    w("# 2026-09-12 会话交接页（第 1–33 轮，机器生成）")
    w("")
    w("> 本页数字全部取自 `results/by_run/*/metrics.json`（canonical metric source），"
      "由 `scripts/evaluation/make_session_handoff.py` 生成；解读请看对应报告与"
      "`docs/status/20260912_session_findings_index.md`。")
    w("> 硬约束：realign 仍 shadow-only（`actual_writeback=0`）；未从 test/OOD 选 checkpoint；"
      "本会话零 GPU、未删除任何既有产物。")
    w("")
    missing: list[str] = []
    for title, entries in SECTIONS:
        w(f"## {title}")
        w("")
        w("| 主题 | canonical 来源 | headline（机器摘取） |")
        w("|---|---|---|")
        for name, desc in entries:
            path = BY_RUN / name / "metrics.json"
            if not path.exists():
                missing.append(name)
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            head = data.get("headline") or {}
            bits: list[str] = []
            for k, v in list(head.items())[:6]:
                if isinstance(v, (int, float, bool)) or v is None:
                    bits.append(f"`{k}`={v}")
                elif isinstance(v, str) and len(v) < 160:
                    bits.append(f"`{k}`=「{v}」")
                elif isinstance(v, dict) and len(v) <= 6:
                    bits.append(f"`{k}`=" + ", ".join(f"{kk}:{vv}" for kk, vv in v.items()))
            w(f"| {desc} | `results/by_run/{name}/metrics.json` | "
              + ("；".join(bits) if bits else "见文件") + " |")
        w("")
    if missing:
        w(f"（无 metrics.json 的条目：{', '.join(missing)}）")
        w("")
    w("## 立即可用的三件产物")
    w("")
    w("- `scripts/evaluation/audit_batch.py`：一条命令做可归因性 / 结构合法 / 阶段归因 / "
      "钉锚点 / 起止顺序 / 修复可行性六项检查（gate 阈值集中在 `GATES`）；")
    w("- `docs/status/20260912_predelivery_checklist.md`：交付前检查清单（含本会话新增的口径规则）；")
    w("- `docs/status/20260912_session_findings_index.md`：按轮次的结论索引（✅/❌/♻️/⛔ 标注）。")
    w("")
    w("## 仍待办（含需要资源的两项）")
    w("")
    w("- **训练侧**（唯一被证明能抬高上限的方向：长音端点不可达率 70.8%→21.7%，r1→r2 已递减）：需 GPU；")
    w("- **能产生新候选的重解码实验**（更长右上下文 / 换窗口；须按域分别验证，"
      "因为长音端点偏置方向在清唱与伴奏间相反）：需 GPU；")
    w("- **产品语义决定**：raw 起止倒序目前是「静默钳成零长」，可选 (a) 重排 (b) 标 "
      "needs_redecode (c) 仅计入 summary（观测已实现）；")
    w("- **真实长片段自然收尾的人工真值**：GTSinger 全曲连续片段方案已评估可行（第 9 轮），需少量 GPU；")
    w("- 三项 HEAD 自带失败测试（`test_archive_builder`、`test_inline_realign_v4_full_mechanism`、"
      "`unit_realign/test_request_families`）本会话刻意未动，属主线待处理。")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "missing": missing}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
