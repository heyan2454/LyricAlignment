# 2026-08-07 Transition–Recovery–Detector 计划补丁

本补丁只新增/更新下一阶段的**设计、讨论记录、执行合同与声明式配置**；不伪造任何新实验结果，也不声称新 pipeline 已实现。

## 新增

- `docs/research_transition_recovery_detector_20260807/README.md`
- `docs/research_transition_recovery_detector_20260807/00_FACTOR_MODEL_AND_FREEZE.md`
- `docs/research_transition_recovery_detector_20260807/01_MASTER_EXPERIMENT_PLAN.md`
- `docs/research_transition_recovery_detector_20260807/02_TRANSITION_RECOVERY_MAINLINE.md`
- `docs/research_transition_recovery_detector_20260807/03_LEGACY_GAP_COMPLETION.md`
- `docs/research_transition_recovery_detector_20260807/04_DETECTOR_RESEARCH_PLAN.md`
- `docs/research_transition_recovery_detector_20260807/05_DATA_METRICS_BUDGET.md`
- `docs/research_transition_recovery_detector_20260807/06_AGENT_EXECUTION_CONTRACT.md`
- `docs/sessions/20260807_transition_recovery_detector_discussion_record.md`
- `configs/research_transition_recovery_detector_20260807/session_defaults.yaml`
- `TRANSITION_RECOVERY_DETECTOR_20260807_PATCH_MANIFEST.json`

## 更新

- `docs/sessions/SESSION_INDEX.md`：加入 2026-08-07 hot session。

## 核心变化

1. Slot/non-slot 归入 Align query；不再把 slot 当串行方案；
2. Transition 独立比较 T0 independent、T1 direct serial、T2 core+boundary、T3 stable-boundary；
3. Audio 主倾向压缩超长静音并保留约 3–5s，silence snap 为主 planner；
4. full-slot 为主，non-slot 只少量对照；raw 为研究主输出，official 为次选/reference；
5. 先 Transition，再 propagation / oracle Recovery，再接 Detector closed-loop；
6. 补齐 stress evaluator、serial propagation、hidden、cross-view、occurrence/CNN1D 等旧缺口；
7. Detector 必须正式完成 SA60、SA80、R95；joint 不可行也不能停；
8. 所有新结果写入全新的 session root，不覆盖旧 OUT_ROOT；
9. 单一实验失败、负结果、样本不足不能让 Agent 中途停止整个 session。

## 应用

将 patch archive 解压到仓库根目录覆盖新增文档即可，或运行随包的 `APPLY_TRANSITION_RECOVERY_DETECTOR_20260807.sh` 做存在性检查。

应用后先读：

```text
docs/research_transition_recovery_detector_20260807/README.md
docs/research_transition_recovery_detector_20260807/06_AGENT_EXECUTION_CONTRACT.md
docs/sessions/20260807_transition_recovery_detector_discussion_record.md
```

声明式 YAML 当前 `status: declarative_not_yet_wired`。Agent 必须先 inventory/mapping 现有实现后再接线，不得把配置文件存在误写为已经实现完成。
