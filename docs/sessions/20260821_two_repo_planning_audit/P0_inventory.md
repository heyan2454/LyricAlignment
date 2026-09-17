# P0 — 文档盘点（inventory）

范围：`/home/hyan/LyricAlignment`（下称 **LA**）、`/home/hyan/AST`（下称 **AST**）。
跳过：`.git/`、`legacy/`、`*/archive/*`、`.patch_backups/`、`.repair_backups/`、
`node_modules/`、`__pycache__/`、`.pytest_cache/`、`pretrained_models/`、runs 数据、音频/checkpoint。

**方法论声明**：本文件所有数字都由命令产出，命令原文附在每张表下方，可复算。
未经命令验证的数字一律不写。标签 `[事实]` = 命令输出或文件原文；`[推断]` = 我的判断（附置信度）；
`[建议]` = 行动建议。

---

## 1. 文档总量统计表

### 1.1 LA — 按顶层目录

| 顶层目录 | *.md 数 | 说明 |
|---|---:|---|
| `docs/` | 242 | 主体 |
| `reports/` | 47 | 人类可读报告 |
| `.opencode/` | 31 | 工具链自带（node_modules 内），非项目文档 |
| `.dsh/` | 17 | 本地 review/审计 + skills |
| （仓库根） | 16 | 散落 PATCH_*/CHANGES_* 等 |
| `src/` | 10 | 模块内说明 |
| `configs/` | 9 | 配置说明 |
| `scripts/` | 7 | 入口说明 |
| `.patch_backups/` | 6 | 备份，应跳过 |
| `results/` | 4 | |
| `data/` | 4 | |
| `tests/`,`runs/`,`requirements/`,`models/`,`.readline_stub/`,`.pytest_cache/` | 各 1 | |
| **合计（含 .git 外全部）** | **385** | |
| **合计（应用跳过清单后）** | **352** | 本文件后续分析基数 |

来源命令（在 `/home/hyan/LyricAlignment` 执行）：
```bash
find . -name '*.md' -not -path './.git/*' | wc -l                       # -> 385
find . -name '*.md' -not -path './.git/*' | sed 's|^\./||' \
  | awk -F/ '{if (NF==1) print "(root)"; else print $1}' | sort | uniq -c | sort -rn
# 352 由 P0 分析脚本输出 "MD_TOTAL(after skip): 352"
```

### 1.2 LA — `docs/` 内部分布

| 子目录 | *.md 数 |
|---|---:|
| `docs/sessions/` | 137 |
| `docs/research_v7_align_behavior/` | 26 |
| `docs/manual/` | 19 |
| `docs/research_transition_recovery_detector_20260808_correction/` | 18 |
| `docs/research_v6/` | 11 |
| `docs/research_transition_recovery_detector_20260807/` | 9 |
| `docs/archive/` | 8 |
| `docs/status/` | 4 |
| `docs/research_fullslot_serial_detector/` | 4 |
| 其余（`reports/`,`experiments/`,`principles.md` 等） | 各 1 |

`docs/sessions/` 结构：顶层 55 项 = **7 个 session 目录 + 48 个扁平 .md**（另 `_templates/`）。
[事实] 同一层混放"目录型 session"与"单文件型 session"两种形态。

来源命令：
```bash
find docs -name '*.md' | awk -F/ '{print $1"/"$2}' | sort | uniq -c | sort -rn
ls -1 docs/sessions | wc -l                                   # -> 55
find docs/sessions -maxdepth 1 -type d | wc -l                # -> 8（含自身，即 7 个子目录）
find docs/sessions -maxdepth 1 -name '*.md' | wc -l           # -> 48
```

### 1.3 AST — 按顶层目录

| 顶层目录 | *.md 数 |
|---|---:|
| `docs/` | 464 |
| `reports/` | 123 |
| `src/` | 45 |
| `configs/` | 13 |
| `data/` | 8 |
| （仓库根） | 8 |
| `legacy/` | 4（跳过） |
| `scripts/`,`results/` | 各 2 |
| `tools/`,`runs/`,`context_packs/`,`.pytest_cache/` | 各 1 |
| **合计（.git 外全部）** | **669** |
| **合计（应用跳过清单后）** | **660** |

