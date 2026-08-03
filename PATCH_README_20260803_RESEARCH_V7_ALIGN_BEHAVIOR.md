# Research v7 Alignment Behaviour 讨论整理 Patch

## 基准包

本 patch 以以下原始包为基准：

```text
LyricAlignment_202608010232_beforehierchange.zip
```

## 内容

本 patch 为**文档与配置规范更新**，不修改现有实验代码或旧 E0–E9 输出。

新增：

- `docs/research_v7_align_behavior/`：完整下一阶段计划、用户决策记录、项目总账、Qwen 影响、架构评价、mutation/no-match 规范、历史修复边界、Demo 准备和 agent handoff；
- `docs/sessions/20260803_research_v7_align_behavior_planning_archive.md`：本次讨论归档；
- `configs/research_v7/`：mutation catalog 示例；
- `RESEARCH_V7_DISCUSSION_PATCH_MANIFEST.json`：patch 文件身份和校验。

更新：

- `AI_SESSION_ENTRY.md`：增加 v7 入口和当前阶段；
- `docs/research_v6/README.md`：说明 v6 已进入结论修复与 v7 行为研究阶段。

## 应用

在原仓库上覆盖解压：

```bash
cd /home/hyan
unzip -o LyricAlignment_20260803_research_v7_align_behavior_discussion_patch.zip
```

然后阅读：

```text
LyricAlignment/docs/research_v7_align_behavior/README.md
LyricAlignment/docs/research_v7_align_behavior/00_EXECUTION_PLAN.md
LyricAlignment/docs/research_v7_align_behavior/01_USER_DECISIONS_AND_RATIONALE.md
LyricAlignment/docs/research_v7_align_behavior/08_AGENT_HANDOFF.md
```

## 注意

- 本 patch 不包含 research_v7 的代码实现；
- 不会删除旧文件；
- 原 E0–E9 文档和结果仍是历史依据；
- 后续 agent 应按 v7 文档实现，并保留原始输出不覆盖。
