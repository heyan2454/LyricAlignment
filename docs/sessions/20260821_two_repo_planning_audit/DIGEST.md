# DIGEST — 断点档

**状态：全部 5 个交付文件 + DIGEST 已完成。** 本 session 无未完成项。
**scratch 根**：`/home/hyan/waifegameweapon/LAassist/scratch/`

---

## 1. 交付进度（全部完成）

| 阶段 | 文件 | 状态 | 主要内容 |
|---|---|---|---|
| — | `PLAN.md` | ✅ 沿用上一 session 版本（未覆盖，见 §5 裁决 1） | 执行计划 |
| P0 | `P0_inventory.md` | ✅ | 文档统计表 / 分类 / 过期·重复·孤儿候选 / 死链 |
| P1 | `P1_status_and_future.md` | ✅ | **含"已知现状"7 条假设的核对结果（1 条证伪）** |
| P2 | `P2_plan_1w_demo.md` | ✅ | 6 个 demo 候选评估 + 默认选择 + 7 天拆解 + 回退 |
| P3 | `P3_plan_1m_roadmap.md` | ✅ | 10 个主题 + gate/预算/风险 + 4 周日程 + 裁剪方案 |
| P4 | `P4_doc_org_plan.md` | ✅ | 目标树 / 旧→新映射(T0–T3) / dry-run 清单 / 不动清单 |

**执行顺序偏差说明**：实际按 P0 → P1 → P2 → **P4 → P3** 执行（P4 先于 P3）。
依据任务书"时长不足：按 P1→P2→P4→P3 优先级交付"——该规则已明示 P4 优先于 P3，
故在上下文预算有限时先交付 P4 以保护更高优先级产物。两者均已完成，无损失。

## 2. 已读清单（精读，证据已提取）

**LA `/home/hyan/LyricAlignment`**
- ✅ `AGENTS.md`（226 行，亲读全文）
- ✅ `AI_SESSION_ENTRY.md`（468 行：1–60、229–320 亲读；其余按标题索引定位）
- ✅ `docs/sessions/20260814_realign_recovery_visualization_overnight/` 全 12 文件
  （README、00–09、RUN_STATE.md）+ `provenance_notes/` 抽样 —— subagent 44dd9c31
- ✅ `docs/sessions/20260816_lyric_align_dataset_acquisition_evaluation_strategy/` 全 8 文件 —— subagent 7ac52550
- ✅ `reports/progress/20260816_*.md` 6 份 + `20260816_evaluation_outputs_index.json` —— subagent 7ac52550
- ✅ `.dsh/review5–9`（5 份）
- ✅ `docs/sessions/SESSION_INDEX.md`、`docs/sessions/README.md`、`docs/README.md`、`docs/principles.md`(head)
- ✅ `docs/status/` 4 文件（head + mtime）、`docs/manual/` 与 `docs/archive/` 清单
- ✅ 磁盘产物：`/home/hyan/Data/lyricalign/runs/`（172 run、686 mp4、6 个 DELIVER）
  + `ffprobe` 分辨率直方图 + `.identity.json` 内容抽验

**AST `/home/hyan/AST`**
- ✅ `AI_SESSION_ENTRY.md`（53 行，亲读全文）、`docs/README.md`、`docs/hyper/information_architecture.md`（76 行，亲读 60 行）
- ✅ `AGENTS.md`、`docs/status/{project_current,next_execution_plan,important_records}.md`、
  `docs/sessions/SESSION_INDEX.md`、
  `docs/sessions/explore/20260806_pesto_causal_12h_program/{README,RUN1_RESULTS,RUN1_REVIEW,
  HANDOFF_20260814,..._selection_status,..._select_twostage,EXPERIMENT_REPORT}.md`、
  `reports/research/20260806_pesto_causal_12h_experiment_program.md`、
  `reports/research/20260806_external_model_{implementation_compare,reproduction}.md` —— subagent 3c1adbb1
- ✅ `docs/{manual,hyper,runbooks,handoffs,progress,owner}/` 清单、`reports/` 分区清单
- ✅ 磁盘产物：`/home/hyan/Data/ast_runs_formal/pesto_causal_12h_run1_20260806/`
  （selection.json ×5 亲验 mtime + 内容 + `cmp` 对比备份 + 键结构、eventizer/、decoder_cf/、status/）