`docs/` 内部：`sessions/` **417**、`manual/` 20、`status/` 11、`hyper/` 8、`owner/` 4、
`runbooks/`+`progress/`+`handoffs/`+`README.md` 各 1。
`docs/sessions/` 再分：`post_rebase/` **171**、`explore/` **141**、`rebase/` **94**、`_templates/` 8。
`reports/` 内部：`progress/` **82**、`tables/` 12、`research/` 8、`company/` 8、`review/` 4、
`delivery/` 3、`experiments/` 2、`metrics/`+`legacy/`+`audits/`+`README.md` 各 1。

来源命令（在 `/home/hyan/AST` 执行）：
```bash
find . -name '*.md' -not -path './.git/*' | wc -l              # -> 669
find docs -name '*.md' | awk -F/ '{print $1"/"$2}' | sort | uniq -c | sort -rn
find reports -name '*.md' | awk -F/ '{print $1"/"$2}' | sort | uniq -c | sort -rn
# 660 / sessions 三分 由 P0 分析脚本输出
```

### 1.4 两仓对比 [推断 0.9]

AST 文档量约为 LA 的 **1.7 倍**（660 vs 352），且 **63%** 的 AST 文档集中在
`docs/sessions/{post_rebase,rebase,explore}`（406/660）。
[推断 0.9] AST 采用"每 session 一目录 + 固定 6 件套模板"的归档制度，文档量随 session 数线性膨胀；
LA 尚未完全模板化（48 个扁平 md 与 7 个目录型 session 混存）。
证据：AST 同名文件统计中 `SESSION_SUMMARY.md` 56 份、`PATCH_REVIEW.md` 55 份、
`FILES_MANIFEST.md` 54 份、`NEXT_PROMPT.md` 54 份、`SESSION_FULL_RECORD.md` 51 份
（见 §3.2），且模板本体位于 `docs/sessions/_templates/*_TEMPLATE.md`（8 个）。

---

## 2. 分类

### 2.1 LA 文档分类（按功能，非目录）

| 类别 | 代表位置 | 数量/证据 | 时效性 |
|---|---|---|---|
| **契约/入口层** | `AGENTS.md`(226 行)、`AI_SESSION_ENTRY.md`(468 行) | 2 | **活跃**，`AGENTS.md` 2026-08-17 02:42 改（追加全局纪律，见 `AGENTS.md:178`） |
| **状态层** | `docs/status/`（4 件） | 4 | **过期**，见 §4.1 |
| **session 记录** | `docs/sessions/` | 137 | 混合：2 个 hot（0814/0816），其余 warm/cold |
| **研究专题** | `docs/research_v7_align_behavior/` 26、`research_transition_recovery_detector_*` 27、`research_v6` 11、`research_fullslot_serial_detector` 4 | 68 | 上游证据，`AGENTS.md:19-21` 明确"只作实现和证据追溯" |
| **手册/规程** | `docs/manual/` | 19 | 稳定 |
| **进度报告** | `reports/progress/` | 47（含 7 个未提交） | **活跃**（0816 批次） |
| **本地 review** | `.dsh/review1–9`、`behavior_compare.md`、`slot_config_audit.md` | 12 | **活跃但游离**，见 §4.3 |
| **补丁说明（根目录）** | `PATCH_README_*`、`PATCH_NOTES_*`、`CHANGES_*`、`IMPLEMENTATION_VALIDATION_*` | 13 个 `PATCH*` + 3 | **历史**，见 §4.2 |
| **归档** | `docs/archive/` | 8 | 已归档 |

来源命令：
```bash
wc -l AGENTS.md AI_SESSION_ENTRY.md                  # 226 / 468
find . -maxdepth 1 -name 'PATCH*' | wc -l            # -> 13
find . -maxdepth 1 -name '*.md' | wc -l              # -> 16
ls .dsh/                                             # review1..9 + behavior_compare + slot_config_audit + skills/
```

