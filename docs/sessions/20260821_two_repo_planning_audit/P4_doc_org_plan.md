# P4 — 文档组织方案（doc_org_plan）

> ⚠️ **本文件是计划，不是执行记录。本 session 未移动/删除/重命名任何文件，未执行任何 git 写操作。**
> 所有操作清单均为 **DRY-RUN**，需人工确认后另行执行。

---

## 0. 核心论点（先说结论）

**[事实] 两个仓库都已经有成文的目标文档架构，而且写得很好。问题不是"缺设计"，而是"现实偏离了自己的设计"。**

证据：
- LA `docs/README.md:3-9` 已定义四层职责（`principles.md` / `status/` / `manual/` / `sessions/`），
  并明写 **"报告类内容位于顶层 `reports/`，不要把阶段报告混入这里"**（`docs/README.md:11`）。
- LA `docs/sessions/README.md` 已定义温度制（hot/warm/cold）与**升格规则**：
  "当内容已经稳定为长期约束时，迁移到 `docs/principles.md` 或 `docs/manual/`；
  状态事实迁移到 `docs/status/project_current.md`"。
- AST `docs/README.md:3-12` 定义六层（`status/ owner/ manual/ hyper/ sessions/ handoffs/`），
  并明写 **"一个文档应只有一个主要职责；动态事实不得长期滞留在 manual/hyper，
  完整执行过程不得堆入 status"**。
- AST 更进一步有专门的架构法典 `docs/hyper/information_architecture.md`（76 行），
  定义四个信息平面（控制/项目知识/执行证据/物理资产，`:11-17`）、
  单一主要职责清单（`:35-46`）、权威与新鲜度规则（`:49-53`）、
  上下文分层 L0–L3（`:57-62`）。其 `:51` 明确要求
  **"动态文档应写明 `as_of` 和来源。中间状态保留在 Full Record，并标记 `superseded`；
  live current 只保存最终整合状态"**。

**[推断 0.95] 因此本方案的正确形态是"合规性修复（conformance）"，而不是"架构重设计"。**
任何新目录树的提案都会与两份已有 README 竞争权威，反而制造第三套标准。
→ **本方案的目标结构树 = 各仓自己 README 已定义的树**，我只标注偏差与回归路径。

**[建议] 优先级铁律：契约层修复（T0）必须先于任何文件移动（T1/T2）。**
理由：过期的 override 与自相矛盾的 handoff 正在**主动误导**下一个 agent
（P1 §1.1、§1.6），而文件位置不合规只是**降低效率**。先治误导，再治整洁。

---

## 1. 目标文档结构树

### 1.1 LA 目标树（依 `docs/README.md` + `docs/sessions/README.md`，标注现状偏差）

```text
/home/hyan/LyricAlignment
├── AGENTS.md                    # 项目契约（226 行）        ✅ 合规
├── AI_SESSION_ENTRY.md          # AI 入口 / active override  ⚠️ T0-1：缺 0816 条目
├── README.md                    # 项目是什么                 ⚠️ 7-31 未更新（低优先）
├── docs/
│   ├── README.md                # 目录职责说明               ✅ 合规（是本树的权威）
│   ├── principles.md            # 长期稳定原则               ✅ 合规
│   ├── status/                  # 当前快照 + 下一步（4 件）   ⚠️ T0-2：快照日期 7-28，落后 ≥18 天
│   ├── manual/                  # 稳定协议（19 件）           ✅ 合规
│   ├── sessions/                # 讨论/决策/负结果/交接       ⚠️ T2-1：48 扁平 md 与 7 目录混存
│   │   ├── SESSION_INDEX.md     #   索引 + 温度              ✅ 合规（已含 0816，:11）
│   │   ├── _templates/
│   │   └── YYYYMMDD_<topic>/    #   目录型 session（新形态）
│   └── archive/                 # 归档（11 件）              ✅ 合规
├── reports/                     # 人类可读报告（唯一报告根）  ✅ 合规
├── results/                     # 轻量结构化指标（canonical） ✅ 合规
├── configs/ scripts/ src/ tests/                              ✅ 合规
└── runs/                        # 只登记 README + .gitkeep    ✅ 合规（数据在 /home/hyan/Data/lyricalign/runs/）
```