## 3. 未读清单（明确未覆盖）

| 项 | 原因 | 是否影响已出结论 |
|---|---|---|
| LA `.dsh/review1–4`、`behavior_compare.md`(20KB)、`slot_config_audit.md`(9.7KB) | 属 08-14 批次，结论已由 09/RUN_STATE/00 覆盖 | 否 |
| LA `docs/sessions/20260813_unit_level_realign_overnight/` 全簇 | `AGENTS.md:19-21` 定为"只作追溯" | 否（关键数字已由 `00:1167-1176` 转述） |
| LA `docs/research_*`（68 md）、`AI_SESSION_ENTRY.md:61–228/321–468` | 上游冻结证据 / 历史 override | 否 |
| LA `docs/manual/` 19 件正文（只读了清单） | 未在必读清单 | 轻微影响 P4 T1-4 的归置判断 |
| AST `docs/sessions/{post_rebase(171),rebase(94)}` | 跳过清单 | 否 |
| AST `docs/manual/`(20)、`docs/hyper/` 其余 7 件、`reports/progress/`(82) 正文 | 未在必读清单 | 轻微影响 P4 |
| AST `LATEST_EXPERIMENT_PROGRESS.md`(21KB)、`REASONIX.md`(15KB) | 未在必读清单 | 低 |
| 仓库外绝对路径引用有效性（`/root/autodl-tmp/...`） | P0 §5.3 已声明为盲区 | 否（已声明） |

## 4. 核心结论（10 条，证据见 P0/P1）

1. **[证伪]** AST "select 未跑、`selection.json` 均为 8-06 旧值" **错误**：
   select×5 已于 2026-08-14 13:16→15:47 完成（磁盘 mtime 13:55–15:46、
   新增 `selection_procedure:"two-stage..."` 与 `selected_epoch` 键、
   `cmp` 与 8-06 备份全部 DIFFERENT、`select_twostage.md:56` 自证）。
   误导源：`HANDOFF_20260814_selection_status.md:9-10`（22:34 写入却记录当日凌晨状态，
   且 `:85` 反过来禁止读取真实产物）。
2. **[修正]** LA 主线契约（0814 realign-recovery）与实际重心（0816 evaluation-v1/产品化）**已漂移**；
   `AI_SESSION_ENTRY.md` 无 0816 条目，但 `SESSION_INDEX.md:11` 已标 hot。
3. **[负结果]** LA realign-recovery 在 884 区域 ×3 家族上 **recovered 0%**、collateral 100%；
   0813 有 GT 的 78 区域 catastrophic_harmful **65.4%** → 该路线应降级归档。
4. **[正结果]** LA 唯一真实 GT 产品数字：GTSinger 75 段/1226 字符，
   R2 = **90.1/95.5/98.1%**（both_100/200/500ms）；raw decoder 一致更优（+1.79pp）。
5. **[可交付]** LA 可视化已成熟：磁盘 686 mp4，其中 **314 个 3840×1080** 符合
   `03_VISUALIZATION_DESIGN_AND_ACCEPTANCE.md:142` 规格；每个 mp4 配 `.identity.json`
   （含每轨 `content_sha256`+label、audio sha256、layout/profile/font）→ P2 默认 demo 即基于此。
6. **[P0 风险]** 两仓最新成果均未提交：LA ahead 124 + 93 项未提交；
   AST 相对 `main` ahead 60 + 27 项未提交。且 LA "baseline identity freeze" 记录在 dirty tree
   上（`.dsh/review5:38`）→ 科学上不可复现。
7. **[文档健康]** markdown 死链 0，但反引号路径失效率 LA **11.4%** / AST **13.8%**；
   LA 主因是违反 `AGENTS.md:147` 的 `runs/` 相对路径写法（40/54），
   AST 主因是 `results/by_run/` 空骨架（46/77）+ 两个已裁撤 status 文件被引 45 次。
8. **[AST 就绪度]** 距"可定稿"只差 runtime/RTF/latency 证据 + 新冻结 split，**均不需重训**。
9. **[架构]** 两仓都已有成文的目标文档架构（LA `docs/README.md`、
   AST `docs/README.md` + `docs/hyper/information_architecture.md`）→
   P4 的正确形态是**合规性修复**，不是重设计。