### 2.2 AST 文档分类

| 类别 | 代表位置 | 数量/证据 | 时效性 |
|---|---|---|---|
| **契约/入口层** | `AGENTS.md`(2026-08-17 改)、`AI_SESSION_ENTRY.md`(53 行) | 2 | **活跃** |
| **状态层** | `docs/status/`：`project_current.md`(as_of 2026-08-06)、`next_execution_plan.md`(as_of 2026-08-06)、`important_records.md`(as_of 2026-07-31)、`README.md` | 4 顶层 + 7 在 `docs/status/legacy/` | 部分过期，见 §4.1 |
| **owner 层** | `docs/owner/`：`owner_current.md`、`research_roadmap.md`、`demo_future_roadmap.md` | 4 | **过期**（2026-07-15～07-22） |
| **session 三分区** | `post_rebase/`171、`explore/`141、`rebase/`94 | 406 | `explore/` 内 24 个目录，仅 1 个 hot |
| **session 模板** | `docs/sessions/_templates/` | 8 | 制度性 |
| **进度报告** | `reports/progress/` | 82 | 历史居多 |
| **对外/企业报告** | `reports/company/` 8、`reports/tables/` 12、`reports/delivery/` 3 | 23 | 汇报路线（`AI_SESSION_ENTRY.md:24` 声明"汇报路线与研究路线分开"） |
| **研究设计** | `reports/research/` | 8 | 含当前主线设计 `20260806_pesto_causal_12h_experiment_program.md` |
| **模型/指标专题** | `src/models/{pesto,basicpitch,rosvot,vocano,fcpe}` 45、`configs/metrics/` | 58 | 与代码同目录 |
| **无关工具** | `tools/baidu_netdisk_aggregate/README.md` | 1 | **范围外**，见 §4.4 |

`docs/status/README.md:3` [事实]："本目录只允许四个文件" —— 顶层实际正好 4 个 md，**合规**；
额外 7 个在 `docs/status/legacy/`。

---

## 3. 重复候选

### 3.1 内容完全相同（sha256 一致）

**LA：0 组**。[事实] 无字节级重复文档。

**AST：5 组**，均为 2 份：

| # | 文件对 | 判定 |
|---|---|---|
| 1 | `docs/sessions/explore/20260731_pesto_frame2note_review_repair_codex_handoff/NEXT_PROMPT.md` ＝ 同目录 `NEXT_PROMPT_FOR_CODEX.md` | [推断 0.9] 同一交接 prompt 的两个命名，**可合一** |
| 2 | `docs/sessions/post_rebase/20260630_streaming_alignment_latency_gui_archive/OUTPUTS/PESTO_OFFLINE_VS_STREAMING_DIRECT_COMPARE.md` ＝ `reports/progress/20260630_pesto_offline_vs_streaming_direct_compare.md` | [推断 0.85] session OUTPUTS 与 reports 双写，属**制度性双份**（归档+可读），建议保留一份+软链接式引用 |
| 3 | `docs/sessions/post_rebase/20260701_gui_cli_manual_test_overnight_archive/OUTPUTS/GUI_CLI_MANUAL_TEST_ANALYSIS.md` ＝ `reports/progress/20260701_gui_cli_manual_latency_coverage_audit.md` | 同上 |
| 4 | `src/models/basicpitch/diagnostics/run_eval/v2.1/README.md` ＝ `v2/README.md` | [推断 0.8] 版本目录复制未改 README，**内容已失真风险** |
| 5 | `src/models/pesto/eventizer/pesto_boundary_eventizer_v2/README_RUN.md` ＝ `..._v2_1/README_RUN.md` | 同上 |

来源命令：P0 分析脚本（sha256 分组）：
```python
h[hashlib.sha256(open(m,'rb').read()).hexdigest()].append(m)   # 取 len>1 的组
```