**现状对该树的 5 处偏差 [事实]**：

| # | 偏差 | 证据 | 与哪条规则冲突 |
|---|---|---|---|
| D1 | 仓库根散落 13 个 `PATCH*` md + `CHANGES_*` + `IMPLEMENTATION_VALIDATION_*` | `find . -maxdepth 1 -name 'PATCH*' \| wc -l` = 13；根 md 共 16 | 该树无"仓库根放补丁说明"这一层；且 13 个全是孤儿（P0 §4.3） |
| D2 | `docs/reports/` 存在（1 件：`20260728_inline_realign_formal_v3_data_discussion.md`） | `ls -la docs/reports/` | 直接违反 `docs/README.md:11`"报告类内容位于顶层 `reports/`" |
| D3 | `docs/experiments/` 存在（1 件：`20260728_inline_realign_full_mechanism_design.md`） | `ls -la docs/experiments/` | 不在 `docs/README.md` 的四层职责中 |
| D4 | `docs/` 顶层散落 2 个清理文档（`cleanup_execution_record_lyricalign.md`、`data_cleanup_checklist_lyricalign.md`） | `ls -1 docs/` | 不在四层中；按性质应入 `manual/` 或 `archive/` |
| D5 | `docs/` 顶层 4 个 research 专题目录（68 md）：`research_v7_align_behavior/`(26)、`research_transition_recovery_detector_20260807/`(9)、`..._20260808_correction/`(18)、`research_v6/`(11)、`research_fullslot_serial_detector/`(4) | P0 §1.2 | 不在四层中。**但见 §4 T3-2：建议不动** |

### 1.2 AST 目标树（依 `docs/README.md` + `docs/hyper/information_architecture.md`）

```text
/home/hyan/AST
├── AGENTS.md / AI_SESSION_ENTRY.md / README.md                 ✅ 合规
├── docs/
│   ├── README.md                # 六层职责定义                ✅ 权威
│   ├── status/                  # 当前快照（限 4 件，README:3）  ⚠️ T0-4：as_of 8-06，落后 8–13 天
│   │   └── legacy/              #   7 件历史                   ✅ 容器合规
│   ├── owner/                   # Owner 决策与 roadmap（4 件）  ⚠️ 7-15～7-22，6 周未更新
│   ├── manual/                  # 长期方法与操作（20 件）       ✅ 合规
│   ├── hyper/                   # AI 协作/IA/session 规则（8 件）✅ 合规（含架构法典）
│   ├── sessions/                # 执行证据平面                 ✅ 合规
│   │   ├── SESSION_INDEX.md     #                              ⚠️ T0-3：未登记 8-14 三份交接文档
│   │   ├── _templates/(8)  explore/(24 目录,141 md)
│   │   ├── post_rebase/(171)  rebase/(94)                      ✅ 归档，跳过
│   ├── handoffs/                # 跨机器专项交接（1 件）        ✅ 合规
│   └── progress/                # ❌ **不在六层定义中**（1 件）  ⚠️ T1-4
├── reports/                     # progress/tables/research/company/delivery/review/...  ⚠️ T1-3：19 个乱码文件名
├── runs/ results/               # 骨架 + registries            ⚠️ T2-3：46 处 results/ 死引用
├── src/ scripts/ configs/ tests/ packaging/                    ✅ 合规
└── tools/                       # ❌ baidu_netdisk_aggregate    ⚠️ T2-4：与主线无关且未跟踪
```

**现状对该树的 4 处偏差 [事实]**：D6 `docs/progress/` 不在六层职责中（`docs/README.md:5-11` 未列）；
D7 `reports/` 内 19 个转义 unicode 乱码文件名；D8 `tools/` 异质内容；
D9 两个已裁撤的 status 文件仍被 45 处引用（`docs/status/metric_management_current.md` ×23、
`docs/status/rebase_current.md` ×22，P0 §5.2）。

---

## 2. 旧 → 新映射表

