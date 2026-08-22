# Review 4/4（第二轮 数据一致性/科学诚实 独立复核）

审者：LyricAlignment 数据一致性与科学诚实二次审查员（Review 2/2）
日期：2026-08-14
方法：conda env `lyricalign-qwen` + python json 复算；不轻信文档，所有数字从 JSON 重算。
STEP BUDGET=8。

---

## 项1：乙女解剖 零时长率（FAIR 文档 vocal 口径）

**复算文件**
- Current: `/home/hyan/Data/lyricalign/viz_fullsong_prep/Japanese/乙女解剖_qwen_fa/alignments/r2/vocal/windowed/alignment.json`
- B4: `/home/hyan/Data/lyricalign/runs/20260814_viz_B4/乙女解剖/alignments/r2/vocal/windowed/alignment.json`

**复算结果（`selected_start_sec == selected_end_sec`）**
| 口径 | Current | B4 |
|---|---|---|
| selected 零时长 | **71/341 = 20.82%** | **76/341 = 22.29%** |
| start_sec/end_sec 零时长 | 74/341 = 21.70% | 78/341 = 22.87% |

两个文件 `summary.character_count = 341`、language=Japanese、`japanese_word_nagisa`，B4 与 Current 同 341 字粒度的同源 vocal 对齐。

**判定：修复正确。**
- 文档 `20.8%`（Current）与 `22.3%`（B4）均与 selected 口径复算完全一致（total 341）。
- 任务提示的备查对：`start_sec/end_sec` 口径确为 22.9/21.7（即 22.87/21.70），与提示一致。
- 无 mislabel、无新矛盾。

---

## 项2：月半小夜曲 49 字连续块根因披露（P0 修复）

### 2a. Current 零时长块结构
文件：`/home/hyan/Data/lyricalign/viz_fullsong_prep/Cantonese/月半小夜曲_qwen_fa/alignments/r2/vocal/windowed/alignment.json`
- total chars = 388；selected 零时长 **104** = 26.8%。
- **最长连续零时长 run：gidx160，长 49**；`gidx160–208` 恰为 49 字且**全零**（104 零时长中的 **47.1%**）。
- `gidx217–223` 连续 7 字全零 ✓。

### 2b. B4 同段对比
文件：`/home/hyan/Data/lyricalign/runs/20260814_b4review/月半小夜曲/alignments/r2/vocal/windowed/alignment.json`
- `gidx160–208`（49 字）**39 字非零**（10 字零）。两种口径（selected / start-end）均为 39。
- B4 total selected 零时长 80/388 = 20.62%（与 REVIEW_SLOT_VS_PRESLOT 的 20.6% 一致）。

### 2c. region 覆盖（REQUESTS.jsonl）
文件：`/home/hyan/Data/lyricalign/runs/20260814_explore/yueban_rcf/01_requests/REQUESTS.jsonl`
- 共 **54** 条 region。
- 其 `active_target_unit_ids` 与 `gidx160–208` 相交的仅有 **1 条**：
  `noncore-Cantonese-月半小夜曲-a12` → target [183,184,185]。
- 49 字块内被选为 target 的仅 **3** 字（183/184/185），**46 字未被覆盖**。
- target size 分布：1字×37、2字×10、3字×7（共 54），与文档一致。
- 文档「54 region 中仅 1 个覆盖块内 3 字 / 剩余 46 字未选为 target」**属实**。

### 2d. 文档文本复核（均如实反映）
- `EXPLORE_FULLSLOT_ZERO_DURATION.md`：
  - L12「不是散布单点，近半集中在一个 49 字连续块」✓
  - L14-21「gidx160–208 连续 49 字整块坍缩 … 占全部零时长 47%」「B4 同段 39 字非零」「不是孤立单点」✓ 全部与复算一致。
  - L24-28 region 覆盖、原结论「只对部分散布单点成立，不能对 49 字连续块作结论」✓。
  - 结论（修订）正确区分「整段塌缩」vs「散布单点」，已消除首版误导表述。
- `REVIEW_SLOT_VS_PRESLOT.md`：
  - L23 月半 B4=20.6% / Current=26.8% Δ+6.2 ✓（复算一致）。
  - L28-32 正确描述 49 字块 + region 覆盖 caveat，显式标注「孤立单字→R-CF 救不回」表述不完整 ✓。
- 全 summary 目录 grep「孤立/散布单点/单字」：所有出现均为**加限定/纠偏上下文**，没有残留误导用法；旧结论均被显式修正，无自相矛盾、无 mislabel。

**判定：修复正确。** 49 字连续块、7 字块、B4 39/49 非零、region 仅 1 个覆盖 3 字、47% 占比均与 JSON 复算一致；文档修订如实且未引入新矛盾。