[建议] 第 4、5 组风险最高：`v2` 与 `v2.1`/`v2_1` 两个版本目录共用同一份 README，
读者无法区分版本差异。属 P4 待处理项（**只登记，不在本任务执行**）。

### 3.2 同名文件（不同目录）

**LA：6 组** —— `README.md` ×63、`00_SESSION_DISCUSSION_RECORD.md` ×6、`SKILL.md` ×4、
`03_CODEX_HANDOFF.md` ×3、`02_NEXT_ROUND_EXPERIMENT_DESIGN.md` ×3、`04_CODEX_IMPLEMENTATION_PLAN.md` ×2。

**AST：14 组**，前 6 名：`README.md` ×90、`SESSION_SUMMARY.md` ×56、`PATCH_REVIEW.md` ×55、
`FILES_MANIFEST.md` ×54、`NEXT_PROMPT.md` ×54、`SESSION_FULL_RECORD.md` ×51；
另 `TEST_REPORT.md` ×7、`ARCHIVE_VALIDATION.md` ×5、`ARCHIVE_CHECKLIST.md` ×5、
`PROVENANCE.md` ×5、`NEXT_PROMPT_FOR_CODEX.md` ×4、`EXPERIMENT_REPORT.md` ×2。

[事实] 这些同名不是重复内容（§3.1 显示仅 5 组字节相同），而是**模板实例化**。
[推断 0.95] 该命名法使"按文件名检索"完全失效（搜 `NEXT_PROMPT.md` 命中 54 份），
必须靠目录名定位——这是 §5 目录树设计的关键约束。

---

## 4. 过期 / 孤儿候选（带证据）

### 4.1 过期候选：状态层落后于主线（两仓皆有，LA 更严重）

**LA [事实]**：`docs/status/` 四个文件 mtime 全为 `2026-07-31`，而
`docs/status/project_current.md:3` 自述 `**Snapshot date:** 2026-07-28`，
`:4` 描述阶段为 "multilingual Test Demo and complete inline-realign shadow suite implemented;
server GPU smoke/formal evidence is next"。
但 `AGENTS.md:82` 声明当前主线是 `Unit Realign Recovery + Visualization`，
最新 session 为 `docs/sessions/20260816_*`（mtime 2026-08-17 02:20），
最新 commit `0356d3f` 日期 `2026-08-15`。
→ **状态层落后主线 ≥18 天，跨越了 0812/0813/0814/0816 四个 session**。

同时 `AI_SESSION_ENTRY.md:232-233` 仍把 `docs/status/project_current.md`、
`next_execution_plan.md` 列为 "Read in this order" 第 2、3 项 —— 新 agent 按此顺序读会
**先读到 7-28 的过期快照**。[推断 0.9] 这是当前文档体系最高优先级的缺陷。

**AST [事实]**：`docs/status/project_current.md:4` `as_of: 2026-08-06`、
`:5` `current_focus: pesto_causal_12h_run1_completed_results_pending_review`；
`next_execution_plan.md:4` `as_of: 2026-08-06`；`important_records.md:5` `as_of: 2026-07-31`。
而 select 相关产物实际更新到 `2026-08-14`（见 P1），仓库最新改动 `tools/` 为 `2026-08-19`。
→ 落后 8～13 天，但**方向未变**（仍是 run1 结果解读），严重度低于 LA。

`docs/owner/owner_current.md` mtime `2026-07-22`、`research_roadmap.md` `2026-07-17`、
`demo_future_roadmap.md` `2026-07-15`，而 `AI_SESSION_ENTRY.md:6` 把
`docs/owner/owner_current.md` 列为"默认读取"第一项 → 同类缺陷。

来源命令：
```bash
for f in docs/status/*.md; do echo "$(stat -c '%y' "$f" | cut -c1-10)  $f"; done
head -12 docs/status/project_current.md ; ls -la docs/owner/
git log -5 --format='%h %ad %s' --date=short
```

### 4.2 过期候选：LA 仓库根散落的补丁说明（13 个 `PATCH*` + 3）