**分级说明**：T0 = 契约修复（**改内容不改位置**，最高优先）；T1 = 低风险移动；
T2 = 需 owner 确认；T3 = 建议不动（见 §4）。

### 2.1 T0｜契约层修复（不移动文件，只补内容）

| # | 目标文件 | 动作 | 依据 | 收益 |
|---|---|---|---|---|
| **T0-1** | LA `AI_SESSION_ENTRY.md` | 在 `:1` 之后插入 `## 2026-08-16 ... — Active Override` 段，列 0816 的 8 个必读文件，并声明"与 0814 冲突时本段优先" | P1 §1.1：`SESSION_INDEX.md:11` 已标 0816 为 hot，但 entry 无此条目；`AGENTS.md:15` 指定 entry 为深度上下文入口 | 消除新 agent 走错主线 |
| **T0-2** | LA `AI_SESSION_ENTRY.md:229-243` 的 "Read in this order" | 重排：把 `docs/status/project_current.md`（快照 7-28）从第 2 位移出或加 **`[STALE as of 2026-07-28]`** 标注 | P0 §4.1：新 agent 按现顺序会**先读到过期快照** | 消除最高频误导路径 |
| **T0-3** | LA `AGENTS.md:15-16` 与 `:82-89` | 主线指针同步到 0816；保留 0814 为"上游已完成轮次" | P1 §1.1 | 契约层内部自洽 |
| **T0-4** | LA `docs/status/project_current.md` + `next_execution_plan.md` | 重写快照到 2026-08-16 状态（含 R2 90.1/95.5/98.1% 与 realign 负结果） | `docs/sessions/README.md` 的升格规则："状态事实迁移到 `docs/status/project_current.md`" | 让状态层重新可信 |
| **T0-5** | AST `docs/sessions/explore/20260806_pesto_causal_12h_program/HANDOFF_20260814_selection_status.md` | 文件头插入 `> **SUPERSEDED (2026-08-14 23:35)**：本文 §1–§2 的"select 未执行"快照采自当日凌晨，已被 HANDOFF_20260814_select_twostage.md:56 证伪（select×5 于 13:16→15:47 完成）。请勿依据本文 §1–§2 决策。` | P1 §1.6（磁盘 mtime 13:55–15:46 + `selection_procedure:"two-stage"` 键）；`information_architecture.md:51` 明确要求中间状态"标记 `superseded`" | **消除本次审计发现的最危险文档**（它会让下一轮白跑 2.5h select） |
| **T0-6** | AST `docs/status/project_current.md` + `next_execution_plan.md` | 更新 `as_of` 到 8-15；修正"待 Codex review"（`RUN1_RESULTS.md:96` 已完成）；纳入两步式 select 结论 | P1 §3.5 矛盾 2、6；且这本是 `selection_status.md:80`、`select_twostage.md:77` 一直未执行的最后待办 | 状态层与现实对齐 |
| **T0-7** | AST `AGENTS.md` 或 `AI_SESSION_ENTRY.md` | 补记汇报口径双轨：选参 100ms/50cent（冻结契约）vs 汇报 150ms/100cent | P1 §3.3-AR3：该口径目前只存在于 `select_twostage.md:68` | 防止跨文档假比较 |
| **T0-8** | AST `docs/sessions/SESSION_INDEX.md` | 补登记 8-14 三份交接文档（`HANDOFF_20260814.md`、`..._selection_status.md`、`..._select_twostage.md`）与 `EXPERIMENT_REPORT.md` | P0 §4.3：这三份是 hot 却零入链，只能靠 `ls` 发现 | 恢复可发现性 |
| **T0-9** | AST `docs/status/README.md` | 追加"已裁撤文件映射"小节：`metric_management_current.md` → 现由 X 承载；`rebase_current.md` → 现由 Y 承载 | P0 §5.2：45 处历史引用指向这两个不存在的文件 | 一处说明替代改写 45 份归档 |
| **T0-10** | LA `AGENTS.md` Conventions 段 | 追加一条方法论纪律：**"跨基线比较必须同音源（vocal vs mix 不可混比）"** | P1 §2.1-D：该教训目前只躺在 `RUN_STATE.md:65-66` / `09:73-75`，是一条曾导致伪结论的高价值教训 | 防止同类伪结论复发 |
| **T0-11** | LA `docs/sessions/20260814_.../09_GPU_REAL_RUN_REVIEW.md` | 在 `:58-59`"核心假设成立"处加口径注解，指向 `00_SESSION_DISCUSSION_RECORD.md:1294-1300`（884 区域 recovered 0%） | P1 §2.1-C：15 区域乐观结论与 884 区域负结果未调和 | 防止读者误读为正结果 |
| **T0-12** | LA `docs/sessions/20260814_.../06_PLANNED_RUNS.yaml:2` | 状态字段 `implementation_complete_formal_gpu_pending` 更新为实际状态 | P1 §2.2-H3；`07_CODEX_IMPLEMENTATION_PLAN.md:334` 本就要求 `planned→done` 同步 | 制度自洽 |

