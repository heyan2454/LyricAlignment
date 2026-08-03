# /home/hyan/Data/lyricalign 清理清单（完整审阅版 · 未执行清理）

> 审核时间：2026-08-01 · 总体占用 **104 GB** · 本清单为只读审核，**未删除任何内容**。
> 口径修正：先前版本只量化了"孤立大文件"，低估到 15–20G；本版**按 run root 逐项分解**，
> 真实可清理量级约 **60–75 GB**（占总量一大半，因 demo_diagnostics 大头是"海量 per-item 中间产物 + 历史迭代"）。

---

## 一、全局占用分布
| 目录 | 体积 | 一句话 |
|---|---:|---|
| `demo_diagnostics` | 86G | 各版本实验 run root（中间产物为主，正式结果很小） |
| `runs` | 6.9G | 训练 checkpoint/run 累积 |
| `test` | 6.7G | 语言 demo 分离音轨+渲染（源 mp3 之外可重建） |
| `derived` | 3.7G | 派生缓存/旧版本数据 |
| `models` | **1.8G** | 运行时模型（**保留**） |
| `evidence` | 144M | 证据（已 git 化轻量） |
| 其余顶层 | ~30M | 归档/日志/快照 |

---

## 二、demo_diagnostics（86G）—— 逐 run root 分类

> 原则：每个 run root 的**结果核心**（`complete.json`、`research_summary.json`、`item_summary.json`、`run_status.jsonl`、各 json 清单）保留；**中间产物**（E0–E9 json、experimental/realign/shadow/trials/branches/visuals 渲染/inference_cache）可重建、可删。

### A. 可整体清理的历史迭代 root（已被 v8 正式取代，约 **12G**）
- `alignment_research_v6_formal_20260731_e9_lazy_v1/`（1.8G）
- `alignment_research_v6_formal_20260731_e9_lazy_compact_v2/`（1.8G）
- `..._lazy_compact_v4_metrics_only/`（1.3G）
- `..._lazy_compact_v5_tracefix_recovery/`（0.96G）
- `..._lazy_compact_v6_shortaudiofix/`（1.8G）
- `..._lazy_compact_v7_inputcache_e9scope/`（0.65G）
- `alignment_research_v6_smoke_20260731_e9/`（1.9G，base smoke）
- `alignment_research_v6_smoke_*_e9_v2`~`_v7/`（0.1–1.6G 各版）
- `alignment_research_v6_formal_20260731_e9/`（正式 v8 的 **base 前缀**，若未跑全可归此；当前 11K 基本空）

### B. 可清理的大块中间产物（约 **30–38G**）
- **inline_realign_formal_v4_20260729/items**（**11G**，98 个 demo）
  - 每 item：`branches/`(125M)、`experimental_alignments/`(96M)、`text_dosage_trials.json`(35M)、`visuals/`(16M)、`incomplete_guard/`(6.6M)、`stable_window_assistance_trials.json`(5.5M)、`automatic_incomplete_shadow/`(4.5M)、`inline_realign_shadow.json`(1.4M) —— **全部为中间/影子对齐产物，可重建**
  - 保留：`item_summary.json`(34K) + 必要时 shadow/来源