10. **[共性失效]** 两仓同构：契约/状态层滞后于工作树 + 最新成果未提交 + 交接文档互相矛盾
    （且新文件可能记录更旧状态）。两仓 `AGENTS.md` 均于 2026-08-17 02:39–02:42
    被同一次机械 append 迁移（各 +52 行），**都没顺手更新主线指针**。

## 5. 本 session 裁决记录

1. **PLAN.md 不覆盖**：scratch 已存在上一 session 的 `PLAN.md`（49 行，规定"7 文件、两仓合写"），
   与任务书骨架一致 → 沿用，避免制造第二份权威。
2. **文件命名**：`P0_inventory.md` … `P4_doc_org_plan.md`（与既有 PLAN.md 的前缀写法一致）。
3. **两仓合写**：每个交付文件内按 LA / AST 分节，不拆两套目录（依裁决 1）。
4. **demo 默认选择**：依"按候选清单顺序取第一个"→ LA ①Side-by-Side 可视化视频、
   AST ①RUN1 结果解读+汇报报告；理由与可行性见 P2 §0/§1（并非仅因排第一）。
5. **"Side by Side" 命名隔离**：`Side_by_Side.wav` 是**中文歌名**（smoke 媒体，`03:285`），
   非"并排布局"。P2 §1 按"B4-vs-Current 对比视频"读法执行并同时覆盖该曲目。
6. **P4 先于 P3**：见 §1 执行顺序说明。
7. **"3×2 矩阵"的第二轴存疑**：仅见于 `HANDOFF_20260814.md:9,59`，
   在 `20260806_external_model_reproduction.md` 中 NOT FOUND → 按数字反推为
   "两档容差口径"（置信 0.9），P3 主题 I 要求先与 owner 确认。

## 6. 授权边界执行情况

- 对两个目标仓库**只执行只读命令**（read/ls/find/grep/wc/stat/cmp/ffprobe/
  git log·status·rev-list·branch·diff --stat/ps）。
- **未**创建/修改/移动/删除/重命名目标仓库或数据目录内任何文件；**未**执行任何 git 写操作
  （无 commit/push/merge/checkout/stash）。
- 3 个 subagent 均在 prompt 内硬约束为只读，且都在结尾自证未改动任何文件。
- 分析脚本全部以 `python3 - <<'EOF'` 内联 heredoc 执行，**未落盘任何临时脚本**。
- P4 §3 的 `git mv`/`sed`/`mkdir` 全部包裹在 `echo`/heredoc 内作为待审文本，**未运行**。
- 唯一写入位置：`scratch/` 下 6 个文件。

## 7. 下一步 resume 指令（可直接粘贴）

### 若要继续深化规划
```text
读 /home/hyan/waifegameweapon/LAassist/scratch/ 下 DIGEST.md、P0–P4 全部文件。
5 个交付文件已完成，不要重做。你是只读分析 agent：禁止修改
/home/hyan/LyricAlignment 与 /home/hyan/AST 内任何文件，禁止 git 写操作。

可选深化方向（按价值排序）：
1. 补读 LA docs/manual/(19) 与 AST docs/manual/(20)+docs/hyper/(7)，细化 P4 的 T1/T2 归置判断。
2. 核实 P1 §3.2 第 6 项疑点（置信 0.7）：AST eventizer/*/selection.json 是 08-14 新值但
   eventizer_eval/* 仍是 08-06 旧目录，判定 rerun_eventizer_selection.py 的 eval45
   冻结环节是否真的执行过（对照 decoder_cf/eval45_final/final_summary.json）。
3. 对 P2 Day2 的片单做实际选片（需 ffprobe 遍历 6 个 DELIVER 目录）。
```

### 若要开始执行（**需另行授权，本 session 无写权限主张**）
```text
按 P3 §4 的四周日程执行，起点是 P2 Day1（保命日）。
铁律：P4 的 T0（契约修复，只改内容不移文件）必须先于任何文件移动。
最高收益单点动作 = P4 的 T0-5：给 AST HANDOFF_20260814_selection_status.md 加
superseded 头部，可阻止下一轮 agent 白跑 2.5h 的 select。
执行前先做 P4 §3.0 的冷备份（git bundle）与工作树清理（LA 93 项 / AST 27 项）。
```