[事实] 根目录 16 个 md，其中 13 个匹配 `PATCH*`，日期跨 `20260728`–`20260814`：
`PATCH_README_20260803_RESEARCH_V7_ALIGN_BEHAVIOR.md`、
`PATCH_README_20260804_LONG_SLOT_REGION_ASSESSOR_ARCHIVE.md`、
`PATCH_README_20260805_DETECTOR_V2.md`、
`PATCH_README_20260807_TRANSITION_RECOVERY_DETECTOR.md`、
`PATCH_README_20260813_realign_request_gate_testdemo.md`、
`PATCH_README_20260814_REALIGN_RECOVERY_VISUALIZATION.md`、
`PATCH_NOTES_20260810_REALGT_NEXT_ROUND_HANDOFF.md`、
`PATCH_NOTES_20260812_DETECTOR_PRODUCTION_REALIGN_GATE.md`、
`PATCH_NOTES_20260728_CONTROL_VISUAL_COLLECTION_FIX.md`、`PATCH_README_mir1k_import_fix.md`、
`PATCH_MANIFEST.{txt,sha256}`、`PATCH_DIFF_EXISTING_FILES.diff` 等；
另有 `CHANGES_20260728_INLINE_REALIGN_V4.md`、`IMPLEMENTATION_VALIDATION_20260728.md`、
`APPLY_*.sh` 3 个可执行补丁脚本。
[事实] 全部 13 个 `PATCH*` md 命中 §4.3 的孤儿判定（无任何 md 链接、文件名未被任何 md 提及）。
[推断 0.85] 这些是历次补丁投递的一次性说明，补丁已合入（对应 session 目录都存在），
说明文件本身已无导航价值，属可归档候选。**不在本任务执行任何移动。**

### 4.3 孤儿候选（无入链且文件名未被任何 md 提及）

| 仓库 | 孤儿候选数 | 占比（基数） | 判定方法 |
|---|---:|---:|---|
| LA | **96** | 96/352 = 27.3% | 无 md 链接指向 + basename 未出现在任何 md 全文 |
| AST | **61** | 61/660 = 9.2% | 同上 |

LA 前列（部分）：`.dsh/review1..9_*.md`（9 个）、`.dsh/behavior_compare.md`、
`.dsh/slot_config_audit.md`、根目录 13 个 `PATCH*`、`docs/cleanup_execution_record_lyricalign.md`。
AST 前列（部分）：`docs/sessions/_templates/*_TEMPLATE.md`（7 个，**模板属正常孤儿**）、
`docs/progress/20260814_progress_report_draft.md`、
`docs/sessions/explore/20260806_pesto_causal_12h_program/EXPERIMENT_REPORT.md`、
`…/HANDOFF_20260814_select_twostage.md`、`…/HANDOFF_20260814_selection_status.md`、
`reports/company/#U4f01#U4e1a…md`。

**方法学警告 [事实]**：该判定会把"制度性无入链文件"误判为孤儿。已识别的**假阳性**类别：
① AST `_templates/*_TEMPLATE.md`（模板本就不被引用）；
② LA `.dsh/skills/*/SKILL.md`（由 `skill` 工具按名加载，非文档链接）；
③ **AST 当前主线最新的 3 个交接文档**（`EXPERIMENT_REPORT.md`、`HANDOFF_20260814_select_twostage.md`、
`HANDOFF_20260814_selection_status.md`）—— 这三个是 hot 文档却无人引用，
属**真正的问题**：`docs/sessions/SESSION_INDEX.md` 末尾只提到 `RUN1_REVIEW.md`
（`docs/sessions/SESSION_INDEX.md:97`），未登记 8-14 的三个交接文档。
[推断 0.9] 8-14 那轮工作**未回写任何索引**，只能靠目录列表发现 → P1/P4 必须处理。

因此"孤儿候选"只作**排查线索**，不等于"可删除"。

### 4.4 范围外/异质内容候选

