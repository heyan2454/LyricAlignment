
# Codex Prompt: Complete Dataset Cleaning Automation

你正在服务器 `/home/hyan/LyricAlignment` 工作。请完整阅读：

1. `AI_SESSION_ENTRY.md`
2. `docs/status/project_current.md`
3. `docs/status/next_execution_plan.md`
4. `docs/principles.md`
5. `docs/manual/data_preparation.md`
6. `docs/manual/data_curation.md`
7. `docs/manual/dataset_split_and_leakage.md`

## 总目标

完成 `docs/status/next_execution_plan.md` 中 Stage 0–11 的所有不依赖外部授权的自动化内容：实现、测试、全量运行、证据、文档、Git commit/push 和最终归档。不要提前开始 LoRA。

## 工作方式

- 不要在首次报错、测试失败或数据异常后停止。定位根因、修复并重跑。
- 不要通过 placeholder、TODO、空实现、静默跳过、删测试、放宽断言或伪造结果来通过 gate。
- 一个阶段暂时失败时，记录诊断并继续完成不依赖它的独立阶段；随后返回修复阻塞。
- 只有 OpenCpop 官方授权、外部资产确实不存在或硬件不可用等外部条件才能标记 external blocker。
- 服务器已有 `src/lyricalign/datasets/` 和 `scripts/datasets/`。合并本归档时保留它们，禁止用 ZIP 缺失为由删除或重写成低标准版本。
- 每阶段先实现正确的库函数和测试，再提供薄脚本；不要把核心逻辑堆在 shell 或一次性 notebook。
- 大数据、逐样本输出和音频放 `/home/hyan/Data/lyricalign/`，仓库只保留轻量摘要、schema、配置、测试和 hash。
- 原始数据只读，所有派生数据版本化、原子写入、可恢复。
- 阶段结束及时 Git commit；最终 push 到 `git@github.com:heyan2454/LyricAlignment.git`。

## 必须遵循的研究口径

- 任务：vocal audio + known Mandarin lyrics -> character timestamps。
- 主输入：`native_vocal | official_vocal_channel | model_separated_vocal`。
- MIR-1K 17 首只作为 final OOD test；不得训练、validation 或调参。
- split 最小单位为 song。
- `native_short | synthetic_concat | natural_long` 分开记录和报告。
- 模型失败不能单独决定样本被 rejected。
- 同音随机字实验 deferred；本轮只允许预留 schema，不要把它混入主数据。

## 阶段执行

严格按 `docs/status/next_execution_plan.md` 的 Stage 0–11 和 Gate S0–S11 完成。每完成一个 stage：

1. 运行该 stage 测试和最小 fixture；
2. 对全量目标数据运行；
3. 生成机器可读 `run_summary.json`；
4. 生成轻量 Markdown 报告；
5. 将 gate 状态记录为 `passed/failed/external_blocked`；
6. failed 时继续修复，不能直接结束任务；
7. commit 已完成阶段。

## 最低交付物

```text
src/lyricalign/datasets/              # 完整数据审计、规范化、映射、split、concat
src/lyricalign/audio/                 # vocal inventory/normalization（可按现有结构调整）
src/lyricalign/metrics/               # character metric 与 aggregation
src/lyricalign/pipelines/             # 可恢复评测/raw baseline orchestration
scripts/datasets/                     # audit/prepare/split/concat 薄入口
scripts/evaluation/                   # fixture/evaluation/raw baseline 入口
configs/curation/                     # 冻结的规则模板
configs/metrics/                      # metric schema
configs/paths/                        # 外部路径模板
runs/data_preparation/                # 轻量 run summary
runs/evaluation/                      # 轻量 run summary
reports/                              # 审计、数据质量、泄漏、baseline 报告
tests/                                # 所有核心规则和 fixture
```

目录名称可在不破坏现有架构的前提下调整，但职责不能缺失。

## 最终验收

最终必须至少执行并记录：

```bash
python -m compileall -q src scripts tests
python -m pytest -q
```

还要逐项证明：

- 20,896 M4Singer items 全量审计守恒；
- mismatch taxonomy 守恒且 unknown 比例明确；
- text normalization 幂等且可回溯；
- accepted character mapping 满足所有时间轴不变量；
- vocal audio contract、来源和 hash 完整；
- song split 无同曲跨集合；
- synthetic-long 不跨 song/split，时间轴正确；
- MIR-1K 17/17 vocal OOD manifest 冻结；
- metric fixture 与手算预期一致；
- raw baseline 对 short/synthetic/natural 分开报告；
- 失败、unknown、negative result 全部保留；
- Git 已 push；
- 最终 archive manifest 与 ZIP 内容一致。

## 不允许的结束方式

不得只输出“已完成计划/框架/脚本骨架”；不得在未运行全量数据时宣称完成；不得因为个别 mismatch 难处理而放弃高置信子集；不得以 OpenCpop 阻塞为由停止 M4Singer/MIR-1K 主线；不得启动训练来逃避数据工程。

请尽最大努力正确实现并完成本轮全部自动化目标。
