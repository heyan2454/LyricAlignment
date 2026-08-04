# Agent 实施合同：10 小时目标 / 12 小时硬上限的长时间线 Slot/判别器实验

## 1. 职责

Agent 负责代码编写、测试、数据发现、长时间线构造、缓存、运行、日志和机器可读汇总。涉及本地路径、模型接口、已有缓存、人工 review artifact 或数据元数据的判断，由 agent 在工作目录内调查并记录证据。

Agent 不负责最终科研文档定稿。所有自动结论必须标为 draft，结果回传后由 ChatGPT 复核和修订。

## 2. 首先阅读

1. `docs/research_v7_align_behavior/13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md`
2. `docs/sessions/20260804_align_behavior_slot_region_assessor_archive.md`
3. `docs/research_v7_align_behavior/11_STAGE_B_FORMAL_REPORT.md`
4. `docs/research_v7_align_behavior/12_COMPLETION_AUDIT.md`
5. 当前 research_v7 代码、attempt/evidence schema、原始 formal 结果和 human-review artifacts
6. `AGENTS.md`

`09_STAGE_A_REPAIR_REPORT.md` 和 `10_STAGE_B_PROGRESS.md` 仅为历史阶段记录；其中 E5、P1 和人工标签状态已由本 patch 修正，不得引用旧表述。

## 3. 冻结事实

- 长数据指 ≥90 秒、以 ≥180 秒为主体的时间线；主模型请求仍使用 fixed 60s acoustic window；
- 不得用人工静音把短样本凑成 180 秒；
- slot 与串行可组合；
- 文本扰动同时包含 1/2/4/8 units 和百分比曲线；
- missing 必须有 virtual gap 评价，replace 必须同时评价 wrong-output 与 omitted-original；
- raw-target 与 official-target 分开诊断，本阶段不冻结最终生产 commit；
- 人工 review 结果与标签已经存在，必须定位、审计并导入，不能继续写“未填写”。

## 4. 实现优先级

1. 立即生成弱人声 calibration packet，与其它开发并行；
2. 修 evaluator、canonical mutation mapping、unit/gap candidate、slot mapping、serial lineage 和历史文档；
3. 实现严格 matched-baseline/cache identity；
4. 完成 ≥180 秒时间线和 fixed 60s window preflight；
5. 完成 density common anchors/phase、非连续 slot、slot+串行和多语言切分 smoke；
6. 完成 hidden extraction contract 与等价性审计；
7. 用 pilot 测真实耗时并将 formal 预测压到 10 小时目标内；
8. 在 12 小时硬上限内运行 formal；
9. 训练并评价 unit/gap H/R/O 子区间判别器及跨域测试；
10. 生成 compact evidence 和 draft 汇总。

## 5. 严禁事项

- 不做全笛卡尔积；
- 不用大量短音频或重复 view 替代长时间线；
- 不把 180 秒误作主模型窗口；
- 不用人工静音凑长数据；
- 不把 P1 prefix recomputation 叫真实串行；
- 不在正式串行每窗用 GT reset；
- 不只输出 request 平均 posterior；
- 不只评分 official；
- 不将 missing 删除 unit 当作普通 output row；
- 不把 replace 只评价成错误输出而忽略被替代 GT；
- 不用不同 slot mask/上下文共享不匹配 baseline；
- 不把系统配置比较写成严格消融；
- 不把无 GT demo 一致性称作 accuracy；
- 不用 attempt 随机切分训练/测试；
- 不在 test/demo 上选阈值；
- 不无限 realign 或永久阻塞；
- 不覆盖旧 OUT_ROOT 或原始 evidence。

## 6. 正式运行预算

- formal 目标 `<=10h`；
- formal 硬上限 `<=12h`；
- 代码开发、用户试听不计入 formal；preflight/smoke/pilot 单独记时；
- pilot 预计 formal 超过 10 小时时必须先缩减；
- 超过 12 小时不得继续启动低优先级 cohort；
- 每阶段保存 elapsed、GPU utilization、forward count、cache hit/miss 和失败数；
- 支持阶段级 resume；
- 单 item 失败不阻止其它独立 cohort，但必须记录实际分母。

优先保留：fixed 60s 长时间线、非连续 slot、density 公共 unit、公平 baseline、绝对+百分比文本错误、missing/replace 评价、真实串行、end-early、跨域判别器和 demo/人工标签审计。

## 7. Cache 与 baseline

缓存必须内容寻址并包含 code/model/processor/environment、audio crop/transform、text units、slot topology、request/window identity、mutation spec/seed、hidden schema、decoder/global-time conversion 和 GT mapping version。

只有完整 request identity 相同的 legal baseline 才能共享。不同 slot mask、文本上下文、audio crop 或 request mode 必须各有 matched legal baseline。

推荐层级：

```text
derived_audio/
processor_inputs/
audio_features/
attempt_evidence/
unit_gap_features/
evaluations/
```

不同判别器特征组合和阈值评价必须复用同一 attempt evidence。

## 8. Preflight 交付

正式运行前生成：

- `available_long_sources.json`
- `duration_distribution.json`
- `constructable_90s_180s.json`
- `window_plan_60s.json`
- `seam_half_second_control.json`
- `multilingual_split_audit.json`
- `slot_contract_audit.json`
- `slot_density_common_units.json`
- `mutation_mapping_audit.json`
- `missing_replace_evaluation_audit.json`
- `hidden_extraction_audit.json`
- `human_review_audit.json`
- `cache_plan.json`
- `estimated_forward_counts.json`
- `estimated_runtime.json`
- `retained_conditions.json`
- `dropped_conditions.json`
- 弱人声 calibration packet

如果数据、映射、hidden 等价性、公平 baseline 或 10/12 小时预算不满足，停止在 preflight/pilot，不能自行改成短数据全量。

## 9. 最终完成定义

- 目标实验实际使用 ≥180 秒时间线主体和 fixed 60s 请求；
- slot 不同工作方式、机制消融和系统配置分别有结果；
- density 主比较使用共同 queried units 并有 phase 轮换；
- 英文词和日文 processor unit 不被窗口错误切断；
- raw、official、hidden 证据可按 unit/gap 回溯；
- missing/replace 评价契约实际运行；
- 判别器在独立 source-song test 上报告 unit recall、interval recall@75%、interval recall@100%、correct-unit FPR 和跨域结果；
- 人工 review 结果/标签已定位、审计并与 packet identity 对齐；
- 正式运行目标 10 小时、硬上限 12 小时；
- 所有结果、失败和缓存身份可复现；
- 自动报告明确标为 draft。