[事实] AST `tools/baidu_netdisk_aggregate/`（`aggregate.py` 12949 B、`README.md` 6344 B、
`rules.example.json`，mtime `2026-08-19 15:35`）是**整个仓库最新的改动**，且为 git 未跟踪（`?? tools`）。
其内容（百度网盘聚合）与 AST 的音频转写研究主线无关。
[推断 0.75] 属临时工具误置入研究仓库，或是刻意放置的运维脚本；**证据不足**判断意图
（读过 `git log`、`AI_SESSION_ENTRY.md`、`docs/status/*` 未找到任何关于 baidu_netdisk 的说明）。
[建议] P4 中列为"需 owner 裁决"项，不自行处置。

### 4.5 LA 契约文档自身的时间悖论

[事实] `AGENTS.md` mtime `2026-08-17 02:42`，`AGENTS.md.bak.1786905548` mtime `2026-08-17 02:39`，
行数 226 vs 174（+52 行）。新增部分即 `AGENTS.md:178-226`「迁移的全局纪律（原 `~/.dsh/AGENTS.md`，
2026-08-17 迁入）」。AST 侧存在同名 `.bak.1786905548`（同一 epoch 后缀 1786905548），
`AGENTS.md` 16287 B / `.bak` 11136 B。
[推断 0.95] 两仓在 2026-08-17 02:39–02:42 被**同一次批量操作**改写，
目的是把用户级全局纪律下沉到项目级（`AGENTS.md:224` 自述 `~/.dsh/AGENTS.md` 已删除）。
[事实] 该次改写**只追加了全局纪律，未同步更新 LA 的主线指针**：
`AGENTS.md:15-16` 与 `:82-84` 仍指向 `20260814` session，而 `docs/sessions/20260816_*`
已存在且 `docs/sessions/SESSION_INDEX.md:11` 已把 0816 标为 `hot`。
→ 契约层内部不一致，详见 P1 §主线仲裁。

---

## 5. 死链

### 5.1 Markdown 语法链接 `[text](target)`

| 仓库 | 死链数 |
|---|---:|
| LA | **0** |
| AST | **0** |

[事实] 两仓的 markdown 语法链接全部可解析。
[推断 0.9] 原因是两仓几乎不用 `[]()` 语法写内部引用，而用**反引号裸路径**（见 §5.2），
所以"0 死链"不代表引用健康。

### 5.2 反引号路径引用（真实引用面）

| 仓库 | 受检引用 | 不存在的路径（去重） | 出现次数 | 失效率 |
|---|---:|---:|---:|---:|
| LA | 568 | **54** | 65 | **11.4%** |
| AST | 1175 | **77** | 162 | **13.8%** |

按顶层目录分布（去重计）：
- **LA**：`runs/` **40**、`scripts/` 6、`src/` 3、`reports/` 2、`results/`/`tests/`/`tools/` 各 1。
- **AST**：`results/` **46**、`docs/` 11、`runs/` 8、`src/` 8、`data/` 2、`configs/`/`scripts/` 各 1。

判定口径：反引号内 token 形如 `^(docs|src|scripts|configs|tests|reports|results|data|runs|packaging|tools)/…$`，
排除含 `<`/`>`/`*`/`...` 的占位符，再对仓库根做 `os.path.exists`。

**LA 的 `runs/` 死链（40/54 = 74%）有系统性原因 [事实]**：
`AGENTS.md:145-148` 规定 run 数据严禁放工作目录，统一在
`/home/hyan/Data/lyricalign/runs/`，且"代码/脚本/文档中的 run 路径一律用该数据目录绝对路径"。
但文档实际写成仓库相对的 `runs/...`。典型：
- `.dsh/review2_data_result.md:30` → `runs/20260814_wp6_E4_full/FINAL_COARSE_FINE.json`（×3 处）
- `docs/sessions/20260814_realign_recovery_visualization_overnight/RUN_STATE.md:46` →
  `runs/20260814_runs_summary/VIZ_FULLSONG_4LANG_POST_REVIEW.md`
