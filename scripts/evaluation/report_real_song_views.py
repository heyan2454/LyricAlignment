#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the real-song cross-view census report from its JSON artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_DIR = Path("/home/hyan/Data/lyricalign/runs/20260912_real_song_views")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else (f"{x:.2f}s" if x >= 1 else f"{1000 * float(x):.{d}f}ms")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_real_song_cross_views.md")
    args = ap.parse_args()
    st = json.loads((args.dir / "VIEWS_PANEL_SUMMARY.json").read_text(encoding="utf-8"))
    a = json.loads((args.dir / "VIEWS_ANALYSIS.json").read_text(encoding="utf-8"))
    comp, pairs = a["comparability"], a["pair_disagreement"]
    prov = st.get("identity_provenance", {})

    L: list[str] = []
    w = L.append
    w("# 真实长歌跨视图一致度普查（25 首 · 无真值 · 2026-09-12 第 5 轮）")
    w("")
    w("> 数字由 `runs/20260912_real_song_views/{VIEWS_PANEL_SUMMARY,VIEWS_ANALYSIS}.json` 生成。")
    w("> 纯 CPU 复用 2026-08-14/15 的真实歌曲对齐产物；零新增前向；无真值 ⇒ 只测分歧，不判对错。")
    w("")
    w("## 0. 结论先说：这批真实长歌证据**不能**支撑任何\"机制对比\"结论")
    w("")
    w(f"- 三个视图里只有一对可按索引比较：**B4 vs current_silence**（{pct(comp['share_b4_cur_character_identical'],1)} "
      "位置文本一致）；而 `full_slot` 有 "
      f"{pct(1 - comp['share_b4_slot_character_identical'],1)} 的位置落在**不同字符**上"
      "（该 run 会跳过/重复单元导致索引漂移），且其音频 sha 未记录（"
      f"b4↔slot 同 sha 占比 {pct(comp['audio_sha_identical_b4_slot'],1)}）⇒ 不能做逐单元比较。")
    w(f"- 而那唯一可比的一对，输出几乎完全相同：>{sec(0.1,0)} 分歧占比仅 "
      f"{pct(pairs['b4_vs_cur']['share_gt_100ms'],2)}（{int(round(pairs['b4_vs_cur']['share_gt_100ms'] * pairs['b4_vs_cur']['comparable_units']))} 个单元）。"
      "**它们根本不是两种规划**：窗口计划逐字段相同（同 policy、同 60s core、同 10s 左上下文、同 committed 区间）。")
    w("- ⇒ 因此 2026-08-14 交付的 `B4 vs Current` 四路诊断视频/KTV 对照，**在留存证据里不构成已识别的因子对比**；"
      "真实长歌上目前**没有任何可用的多视图证据**。")
    w("")
    w("## 1. 视图身份溯源（问题定位）")
    w("")
    w("| 视图 | 产出 runner（identity.schema_version） | 记录 silence 标志的歌曲数 |")
    w("|---|---|---:|")
    for view, v in prov.items():
        schemas = "、".join(f"`{k}`×{n}" for k, n in v["schema_versions"].items())
        w(f"| `{view}` | {schemas} | {v['songs_recording_silence_flags']}/{v['n_songs']} |")
    w("")
    w("- 批处理视图（`qwen_fa_batch_alignment_v4_*`）的 `identity.window` **完全不记录** "
      "`skip_silent_windows / silence_aware_window_plan / strong_silence_anchor_sec / "
      "leading_silence_min_sec / tail_min_core_sec` 等标志（全部 None）"
      "⇒ 即使标志生效，产物里也无法核对；这是 request-identity 的**记录缺口**，"
      "正是 AGENTS 里\"缓存身份必须并入代码/配置\"要求在长歌 demo 链路上的破口。")
    w("- 两个视图的音频路径不同（一份在 `test/<Lang>/<song>_qwen_fa/work/audio/vocals.wav`，"
      f"一份在 `runs/20260814_ktv_current_silence/<song>/work/…`），但内容 sha 一致率 "
      f"{pct(comp['audio_sha_identical_b4_cur'],1)}（按单元计）⇒ 同一段分离人声被复制两份，"
      "后续若要真正做\"分离 vs 混音\"因子，必须先消除这种同内容双路径。")
    w("")
    w("## 2. 可比对的分歧量级（唯一有效的一对）")
    w("")
    w("| 配对 | 可比单元 | 中位分歧 | p90 | p99 | >100ms | >250ms |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for name, v in pairs.items():
        note = "" if name == "b4_vs_cur" else "（**不可用于结论**：索引错位）"
        w(f"| `{name}`{note} | {v['comparable_units']:,} | {sec(v['median_sec'])} | "
          f"{sec(v['p90_sec'])} | {sec(v['p99_sec'])} | {pct(v['share_gt_100ms'],2)} | "
          f"{pct(v['share_gt_250ms'],2)} |")
    w("")
    w("## 3. 各语言的退化单元比例（这是本面板**唯一可靠**的跨视图信息，来自 single-view 统计）")
    w("")
    w("| 语言 | 单元 | 歌曲 | B4 零时长率 | full_slot 零时长率 |")
    w("|---|---:|---:|---:|---:|")
    for r in a["by_language"]:
        w(f"| {r['language']} | {r['units']:,} | {r['songs']} | {pct(r['zero_dur_b4'],1)} | "
          f"{pct(r['zero_dur_slot'],1)} |")
    w("")
    w(f"- 真实伴奏流行歌上的零时长单元比例高得离谱（中文 {pct(a['by_language'][1]['zero_dur_b4'],1)}、"
      "英文约 23%、日文 45-53%），与 GTSinger 干净录音上的 2-4% 完全不同量级："
      "**产品化必须把零时长/退化区间当作首要结构 gate**，而不是把它当成可忽略的边角。")
    w("")
    pa_path = args.dir / "POSTPROCESS_ATTRIBUTION.json"
    if pa_path.exists():
        pa = json.loads(pa_path.read_text(encoding="utf-8"))
        hv = pa["headline"]
        b4 = pa["views"]["b4_60s_windowed"]
        w("## 3b. 后处理归因（无真值，纯结构）：**干净结构是靠压扁单元换来的**")
        w("")
        w(f"- 退化（零/负时长）单元：清理前 {pct(b4['raw_degenerate_share'],1)} → 清理后 "
          f"**{pct(b4['selected_degenerate_share'],1)}**；"
          f"清理创建 {b4['created_by_postprocess']} 个、修复 {b4['healed_by_postprocess']} 个"
          f"（净 **{b4['net_change_in_degenerate']:+d}**）⇒ 判定：{hv['verdict']}。")
        w(f"- 机制与第 2 轮同型但更温和：被移动的起点中 "
          f"{pct(hv['mechanism']['start_pinned_to_prev_end'],1)} 落在前一单元 selected 尾端、"
          f"{pct(hv['mechanism']['end_pinned_to_next_start'],1)} 的尾端落在下一单元起点；"
          f"相邻重叠率 {pct(hv['mechanism']['overlap_rate_before'],1)} → "
          f"{pct(hv['mechanism']['overlap_rate_after'],2)}（连续性确实被强制执行）。")
        rd, sd = b4["raw_structural_defects"], b4["selected_structural_defects"]
        w(f"- **raw 解码本身在真实伴奏歌上结构就不成立**："
          f"负时长 {pct(rd['negative_duration_share'],1)}、时长>3s {pct(rd['duration_over_3s_share'],1)}、"
          f"单单元最长 raw 时长 **{rd['max_raw_duration_sec']}s**（中位仅 {rd['median_raw_duration_sec']}s）、"
          f"起点回退 {pct(rd['start_regression_share'],1)}；清理后这些分别为 "
          f"{pct(sd['negative_duration_share'],1)} / {pct(sd['duration_over_3s_share'],1)} / "
          f"{pct(sd['start_regression_share'],1)} —— 全部被\u300c压成零长\u300d抹平而非修好。")
        cg = b4["created_degenerate_origin"]
        w(f"- 被压扁的 {cg['n']} 个单元里 {pct(cg['share_from_overshoot_gt1s'],1)} 原本 raw 时长 >1s"
          f"（中位 {cg['median_raw_duration_of_created_sec']}s）"
          f"⇒ 后处理是在**掩盖 gross 解码错误**，不是在修复边界。")
        w("")
        w("按单元类型（关键：普通话最健康，灾难在 word 单元路径）：")
        w("")
        w("| 单元类型 | 单元数 | raw 退化 | 清理后退化 | raw 负时长 | raw 最长时长 |")
        w("|---|---:|---:|---:|---:|---:|")
        for ut, v in sorted(b4.get("by_unit_type", {}).items(),
                            key=lambda kv: -kv[1]["selected_degenerate_share"]):
            w(f"| `{ut}` | {v['units']:,} | {pct(v['raw_degenerate_share'],1)} | "
              f"{pct(v['selected_degenerate_share'],1)} | {pct(v['raw_negative_share'],1)} | "
              f"{v['max_raw_duration_sec']}s |")
        w("")
        w("- ⇒ 对\u300c优先普通话\u300d的直接含义：中文字符路径清理后退化率 9.7%（GTSinger 干净数据 2-4%），"
          "而英/日 word 路径 23-53% ⇒ **word 单元化策略与解码结构约束是普通话之外语言的主要故障源**；"
          "普通话侧真正该做的是把 9.7% 的退化率压下去（约束解码或单调性修复），"
          "而不是继续在边界毫秒级打磨。")
        w("")
    w("## 4. 与前三轮结论的接续")
    w("")
    w("- 第 1 轮：GTSinger 上 12 配置矩阵是假因子 ⇒ 本轮在真实长歌上又发现一个假因子"
      "（B4 vs current_silence 计划相同）。**\"配置写了不同标签\"不等于\"跑了不同配置\"**，"
      "这条已经两次被证实，必须进流程。")
    w("- 第 5 轮共识模拟：自然录音上共识只关 7.4% 上界差距 ⇒ 真实长歌这边连可用的多视图证据都没有，"
      "所以`multi-view / recrop` 线要推进，缺的不是算法而是**一次带完整身份记录的多视图采集**。")
    w("- 建议（不花 GPU 就能做）：把本模块的\"可比性检查\"（文本逐位一致 + 音频 sha 相同 + 窗口计划不同）"
      "作为任何跨视图实验的**前置门**，三条不满足就直接拒绝出对比结论。")
    w("")
    w("## 5. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python -c \"from pathlib import Path;")
    w("from lyricalign.analysis import real_song_views as R;")
    w("d=Path('/home/hyan/Data/lyricalign/runs/20260912_real_song_views'); st=R.build_panel(d)")
    w("df=R.load_frame(Path(st['out'])); a=R.analyse(df)")
    w("(d/'VIEWS_ANALYSIS.json').write_text(__import__('json').dumps(a,ensure_ascii=False,indent=2))\"")
    w("PYTHONPATH=src python scripts/evaluation/report_real_song_views.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_real_song_views.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    metrics = {
        "schema_version": "real_song_views_metrics_v1", "run": "20260912_real_song_views",
        "source": str(args.dir), "no_ground_truth": True,
        "panel": a["panel"], "comparability": comp, "pair_disagreement": pairs,
        "identity_provenance": prov, "by_language": a["by_language"],
        "per_song": a["per_song"], "seam_head_profile": a.get("seam_head_profile"),
        "seam_tail_profile": a.get("seam_tail_profile"),
        "posterior_predicts_disagreement_auc": a.get("posterior_predicts_disagreement_auc"),
        "postprocess_attribution": (json.loads((args.dir / "POSTPROCESS_ATTRIBUTION.json").read_text(encoding="utf-8"))
                                    if (args.dir / "POSTPROCESS_ATTRIBUTION.json").exists() else None),
        "headline": {
            "comparable_pair_units": pairs["b4_vs_cur"]["comparable_units"],
            "comparable_pair_share_gt100ms": pairs["b4_vs_cur"]["share_gt_100ms"],
            "full_slot_index_mismatch_share": round(1 - comp["share_b4_slot_character_identical"], 4),
            "views_recording_silence_flags": {
                view: f"{v.get('songs_recording_silence_flags', 0)}/{v.get('n_songs', 0)}"
                for view, v in prov.items()},
            "zero_duration_worst_language_b4": max(
                a["by_language"], key=lambda r: r["zero_dur_b4"])["language"],
            "conclusion": "B4 vs current_silence is not an identified contrast; no usable multi-view "
                          "evidence exists on natural long songs",
            "degenerate_before_cleanup": (pa["headline"]["degenerates_before_cleanup"]
                                          if pa_path.exists() else None),
            "degenerate_after_cleanup": (pa["headline"]["degenerates_after_cleanup"]
                                         if pa_path.exists() else None),
            "raw_negative_duration_share": (pa["views"]["b4_60s_windowed"]["raw_structural_defects"]
                                            ["negative_duration_share"] if pa_path.exists() else None),
            "cjk_selected_degenerate_share": (pa["views"]["b4_60s_windowed"]["by_unit_type"]
                                              .get("cjk_character", {}).get("selected_degenerate_share")
                                              if pa_path.exists() else None),
            "japanese_word_selected_degenerate_share": (
                pa["views"]["b4_60s_windowed"]["by_unit_type"].get("japanese_word", {})
                .get("selected_degenerate_share") if pa_path.exists() else None),
        },
    }
    mout = REPO / "results/by_run/20260912_real_song_views/metrics.json"
    mout.parent.mkdir(parents=True, exist_ok=True)
    mout.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(mout)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