### 2.2 T1｜低风险移动（孤儿或明确违规，无入链）

| # | 旧路径 | 新路径 | 依据 | 风险 |
|---|---|---|---|---|
| **T1-1** | LA 根 13 个 `PATCH*.md` + `CHANGES_20260728_INLINE_REALIGN_V4.md` + `IMPLEMENTATION_VALIDATION_20260728.md` | `docs/archive/patches/` | 全部为孤儿（无 md 链接、basename 未被任何 md 提及，P0 §4.3）；补丁均已合入（对应 session 目录都在） | **低**。零入链 → 移动不破坏引用 |
| **T1-2** | LA `docs/reports/20260728_inline_realign_formal_v3_data_discussion.md` | `reports/20260728_inline_realign_formal_v3_data_discussion.md` 或 `docs/archive/` | 直接违反 `docs/README.md:11` | 低（需检查 1 处引用） |
| **T1-3** | LA `docs/experiments/20260728_inline_realign_full_mechanism_design.md` | `docs/archive/`（内容为 7-28 设计，已被 v4 取代） | 不在四层职责中 | 低 |
| **T1-4** | LA `docs/cleanup_execution_record_lyricalign.md`、`data_cleanup_checklist_lyricalign.md` | `docs/manual/`（若仍作规程）或 `docs/archive/`（若为一次性记录） | 不在四层中 | 低（前者已是孤儿） |
| **T1-5** | AST `docs/progress/20260814_progress_report_draft.md` | `reports/progress/`（报告平面）或 `docs/sessions/explore/20260806_.../` | `docs/progress/` 不在 `docs/README.md:5-11` 六层中；该文件已是孤儿 | 低 |
| **T1-6** | AST `reports/**` 19 个转义 unicode 文件名（如 `#U4f01#U4e1a#U62a5#U544a…md`） | 同目录、还原为可读中文名（或转纯 ASCII slug） | 文件名不可检索、不可输入；P0 §4.3 | **中**：需同步改写指向它们的引用；建议先 `grep -rn` 统计入链再决定 |
| **T1-7** | AST `docs/sessions/explore/20260731_..._codex_handoff/NEXT_PROMPT.md` 与 `NEXT_PROMPT_FOR_CODEX.md`（sha256 相同） | 保留 1 份，另一份删或改为指针 | P0 §3.1 第 1 组 | 低 |

### 2.3 T2｜需 owner 确认后再动