- `RUN_STATE.md:69` → `runs/20260814_viz_B4_vs_cur_Fair_vocal/`
→ [推断 0.9] 这 40 条**多数不是"产物丢失"，而是违反 `AGENTS.md:147` 的写法**，
真实产物在数据目录（已验证：`/home/hyan/Data/lyricalign/runs/` 下存在 172 个 run 目录、686 个 mp4）。
**修复动作是改写引用前缀，不是找回文件**——这个区分对 P4 很重要。

**AST 的 `results/` 死链（46/77 = 60%）**：如
`configs/metrics/diagnostic_metric_completion_plan.md:12` → `results/by_run/mirst500_eval45_conp_tolerance_collab_20260622/`；
`docs/sessions/explore/20260716_four_config_corrected_deep_audit_archive/SESSION_FULL_RECORD.md:55` →
`results/by_run/four_config_ab_selection_repair_20260716/`（×6）。
[事实] `results/by_run/` 实际为空骨架（`find results -maxdepth 2` 仅见 `.gitkeep` 与 registries，
最新 mtime 2026-07-20）。[推断 0.8] 与 LA 同类问题：轻量指标本应进 git 但实际未落盘，或已外置到
`/home/hyan/Data/`。

**AST 最高频死链是文档而非产物 [事实]**：
- `docs/status/metric_management_current.md` 被引 **23** 次（首见
  `docs/sessions/rebase/20260615_metrics_runs_completion_diagnostic_registry_v3/FILES_MANIFEST.md:9`）
- `docs/status/rebase_current.md` 被引 **22** 次（首见 `docs/sessions/rebase/20260612_policy_v4/FILES_MANIFEST.md:9`）

两者均不存在。而 `docs/status/README.md:3` 规定该目录"只允许四个文件"。
[推断 0.95] 这两个文件曾存在于 `docs/status/`，后因"四文件制"被裁撤/合并，
但 45 处历史 `FILES_MANIFEST.md` 引用未随之更新。属**历史归档的既成事实**，
[建议] 不逐个改写 45 份归档，而在 `docs/status/README.md` 加一条"已裁撤文件映射"说明即可（P4）。

### 5.3 死链检查的已知盲区（诚实声明）

本次**未**检查：① 指向仓库外绝对路径（如 `/home/hyan/Data/...`、`/root/autodl-tmp/...`）的引用；
② 非反引号、非 md 语法的裸路径；③ http(s) 外链可达性；④ 锚点（`#section`）有效性；
⑤ 代码/YAML/JSON 内的路径引用（只扫了 `*.md`）。
其中 ① 数量可观且对可复现性影响大，[建议] 列入 P4 的后续核查项。

---

## 6. P0 结论摘要

1. [事实] LA 352 / AST 660 份有效文档；AST 63% 集中在三个 session 分区，靠 6 件套模板驱动。
2. [事实] **两仓状态层都过期**，LA 严重（落后 ≥18 天且被列为必读第 2 项）、AST 轻微（8–13 天，方向未变）。
3. [事实] 字节级重复极少（LA 0 / AST 5 组），真正的问题是**同名模板实例**（AST `README.md` ×90）
   使文件名检索失效。
4. [事实] Markdown 死链 0，但反引号路径失效率 **LA 11.4% / AST 13.8%**；
   LA 主因是违反 `AGENTS.md:147` 的 `runs/` 相对路径写法（40/54），
   AST 主因是 `results/by_run/` 空骨架（46/77）与两个已裁撤 status 文件被引 45 次。
5. [事实] AST 当前主线 8-14 的三份交接文档（`HANDOFF_20260814*.md`、`EXPERIMENT_REPORT.md`）
   **无任何索引入链**，`SESSION_INDEX.md` 只登记到 `RUN1_REVIEW.md`。
6. [事实] LA 契约层自我矛盾：`AGENTS.md:15/82` 指向 0814，`SESSION_INDEX.md:11` 已把 0816 标 hot，
   而 `AI_SESSION_ENTRY.md` 无 0816 条目。仲裁见 P1。
7. [推断 0.75] AST `tools/baidu_netdisk_aggregate/` 与主线无关且为仓库最新改动，需 owner 裁决。
