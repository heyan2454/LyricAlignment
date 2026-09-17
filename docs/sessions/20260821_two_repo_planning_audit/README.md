# 2026-08-21 双仓只读规划审计（外部归位件）

**性质**：一次只读的跨仓库规划审计（LyricAlignment + AST）产物。原文件散落在仓库之外、
且不在任何 git 仓库内，2026-09-17 由 `/home/hyan` 目录清点时归位到本 session 目录。

- 原始位置：`/home/hyan/waifegameweapon/LAassist/scratch/`（`waifegameweapon` 不是 git 仓库，
  文件此前无任何版本控制与索引入链）。
- 文件生成时间：2026-08-21 02:19 → 03:57（`cp -p` 保留 mtime）。
- 执行合同：任务书（见 `PLAN.md`）明确**只读**——不修改/不提交/不移动任何仓库文件，
  唯一写操作是向 scratch 写这 7 个文件。因此本目录记录的是"分析结论"，不是"执行记录"。

## 文件清单

| 文件 | 内容 |
|---|---|
| `PLAN.md` | 任务执行计划：硬约束（只读、证据格式 `[事实]/[推断]/[建议]`、冲突仲裁规则）、必读清单、断点协议。 |
| `P0_inventory.md` | 两仓文档盘点：统计命令与产出表、文档分类、过期/重复/孤儿候选、markdown 死链检查。 |
| `P1_status_and_future.md` | 主线状态核对：对 7 条"已知现状"假设逐条验证，**1 条被证伪**（AST select 实际已于 2026-08-14 13:16→15:47 完成，误导源为 `HANDOFF_20260814_selection_status.md`），并指出 LA 主线契约（0814 realign-recovery）与实际重心（0816 evaluation-v1/产品化）已漂移。 |
| `P2_plan_1w_demo.md` | 一周 demo 计划：两仓各 3 个候选 → 6 个候选的可行性与依赖评估、默认选择声明、按天拆解与回退。 |
| `P3_plan_1m_roadmap.md` | 一月路线图：10 个主题、gate/预算/风险、4 周日程与裁剪方案；预算口径为"GPU 非瓶颈，真实约束是有 GT 样本量 / 数据授权 / 收尾工时"。 |
| `P4_doc_org_plan.md` | 文档组织方案：目标结构树、偏差清单（D1–D8）、旧→新映射与 T0–T3 分级操作清单、**全部为 DRY-RUN 命令**、不动清单。 |
| `DIGEST.md` | 断点档：交付进度表、精读清单（含 subagent 归属）、执行顺序偏差说明、假设核对结论。 |

## 阅读边界（重要）

1. 口径**截至 2026-08-21**。此后主线（`20260816_lyric_align_dataset_acquisition_evaluation_strategy/`
   之后的数据集获取/无训练评测路线、`20260912_gtsinger_gt_deep_analysis/` 等）不在其覆盖范围内，
   本文不作当前状态源；当前状态以 `docs/status/project_current.md` 与 `AI_SESSION_ENTRY.md` 最新段为准。
2. 温度定为 `warm`：P1 的事实核对方法与 P4 的文档组织判断仍具参考价值；
   其中列为"待执行"的 T0/T1 项**并未执行**（本次归位同样只搬运文件，未执行其中任何命令）。
   若要执行，须按当前仓库状态重新核实每一项。
3. AST 相关结论属于另一仓库（`/home/hyan/AST`），在此只作背景与交叉引用，不构成本仓库约束。

## 归位时的 `/home/hyan` 清点判定（2026-09-17）

同一次扫描对 `/home/hyan` 下所有疑似 LyA 散落件的处置结论，一并留档：

| 候选内容 | 判定 | 依据 | 处置 |
|---|---|---|---|
| `waifegameweapon/LAassist/scratch/`（本目录 7 文件） | **独占，未安放** | 不在任何 git 仓库内、仓库零引用 | 归位至本 session 目录 |
| `pack_lyricalignment.sh`（2026-08-08 版） | **分叉变体，含独占内容** | 与仓库 `scripts/environment/pack_lyricalignment.sh`（2026-07-31 版）互有独占行：外部版独有 `--exclude-root`（models/runs/results/reports/docs/sessions/docs/archive 等）便携源码包口径；仓库版独有 `mkdir -p`、秒级时间戳与 ZIP 唯一名校验说明 | 归位为 `scripts/environment/pack_lyricalignment_portable.sh`，主入口不变 |
| `docs/sessions/20260729_render_refresh_old_cache.md` | 纯重复 | 与仓库同名文件 `diff` 完全一致 | 不入库（仓库已有权威版本） |
| `tmp/tmp.vWIJNu3nHc/docs/sessions/20260813_unit_level_realign_overnight/`（5 文件） | 陈旧子集 | 逐文件比对：外部版行数 ≤ 仓库版，且"仅在外部侧"的行数为 0（仓库版为严格超集，另含 04–09 与 README 全量） | 不入库 |
| `docs/sessions/20260813_unit_level_realign_overnight/` | 空目录 | `ls` 无文件 | 不入库 |
| `m4singer_audit_20260830/`（1.4M，3 脚本 + audit + manifest + 217 个 gt_by_item CSV） | **属 AST/Eventizer 线，非 LyA** | 脚本路径引用全部指向 `/home/hyan/AST`、`Data/ast_data/m4singer/current`、`ast_runs_formal/eventizer_paper_unseen_resplit_20260824_*`；主题是无见集 MIDI GT 核实 | 不归入本仓库，交由 AST 线处置 |
| `DISK_INVENTORY_20260917.md` | 跨项目磁盘盘点（AST 主导） | 全文按 AST 清理口径组织，仅引用 LyA 路径作为盘点对象 | 不入本仓库（属运维记录，非项目成果） |
| `AGENTS.md.bak.1786905548`（P4 T2-5 建议删除） | 已被跟踪进仓库 | `git ls-files` 命中（2026-08-17 迁移时的备份） | 保持现状，本次不删不改（P4 T2-5 视为未执行项） |

数据目录侧（`/home/hyan/Data/lyricalign/` 即 `/root/autodl-tmp/AST_storage/Data/lyricalign/`）与
`/root/autodl-tmp/lyricalign_sessions`（1.3G 会话导出）、`/root/autodl-tmp/lyricalign_code_backups`
按仓库约定属外置大型资产，**不进 git**，本次只登记位置不搬迁。