| # | 对象 | 问题 | 建议 |
|---|---|---|---|
| **T2-1** | LA `docs/sessions/` 48 个扁平 md + 7 个目录 | 两种形态混存，检索心智负担大 | **建议只对 cold session 归整**：把已标 cold 的扁平 md 移入 `docs/sessions/archive_flat/`，hot/warm 不动。需先按 `SESSION_INDEX.md` 温度列表逐个核对 |
| **T2-2** | AST `src/models/basicpitch/diagnostics/run_eval/{v2,v2.1}/README.md` 与 `pesto/eventizer/{...v2,...v2_1}/README_RUN.md`（两组 sha256 相同） | 版本目录复制未改 README → 读者无法区分版本 | 需模型 owner 判断两版差异，**分别改写**而非删除。P0 §3.1 判定风险最高的两组 |
| **T2-3** | AST 46 处 `results/by_run/...` 死引用 + LA 40 处 `runs/...` 死引用 | LA 的属**写法违规**（`AGENTS.md:147` 要求用数据目录绝对路径），AST 的属**产物未落盘或已外置** | LA：批量把 `runs/` → `/home/hyan/Data/lyricalign/runs/`（可脚本化，但须逐条确认非占位符）。AST：先判定"该落盘但没落"还是"已外置"，再决定改引用还是补产物 |
| **T2-4** | AST `tools/baidu_netdisk_aggregate/`（仓库最新改动，未跟踪，与主线无关） | 意图不明。**证据不足**：读过 `git log`、`AI_SESSION_ENTRY.md`、`docs/status/*` 未找到任何说明 | 三选一由 owner 定：① 移出到独立仓库；② 保留并在 `tools/README.md` 声明用途与边界；③ 删除。**不建议自行处置** |
| **T2-5** | LA `AGENTS.md.bak.1786905548` / AST 同名 | 两仓各有一份 8-17 02:39 的备份，未跟踪 | 确认迁移已验收后删除；或移入 `docs/archive/` |

---

## 3. Dry-run 操作清单

> 以下命令**全部未执行**。执行前请逐条 review。
> **强制顺序：先 §3.0 备份 → 再 T0（改内容）→ 再 T1（移动）→ 最后校验。**

### 3.0 前置：备份与基线（必须先做）

```bash
# ① 先解决 P1 的 P0 风险：两仓都有大量未提交改动，移动文件前必须先落盘
cd /home/hyan/LyricAlignment && git status --porcelain | wc -l    # 当前 93，必须先降到 0
cd /home/hyan/AST            && git status --porcelain | wc -l    # 当前 27，必须先降到 0
# ② 冷备份（防移动出错）
cd /home/hyan/LyricAlignment && git bundle create /tmp/LA_$(date +%F).bundle --all
cd /home/hyan/AST            && git bundle create /tmp/AST_$(date +%F).bundle --all
# ③ 记录移动前的文档基线（用于事后 diff）
cd /home/hyan/LyricAlignment && find . -name '*.md' -not -path './.git/*' | sort > /tmp/LA_md_before.txt
cd /home/hyan/AST            && find . -name '*.md' -not -path './.git/*' | sort > /tmp/AST_md_before.txt
```

### 3.1 DRY-RUN：T1-1（LA 根补丁说明归档）

```bash
cd /home/hyan/LyricAlignment
# —— 第 1 步：确认这些文件确实零入链（应输出 0）——
for f in PATCH_README_*.md PATCH_NOTES_*.md CHANGES_20260728_INLINE_REALIGN_V4.md IMPLEMENTATION_VALIDATION_20260728.md; do
  n=$(grep -rl --include='*.md' -F "$f" . 2>/dev/null | grep -v "^./$f$" | wc -l)
  echo "$n  $f"
done
# —— 第 2 步：DRY-RUN 打印将执行的命令（不执行）——
mkdir -p docs/archive/patches   # 真实执行时才建
for f in PATCH_README_*.md PATCH_NOTES_*.md CHANGES_20260728_INLINE_REALIGN_V4.md IMPLEMENTATION_VALIDATION_20260728.md; do
  echo "git mv \"$f\" docs/archive/patches/"
done
# —— 第 3 步：真实执行（去掉 echo 后手工确认逐条）——
```

### 3.2 DRY-RUN：T1-2 / T1-3 / T1-4（LA docs 顶层归位）

```bash
cd /home/hyan/LyricAlignment
echo 'git mv docs/reports/20260728_inline_realign_formal_v3_data_discussion.md reports/'
echo 'git mv docs/experiments/20260728_inline_realign_full_mechanism_design.md docs/archive/'
echo 'git mv docs/cleanup_execution_record_lyricalign.md docs/archive/'
echo 'git mv docs/data_cleanup_checklist_lyricalign.md docs/manual/'
echo 'rmdir docs/reports docs/experiments   # 仅在目录已空时'
# 移动后必须回归检查引用
grep -rn --include='*.md' 'docs/reports/\|docs/experiments/' . | grep -v '^./docs/README.md' | head
```

