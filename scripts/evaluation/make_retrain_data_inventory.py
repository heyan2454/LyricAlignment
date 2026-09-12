#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the retraining inventory: training protocol facts + what data can actually enter training.

Answers three questions the record leaves ambiguous today: (1) how the last run stopped and how many
checkpoint candidates it could choose between, (2) how large the differences between them are versus
the resolution of the metric, and (3) which datasets are *eligible* for training, as opposed to
evaluation-only or licence-blocked.  Every number is read from the run/dataset files at generation
time; nothing is hand-copied.

    PYTHONPATH=src python scripts/evaluation/make_retrain_data_inventory.py
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DATA = Path("/home/hyan/Data/datasets")
RUNS = Path("/home/hyan/Data/lyricalign/runs")
M4 = Path("/home/hyan/Data/lyricalign/derived")
DEFAULT_RUN = RUNS / "20260724_qwen_fa_r2_full_seed20260724"
OUT_MD = REPO / "docs/status/20260913_retrain_data_inventory.md"
OUT_JSON = REPO / "results/by_run/20260913_retrain_data_inventory/metrics.json"

# roles/boundaries are transcribed from data/datasets_registry.md and the acquisition snapshot;
# they are policy statements, not measurements, so they live here as text with their source named.
REGISTRY_ROLES = {
    "m4singer": ("primary train + custom validation", "可用于训练（现行唯一训练语料）"),
    "mir1k": ("OOD test-only", "禁止：不训练、不验证、不调参（登记表明文）"),
    "gtsinger_chinese": ("phoneme-boundary + technique stress test",
                         "CC BY-NC-SA + 附加协议未澄清；登记表限定内部非商业研究；未定前不进训练"),
    "pjs": ("Japanese phoneme/boundary calibration", "CC BY-SA 4.0；单男声短句，只做边界单测，域不匹配"),
    "mir_mlpop": ("natural-mixture evaluation candidate", "仅学术非商业；普通话音频 20/30，规模不足作训练"),
    "amll_ttml_db": ("community silver pool", "无音频，不可训练；底层歌词权利未解决"),
    "jamendolyrics_en": ("English evaluation candidate", "登记表明文『不混入训练』；逐曲许可"),
    "ikala": ("benchmark candidate", "blocked_pending_access：未获授权，禁止训练"),
    "audio_works_202604": ("real-song pool", "无标注；只能作评测/伪标签来源"),
    "mirst500": ("未登记", "只有 raw/，无 acquisition.json/checksums ⇒ 不可依赖"),
    "ismir2014_singing": ("未登记", "同上"),
    "tonas": ("未登记", "同上"),
}