- **inline_realign_formal_v5_60main_20260729/items**（**9.9G**，同上结构）
- **inline_realign_formal_v3_20260728/**（**5.8G**）：`items/`(4.8G 同上) + `items.zip`(**0.95G** 与 items/ 冗余 → 最安全删)
- **v8 `formal/items/`**（**9.2G**）：其中 **5.77G 来自 20298 个 m4native 的 E0–E9 中间 json 累加**（每 item ~0.3MB，含 E2_corruptions/E1_detector/experimental_alignments/E4_.../E6/E7 等）；`item_summary.json` 合计仅 ~0.3G。→ 保留各 item_summary + 顶层 complete/research_summary/run_status，删中间 json 可省大部分
- **supplemental_20260801/**（**14G**）：`tier1_demo_e489`(13G) 主体为**超大 E8_realign.json**（11 个 >100MB、最大 577MB）；`tier1_mir1k_e489`(1.1G) 等。→ 中间解码可保留 item_summary/最终，删超大 E8 中间（长音频样例建议留）

### C. 保留（正式结果/活跃引用）
- v8：`formal/complete.json`(0.32G)、`research_summary.json`、`run_status.jsonl`、`manifest/`、`frozen_parameters.json`、`baseline_reuse.json`
- v8 `evidence/alignment_research_v6_full.tar.gz`(1.9G)——**归档，确认已另存才删**
- v8 `visuals/`(1.8G)——若需复现可视化可保留，否则属可重建渲染
- 被 active 脚本引用的 `mir1k_subset_v1`、`realign_*` 等（删前核对引用）

### D. demo_diagnostics 其他（可清理或斟酌）
- 日志：v8 `logs/*.log`(formal 161M+collect 126M+visuals 39M+pipeline 328M)、v3/v6 日志 → ~0.7G 可删
- `inference_cache`（120 处）→ **1.1G** 可删
- 顶层旧归档 `*.tar.gz` 手 off 包（~20M）

---

## 三、test（6.7G）
- 每首 `*_qwen_fa/work/audio/*.wav`（vocals/acc/mix，单首 ~150–168M）+ `videos/*.mp4`，以及 `_decoder_realign`/`_raw_guarded` 变体产物 → **可省 ~5–6G**（属可重建；保留源 `mp3/mp4` + `.ass/.srt` 字幕/对齐）

## 四、runs（6.9G）
- **保留**：`seed20260724/checkpoints/step-000750`、`step-001110`；`seed3407/checkpoints/step-001000` 及所在 run 的 `best_checkpoint.json`/`final_checkpoint_selection.json`（formal 引用）
- **可删**：各 run 未被 eval 引用的中间 step（step-000250/0500/0750/1000 非最佳）；纯实验 run 全部 checkpoint（`overfit32`、`overfit_smoke`、`discarded_base_model_adapters`、`r1_*`、`r3_audio_all`、`r0_raw*`、`followup_smoke_*`、`long_test_b*`、`immediate_*`、`120_quick_*`、`r1/r2_pilot` 等）；空目录 `*_empty_launch_attempt`、`*_superseded_preflight_*`、`*.tmp.*`、`*.incomplete.*`
- ⚠️ `seed3407 r1_projector` 保守保留（默认名引用但缺 best_checkpoint，确认无显式指向再删）
- **候选省：数 GB**

## 五、derived（3.7G）
- **保留**（formal 引用）：`20260723_qwen_fa_lora_v1`、`20260722_m4singer_pinyin_validated_v4`、`20260722_mir1k_vocal_channel1_ood`、`20260724_mir1k_qwen_fa_labels_v1`
- **可删**：`20260722_b_tier_visual_review/v{1,2,3}`、`m4singer_character_v1`、`m4singer_vocal_inventory_v1`、`m4singer_split_v1`、`synthetic_v1/v2(+retry*)`、可重建 `m4singer_synthetic_v3/bucket_{20,30}/audio/`、一次性实验目录
- **候选省：数百 M ~ 1G**

## 六、明确保留（不删）
- `models/`（hf_cache Qwen 1.84G 被脚本默认引用、spleeter 被引、torch 部署位）
- `tools/fonts/`（.otf 渲染）、`outputs/`（baseline 审计证据被 reports 引用）
- 各 `formal/`、`complete.json`、`research_summary.json`、`run_status.jsonl`、`manifest/*.jsonl`、`item_summary.json`
- `evidence/`、`evidence_bundle*`（已受控入 git）

---

## 七、汇总（可清理量级）

| 区块 | 可清理量级 |
|---|---:|
| demo_diagnostics·历史迭代 root（A） | ~12G |
| demo_diagnostics·大块中间产物（B：inline v3/v4/v5 + v8 m4native items + supplemental E8） | ~30–38G |
| demo_diagnostics·日志+缓存+归档（D） | ~2G |
| test work/audio + videos | ~5–6G |
| runs 非复用 checkpoint | ~2–4G |
| derived 旧版本 | ~0.5–1G |
| **合计** | **约 50–60G+**（演示式估算，实际以你批量 `du` 为准） |

> 注：若连 v8 的 `visuals` 渲染(1.8G)与 `evidence` 归档(1.9G) 也确认另存/可重建，可再 +3.7G。
> **最保守、零风险起步**：demo 历史迭代(A) + inference_cache + 冗余 items.zip + 日志 + test work/audio ≈ **约 20–25G**。

---

## 建议执行顺序（仅在你审阅批准后）
1. 🟢 零风险：`inference_cache`(1.1G) + `items.zip`(0.95G) + 各 `*.log`(~0.7G) + 顶层残留(~24M)
2. 🟢 test `work/audio` + `videos`(~5-6G，保留源)
3. 🟡 demo 历史迭代 root(A，~12G) —— 先核对 v8 frozen/baseline 一致
4. 🟡 inline v3/v4/v5 items + v8 m4native 中间 json + supplemental E8(建议保留长音频样例)
5. 🟠 runs/derived 旧版本（逐目录确认）
6. `alignment_research_v6_full.tar.gz` 确认另存后再删

> 本清单仅为审阅材料；**未执行任何删除**。