### 3.3 DRY-RUN：T2-3（LA `runs/` 引用前缀修正）

```bash
cd /home/hyan/LyricAlignment
# —— 只打印将改动的行，绝不 -i 就地改 ——
grep -rn --include='*.md' -E '`runs/[A-Za-z0-9_]' . | grep -v '\.\.\.' | head -50
# 逐条人工判断后，单文件试点（示例，仍为 dry-run 形式）：
echo "sed -n 's|\`runs/|\`/home/hyan/Data/lyricalign/runs/|gp' docs/sessions/20260814_realign_recovery_visualization_overnight/RUN_STATE.md"
# 试点验证：改后该文件的死引用应降为 0
```
⚠️ **不要全库 `sed -i`**：40 条中含 `runs/local/`、`runs/registry/` 等可能是**有意的相对约定**，
且 `AGENTS.md:145-148` 只要求 run 数据路径用绝对路径，不含 `runs/README.md` 这类仓库内真实文件。

### 3.4 DRY-RUN：T0 系列（改内容，用 patch 而非移动）

```bash
# T0-5 是收益最高、风险最低的一条：只加一个文件头
cd /home/hyan/AST
F=docs/sessions/explore/20260806_pesto_causal_12h_program/HANDOFF_20260814_selection_status.md
head -3 "$F"                       # 先看现有头部
# 拟插入内容（人工确认后再写入）：
cat <<'EOT'
> **SUPERSEDED（2026-08-14 23:35）**：本文 §1–§2 关于 "select 一次都没有执行过" 与
> "selection.json 全部为 08-06 旧值" 的快照采自 08-14 凌晨，**已被证伪**。
> 依据：`HANDOFF_20260814_select_twostage.md:56`（select×5 于 13:16→15:47 完成，rc=0）
> 与磁盘实况（`$RUN/joint_eval/*/selection.json` mtime 08-14 13:55–15:46，
> 且含 `selection_procedure: "two-stage..."` 键）。**请勿依据本文 §1–§2 决策。**
EOT
```

### 3.5 执行后统一校验（两仓通用）

```bash
for R in /home/hyan/LyricAlignment /home/hyan/AST; do
  cd $R; echo "=== $R ==="
  git status --porcelain | head -20            # 应只有预期的 R(renamed) 与 M(modified)
  git diff --check                             # 应无输出
  find . -name '*.md' -not -path './.git/*' | wc -l   # 与 before 数量一致（移动不改总数）