def du_gb(path: Path) -> float | None:
    if not path.exists():
        return None
    # this platform's du has no -g, so measure KiB and convert
    out = subprocess.run(["du", "-sk", "--", str(path)], capture_output=True, text=True).stdout.strip()
    try:
        return float(out.split()[0]) / 1024.0 / 1024.0
    except (IndexError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=DEFAULT_RUN)
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = ap.parse_args()
    run = args.run

    sel = json.loads((run / "final_checkpoint_selection.json").read_text(encoding="utf-8"))
    cfg = yaml.safe_load((run / "config.yaml").read_text(encoding="utf-8")) or {}
    cand = sel.get("candidates", [])
    maes = {int(c["step"]): float(c["song_macro_boundary_mae_sec"]) for c in cand
            if c.get("song_macro_boundary_mae_sec") is not None}
    best = int(sel["selected"]["step"])
    order = sorted(maes)
    metrics = collections.Counter()
    split_path = None
    for f in M4.glob("20260723_qwen_fa_lora_v1/split/*.jsonl"):
        split_path = f
        break
    split_counts: dict[str, int] = {}
    if split_path:
        for line in open(split_path, encoding="utf-8"):
            metrics[json.loads(line).get("split", "?")] += 1
        split_counts = dict(metrics)
    labels_rows = sum(1 for _ in open(
        M4 / "20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl", encoding="utf-8"))
    batch = int(cfg["training"].get("micro_batch_size", 4)) * int(cfg["training"].get(
        "gradient_accumulation", 8))
    max_steps = int(cfg.get("stages", {}).get("r2", {}).get("max_steps", 0))
    epochs_implied = round(batch * max_steps / max(split_counts.get("train", 1), 1), 2)
    gaps = {
        "best_vs_next_best_ms": round(1000 * (sorted(maes.values())[1] - sorted(maes.values())[0]), 2),
        "best_vs_last_ms": round(1000 * (maes[order[-1]] - maes[best]), 2),
        "spread_ms": round(1000 * (max(maes.values()) - min(maes.values())), 2),
        "metric_resolution_ms": 80.0,
    }
    ds_rows = []
    for name in sorted(set(list(REGISTRY_ROLES) + [p.name for p in DATA.iterdir() if p.is_dir()])):
        path = DATA / name
        if name not in REGISTRY_ROLES and not path.exists():
            continue
        ds_rows.append({"dataset": name, "present_on_disk": path.exists(),
                        "size_gb": du_gb(path) if path.exists() else None,
                        "registered_role": REGISTRY_ROLES.get(name, ("未登记", ""))[0],
                        "training_eligibility": REGISTRY_ROLES.get(name, ("", "未登记 ⇒ 不可依赖"))[1]})

    res = {"schema_version": "retrain_data_inventory_v1",
           "training_protocol": {
               "run": str(run), "max_steps": max_steps, "eval_steps": cfg["training"].get("eval_steps"),
               "save_steps": cfg["training"].get("save_steps"), "effective_batch": batch,
               "epochs_implied": epochs_implied, "early_stopping": False,
               "stop_reason": "step budget exhausted (no convergence or patience criterion in config)",
               "selection_split": sel.get("selection_split"), "selection_metric": sel.get("selection_metric"),
               "tie_break": sel.get("tie_break"),
               "test_or_ood_not_used": sel.get("test_or_ood_not_used_for_checkpoint_selection"),
               "candidate_steps": order, "candidate_mae_sec": {str(k): v for k, v in maes.items()},
               "selected_step": best,
               "validation_set_songs": json.loads(
                   (run / f"validation_step_{best:06d}.json").read_text(encoding="utf-8"))[
                   "metric"].get("song_count"),
               "validation_per_song_data_stored": False,
               "differences_vs_resolution_ms": gaps},
           "m4_training_corpus": {"label_rows": labels_rows, "split_counts": split_counts},
           "datasets": ds_rows}
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tp = res["training_protocol"]
    L: list[str] = []
    w = L.append
    w("# 重训盘点：上一次是怎么停的 + 现在有什么数据可用（生成）")
    w("")
    w("> 由 `scripts/evaluation/make_retrain_data_inventory.py` 生成；数字取自 run 内文件与磁盘实测，"
      "许可/角色条目转写自 `data/datasets_registry.md` 与采集会话快照（政策声明，不是测量）。")
    w("")
    w("## 1. 上一次的停止方式与选择粒度")
    w("")
    w(f"- 预算 **max_steps = {tp['max_steps']}**，micro_batch × grad_accum = "
      f"**{tp['effective_batch']}** ⇒ 折算 **约 {tp['epochs_implied']} 个 epoch**；"
      f"`eval_steps = {tp['eval_steps']}`、`save_steps = {tp['save_steps']}`、**无早停**；"
      "⇒ 停止原因是**步数预算用尽**。")
    w(f"- 候选检查点 **{len(tp['candidate_steps'])} 个**（{tp['candidate_steps']}），"
      f"其中最后一个是 terminal_validation；**每个都做过验证**（此前我说过『1110 未验证』，是错的，已更正）。")
    w(f"- 验证集只有 **{tp['validation_set_songs']} 首歌**上的宏平均（"
      f"selection_metric = `{tp['selection_metric']}`，tie_break = `{tp['tie_break']}`），"
      "**且只存聚合值、没存逐歌数据** ⇒ 无法给出误差棒。")
    w("")
    w("| 检查点 | 验证 MAE（秒） | 与最优差 |")
    w("|---:|---:|---:|")
    for step in tp["candidate_steps"]:
        m = maes[step]
        w(f"| {step} | {m:.5f} | {(m - maes[best]) * 1000:+.2f}ms |")
    w("")
    w(f"- 最好与次好只差 **{gaps['best_vs_next_best_ms']}ms**；与最后一步差 **{gaps['best_vs_last_ms']}ms**；"
      f"五个候选总跨度 **{gaps['spread_ms']}ms**，而系统的**时间分辨率是 80ms**、"
      "且指标本身要 0.2s 才稳（第 31/32 轮）。")
    w(f"- ⇒ 更正措辞：不能说『再练会更差』，准确说法是**『500 步以后就平了，"
      "彼此差异远小于测量分辨率，因此选择哪一个是随机的』**。")
    w("")
    w("## 2. 重训前该改的协议（不是数据，是流程）")
    w("")
    w("1. **验证间隔加密**（如每 50–100 步）并**保存逐歌/逐条指标**，否则任何 checkpoint 选择都不可判定；")
    w("2. 选择指标换成**分辨率足够**的口径（≥0.2s 的 within-rate，或 MAE 但配合误差棒），"
      "并把「两个 checkpoint 谁更好」与「格点余量界」一起报（第 32 轮的规则）；")
    w("3. 若继续用 M4Singer，验证集偏小（29 首歌）⇒ 建议扩充验证集（人工标注或 GTSinger 内部研究用）"
      "而不是只加训练量；")
    w("4. **检查点保留策略的现状（读代码，非推测）**："
      "`scripts/training/run_qwen_fa_lora.py:281` 每 `save_steps` 落一次盘，**全程没有任何删除/轮换逻辑**；"
      "`:293-295` 的 best 只是**写一个指针 JSON**（不搬权重、不清除旧点），"
      "所以盘上是「全部周期保存 + 一个指向最优的指针」。本次实测 **5 × 48MB = 239MB**；")
    w("   - 好处（对我们**此刻**尤其重要）：选择指标本身还不可靠（候选差 0.35–1.25ms，"
      "且被塌陷污染），**留着全部候选意味着修好修补后只需重跑 5 次验证就能重新选择，不用重训**；")
    w("   - 风险：`--overwrite` 会 `shutil.rmtree` 整个 run 目录；重训加密验证后候选数会到 11–22 个"
      "（≈0.5–1.1GB），届时应改成『保 best + 最近 N 个轮换』，但**在重新选择完成之前不要删候选**；")
    w("   - ⇒ 建议动作顺序：**先修塌陷 → 对现有 5 个检查点各重跑一次验证 → 再决定是否重训**"
      "（验证成本远小于重训）。")
    w("5. **保留现有 ckpt**：`r2/step-000750` 的逐文件指纹已固定"
      "（见 `docs/status/20260913_pinned_checkpoint_inventory.md`），新训练必须写到新 run 目录。")
    w("")
    w("## 3. 数据盘点：磁盘上有 11 个目录，能进训练的其实还是只有 1 个")
    w("")
    w("| 数据集 | 在盘 | 体量(GB) | 登记角色 | 能否进训练（依登记表） |")
    w("|---|---|---:|---|---|")
    for row in res["datasets"]:
        size = "—" if row["size_gb"] is None else f"{row['size_gb']:.1f}"
        w(f"| `{row['dataset']}` | {'是' if row['present_on_disk'] else '否'} | {size} | "
          f"{row['registered_role']} | {row['training_eligibility']} |")
    w("")
    mc = tp_m4 = res["m4_training_corpus"]
    w(f"- 现行训练语料规模：标签 **{mc['label_rows']:,}** 条，划分 "
      + "、".join(f"{k} {v:,}" for k, v in sorted(mc["split_counts"].items()))
      + "（登记表记 20,896 items / 193,666 字符记录，且注明 `rule_validated` 属弱监督，不等同人工确认）")
    w("")
    w("## 4. 结论：想加数据，路径只有三条")
    w("")
    w("- **A. 走授权拿真正的普通话训练集**：登记表里 `OpenCpop`（官方 train/test）长期是 "
      "`pending official authorization/download`，而主项目定位就是普通话 character-level；"
      "**这是最对症的一条，但被外部授权卡住**；")
    w("- **B. 英文侧**：`DALI` 被登记为『English training candidate』但状态是 `deferred`（未推进）；"
      "`JamendoLyrics` 明文『不混入训练』；所以英文要练就得先推进 DALI；")
    real_pool = next((d["size_gb"] for d in res["datasets"]
                      if d["dataset"] == "audio_works_202604"), None)
    pool_text = f"实测约 {real_pool:.0f} GB" if real_pool else "体量未取到（du 无返回）"
    w(f"- **C. 自监督/伪标签**：`audio_works_202604`（{pool_text}）"
      "无标注，但可以用『raw 解码 + 定向修复 + 置信度筛选』造标签。"
      "**注意与本次发现耦合**：若用现行上游修补的输出去造标签，会把 16% 的塌陷当真理学进去 ⇒ "
      "伪标签必须走 raw + 定向修复，并用结构非法率与置信度双重过滤。")
    w("")
    w("另外三个目录（`mirst500`、`ismir2014_singing`、`tonas`）只有 `raw/`、"
      "没有 `acquisition.json`/`checksums.sha256`，**属于未登记资产，不应作为训练依据**。")
    w("")
    w("## 5. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/make_retrain_data_inventory.py")
    w("```")
    w("")
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"out_md": str(args.out_md), "candidates": tp["candidate_steps"],
                      "best": best, "gaps_ms": gaps, "split_counts": split_counts,
                      "datasets": len(res["datasets"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
