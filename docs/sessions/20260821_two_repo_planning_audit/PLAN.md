# PLAN.md — 两仓库规划任务执行计划

任务：只读规划分析 LyricAlignment 与 AST 两仓库，产出 5 个交付文件。
工作目录(scratch)：`/home/hyan/waifegameweapon/LAassist/scratch/`

## 硬约束（本任务）
- 只读：不改/不提交/不移动任何仓库文件；不运行 GPU 或 >5min 任务。
- 唯一写操作：向 scratch/ 写 PLAN.md、DIGEST.md、P0–P4 共 7 个文件。
- 每条结论挂证据（路径:行号 / JSON 键 / commit）；区分[事实][推断][建议]。
- 冲突仲裁：active override 优先；否则文档日期新者优先并记录。
- demo 定义不明：按候选清单顺序选第一个并声明。
- 时长不足：按 P1→P2→P4→P3 优先级交付，DIGEST.md 写 resume 指令。

## 必读清单（按序精读，其余只用统计命令）
LyricAlignment (`/home/hyan/LyricAlignment`)：
1. AGENTS.md
2. AI_SESSION_ENTRY.md
3. docs/sessions/20260814_realign_recovery_visualization_overnight/README.md 及 00–06
4. docs/sessions/20260816_lyric_align_dataset_acquisition_evaluation_strategy/（00–06、05_NEXT_ACTIONS.md）
5. docs/sessions/SESSION_INDEX.md
6. docs/status/ 全部
7. .dsh/review1–9
8. reports/progress/20260816_*.md

AST (`/home/hyan/AST`)：
1. AGENTS.md
2. AI_SESSION_ENTRY.md
3. docs/status/project_current.md、next_execution_plan.md、important_records.md
4. docs/sessions/SESSION_INDEX.md
5. docs/sessions/explore/20260806_pesto_causal_12h_program/（RUN1_RESULTS.md、HANDOFF_20260814.md、HANDOFF_20260814_selection_status.md、EXPERIMENT_REPORT.md）
6. reports/research/20260806_pesto_causal_12h_experiment_program.md

## 阶段执行顺序与动作
- P0 inventory.md：用 find/wc/du/grep 统计两仓文档（排除 legacy/、archive、runs、checkpoint、音频、大文件、.git）；分类（进度/会话/报告/状态/审查/补丁说明等）；过期/重复/孤儿候选（带证据）；死链检查（md 内相对链接解析）。
- P1 status_and_future.md：精读必读清单后归纳主线状态、已完成(证据)、挂起项、风险、开放问题、未来可能性（文档已有 vs [推断]）。
- P2 plan_1w_demo.md：两仓 demo 候选各 2–3 个逐个给可行性与依赖；默认选择(按候选清单顺序第一个)+声明；按天拆解（每天：目标/动作/依赖/验收命令/时长估计）；风险与回退。
- P3 plan_1m_roadmap.md：升级主题分组；每主题：目标/阶段 gate/资源预算/风险；与一周计划关系。
- P4 doc_org_plan.md：目标文档结构树；旧→新映射表；dry-run 操作清单（仅计划，不执行）；建议不动部分+理由。

## 断点协议
- 每完成一阶段立即写该阶段文件并追加 DIGEST.md（已读/未读/当前结论/下一步 resume 命令）。
- 任一时刻中断不返工；resume 时按 DIGEST.md 继续。

## 预计耗时与优先级
- 时长不足时：P1→P2→P4→P3（P3 最后）。

## 验收
- scratch/ 下存在：PLAN.md、DIGEST.md、P0 inventory.md、P1 status_and_future.md、P2 plan_1w_demo.md、P3 plan_1m_roadmap.md、P4 doc_org_plan.md。
- 各文件结论均有证据；数字给出源位置；推断标注。