done
# 死引用是否下降（复用 P0 的检查口径）
# 期望：LA 反引号失效率 < 11.4%；AST < 13.8%
```

---

## 4. 建议**不动**的部分（含理由）

| # | 对象 | 规模 | 为什么不动 |
|---|---|---|---|
| **T3-1** | AST `docs/sessions/{post_rebase,rebase}/` | **265 md** | [事实] 属跳过清单内的归档；`information_architecture.md:11-17` 把 sessions 定为"执行证据平面"，其价值正在于**原样保存过程**。重整会破坏 `FILES_MANIFEST.md` 的自指结构（54 份 manifest 内含相对路径） |
| **T3-2** | LA `docs/` 下 4 个 research 专题目录 | **68 md** | [事实] `AGENTS.md:19-21` 明确"只作实现和证据追溯"，`:94-97` 还规定 Detector V2 必须从 `18/19/20/21` 号文档进入 → **它们是活的引用目标**，不是死文档。虽不在 `docs/README.md` 四层中，但移动会打断 `AGENTS.md` 的既有指路 |
| **T3-3** | 两仓 `_templates/` | LA 1 + AST 8 | [事实] 模板"零入链"是**制度性正常**，不是孤儿。P0 §4.3 已把它列为方法学假阳性 |
| **T3-4** | LA `.dsh/skills/*/SKILL.md` | 4 | [事实] 由 `skill` 工具按名加载，非文档链接；`AGENTS.md:225` 明确 skill 是"按需加载的工具类知识" |
| **T3-5** | LA `.dsh/review1–9`、`behavior_compare.md`、`slot_config_audit.md` | 12 | [推断 0.8] 是 agent 工作台产物（`.dsh/` 为 DSH 项目级目录），不属项目文档体系。虽零入链，但**移入 docs/ 反而会污染文档树**。建议留在 `.dsh/`，仅在 T0-8 类索引里按需引用 |
| **T3-6** | AST `reports/` 的 7 个分区（progress/tables/research/company/delivery/review/audits） | 123 md | [事实] 与 `information_architecture.md:44`"runs/results/reports = 运行事实、结构化结果、可读结论"一致，分区职责清楚。只需修文件名（T1-6），不需重组 |
| **T3-7** | 两仓 `AGENTS.md:178+` / `:105+` 迁入的全局纪律段 | LA 49 行 / AST 52 行 | [事实] 2026-08-17 刻意从 `~/.dsh/AGENTS.md` 下沉（`AGENTS.md:224` 自述用户级文件已删除）→ 是**唯一副本**，不可再移动或精简 |
| **T3-8** | LA `docs/status/` 只有 4 件、AST `docs/status/` 顶层只有 4 件 | 8 | [事实] AST `docs/status/README.md:3`"本目录只允许四个文件"，实测顶层正好 4 个 → **容器合规**。要修的是**内容陈旧**（T0-4/T0-6），不是结构 |
| **T3-9** | 所有 `runs/` `results/` 骨架目录与 `.gitkeep` | — | [事实] LA `AGENTS.md:145-148` 与 AST 同构约定要求工作目录只留轻量登记，大数据外置 → 空骨架是**设计意图**，不是遗漏 |

---

## 5. 收益预估与验收标准

| 层级 | 动作数 | 预估工时 | 可观察验收标准 |
|---|---:|---:|---|
| **T0**（契约修复） | 12 | 4–6 h | ① `grep -n "2026-08-16" LA/AI_SESSION_ENTRY.md` 命中 override 段；② `grep -i superseded AST/...selection_status.md` 命中；③ 两仓 `docs/status/*` 的 `as_of`/Snapshot date ≥ 2026-08-15；④ AST `SESSION_INDEX.md` 含 3 份 HANDOFF 文件名 |
| **T1**（低风险移动） | 7 | 2–3 h | ① `find . -maxdepth 1 -name 'PATCH*' \| wc -l` = 0（LA）；② `ls docs/reports docs/experiments` 不存在；③ md 总数不变（LA 385 / AST 669）；④ `git status` 只见 `R` 与 `M` |
| **T2**（需确认） | 5 | 视决策 | ① LA 反引号失效率由 **11.4%** 降至 < 5%；② AST 由 **13.8%** 降至 < 8%；③ 19 个乱码文件名归零 |
| **T3**（不动） | — | 0 | 333+ 个文档零风险（LA 68+12+5 / AST 265+8+123 中的归档部分） |

**[推断 0.9] 投入产出判断**：T0 的 12 条只改内容、不动文件，4–6 小时即可消除
本次审计发现的**全部 P0 级文档风险**（误导性 handoff、过期 override、过期状态层）。
**建议只做 T0 + T1-1/T1-5/T1-7，其余排入 P3**——因为 T2 需要 owner 判断，
而 T3 的 333 份文档本就不该动。

---

## 6. 执行边界声明（再次强调）

- 本 session **未执行**上述任何操作：未 `git mv`、未 `sed -i`、未 `rm`、未 `mkdir`、
  未 commit/push/merge，未在两个目标仓库内创建或修改任何文件。
- §3 中出现的 `mkdir -p`、`git mv`、`sed` 均包裹在 `echo` 或 heredoc 内作为**待审命令文本**；
  §3.0 的 `find`/`git bundle` 也未运行。
- 本 session 唯一写入位置：`/home/hyan/waifegameweapon/LAassist/scratch/`。