---

## 项3：E4 / E2 summary JSON 扩量为 40-region

### 3a. E4（`E4_GPU_real_coarse_fine.json` vs `runs/20260814_wp6_E4_full/FINAL_COARSE_FINE.json`）
| 主张 | E4 summary | FINAL 复算 | OK |
|---|---|---|---|
| scale/regions | 40 | n_regions=40, aggregates len 40 | ✓ |
| stage_a_constructible | 27 | 27 | ✓ |
| stage_b_constructible | 15 | 15 | ✓ |
| final_stage | B=15, A=12, not_constructible=13 | {B:15, A:12, None:13} | ✓ |
| catastrophic_regression | 8 | 8 | ✓ |
| stage_b_recovered@200/500/1000 | 10/12/13 | 全恢复 target_recovered=1.0 计数: 10/12/13 | ✓ |
| stage_b fixed_context_displacement 0ms | 15/15 | 15 个全为 0.0 | ✓ |

**注意（轻微命名缺陷，非核心数字）**：summary 的 `stage_a_not_constructible_reasons = {invalid_unit_target_span:13, proposal_invalidates_fixed_context:9, SAFE_SLOT:2, non_monotonic:1}` 合计 25，但真正 **stage-A 不可构建的只有 13 个 region**（全部 reason=invalid_unit_target_span）。其余 12 个（9+1+2）实为 **stage-A 可构建但 stage-B 不可构建**（final_stage=A）的 region 的 reason，也摞进了名叫 `stage_a_not_constructible_reasons` 的字段下。该字段名 slight mislabel（实为「两者任一阶段不可构建的 reason」），但 headline 均正确，不影响结论。标为 MINOR 记 backlog。

### 3b. E2（`E2_GPU_real_split.json` vs `runs/20260814_wp4_E2_full_1u_ind/FINAL_SPLIT.json`）
| 主张 | E2 summary | FINAL 复算 | OK |
|---|---|---|---|
| scale | 40 | n_regions=40, ok=40 | ✓ |
| recovered_mean | 0.748 | 0.7477 | ✓ |
| full_recovery_count (>=1.0) | 26/40 | 26/40 | ✓ |
| region_ge75_hit | 28 | 28 | ✓ |
| context_preservation | 0 | 0/40 | ✓ |
| n_context_units_harmed | 80 | 80（40×2） | ✓ |

**判定：修复正确（E2 完全一致；E4 核心数字全对，仅一个原因统计字段名 MINOR 命名偏差）。**

---

## 项4：`09_GPU_REAL_RUN_REVIEW.md` L75
- L75 现文「乙女解剖 20.8% vs 22.3% 等」与项1 复算（20.82% vs 22.29%）完全一致。
- L81-82 E2 数字（rec 0.748, 26/40, ctx_harmed 80/40）与项3b 复算一致。
- L73-74 「mix → Current 零时长被拉高（30%/15%/13%/5%），同源 vocal 后 ≤ B4 → 证伪」的叙事与 VIZ_B4_VS_CURRENT_FAIR_FINDING 一致，无矛盾。

**判定：修复正确。**

---

## 附带发现（不在四复核项内，记录供参考）
- `runs/20260814_runs_summary/VIZ_FULLSONG_4LANG_POST_REVIEW.md` L26「乙女解剖 ja 272字」为**旧 4lang render 的历史遗留**（当时误用 Chinese 分词 272 字）。当前数据文件与更新文档均确认为 Japanese/nagisa **341 字**（VIZ_FINAL_4WAY_RCF_DEMO.md L15-17 已明示修正）。该旧文档未加"已废弃"标注，读者可能误当现行值。属 MINOR 文档遗留，不影响任何零时长率/核心结论。

---

## 结论汇总
- **项1 乙女解剖零时长率：修复正确**（20.8% / 22.3%，total 341，selected 口径；start/end=21.7/22.9 另口径备查正确）。
- **项2 月半小夜曲 49 字块：修复正确**（49 字连续全零、占 47%；7 字块；B4 39/49 非零；region 仅 1 个覆盖 3 字、46 字未覆盖；文档修订如实、无残留误导、无自相矛盾）。
- **项3 E4/E2 扩量 40-region：修复正确**（E2 全对；E4 核心数字全对，唯一 MINOR=reason 字段名 mixture）。
- **项4 09 L75：修复正确**（20.8% vs 22.3% 与数据一致）。

**P0/P1：无。**
（唯一需记 backlog 的 MINOR：E4 summary 的 `stage_a_not_constructible_reasons` 字段名实际混入 stage-B 不可构建 reason；以及 `VIZ_FULLSONG_4LANG_POST_REVIEW.md` L26 的旧 272 字历史残留未加废弃标注。）
