# Transition–Recovery–Detector 后续纠偏实现计划

日期：2026-08-08  
状态：待实现（不覆盖既有 `20260808_corrected` 产物）  
前置审查：当前 corrected run 的 query density/resume 与基础三态分母修复可保留；
但 transition 正式汇总、detector、closed loop 和 final report 仍须按本计划补齐。

## 0. 冻结决定与总原则

### 0.1 Detector 标签与正式口径（冻结）

每个有 GT 的 canonical unit 按 start-time absolute error 标注：

| 状态 | 定义 | 用途 |
|---|---:|---|
| Safe | `error <= 100ms` | detector safe target |
| Grey | `100ms < error <= 250ms` | 不进二元 detector train/freeze 分母，单独报告 |
| Unsafe | `error > 250ms` | detector unsafe target |

同时，transition 与 final report 必须报告 `100/250/500/1000ms` 全曲线；`320ms` 仅为
`legacy_320ms` 兼容列，禁止参与 checkpoint、candidate selection、propagation label、detector
label 或工作点冻结。

### 0.2 历史产物与新产物

- 不删除、不覆盖已有 `runs/research_transition_recovery_detector_20260808_corrected/` 中的
  `FORMAL_*`、`FROZEN_WORKING_POINTS.json`、`CLOSED_LOOP_SUMMARY.json` 或最终报告。
- 新结果写入同 session 下的版本化子目录，建议：
  `10_followup/transition_v2/`、`10_followup/detector_v2/`、
  `10_followup/closed_loop_v3/`、`10_followup/reports_v2/`。
- 新报告必须将旧结论标记为 `superseded_for_formal_interpretation`，而不是修改或删除旧文件。
- 下游只消费本计划指定的 `*_v2` / `*_v3` authoritative artifacts；缺失时 fail closed。

## 1. Task A — Transition 离线重汇总

### 目标

利用已完成的 corrected forward，生成统一、可比较的 transition summary，不重跑模型。

### 可复用输入

- serial：`02_transition/<song>__<transition>.jsonl` 的 request、state、raw rows、commit 区间；
- serial formal：`02_transition/FORMAL_model_selection.json` 与 `FORMAL_m4_formal.json` 的逐歌
  `multi_tolerance`（仅作为交叉校验，不能作为唯一输入）；
- full-song：`cache/full_song/*.json` 的逐字符 rows；以音频内容 hash 与 timeline manifest 映射，
  不按文件排序或名称猜测；
- source GT：long timeline manifest。

### 实现

新增纯 CPU 入口，例如：

```bash
PYTHONPATH=.:src python scripts/research_transition_recovery_detector/reaggregate_transition.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" \
  --role model_selection --out "$SESSION/10_followup/transition_v2/REAGGREGATE_model_selection.json"
```

要求：

1. 对 T1/T2/T3 仅评价当窗新 committed ids；对 full-song 评价全部 canonical ids。
2. 输出每 transition、每 song、pooled 的：evaluated/total、committed coverage、correct coverage、
   correct-committed rate、100/250/500/1000ms 计数与率、Safe/Grey/Unsafe 数量、legacy_320ms。
3. 以 `250ms correct coverage` 为 primary product comparison，明确分母均为全部 target units；
   committed-only rate 只能作为辅助诊断。
4. full-song cache 必须逐项与 manifest audio hash、unit range 和 row ids 校验；任一 song 不匹配则
   命令失败，不静默 fallback 或重跑。
5. 生成 `AUTHORITATIVE_TRANSITION_SELECTION_v2.json`，由数据计算 candidate，不允许模板硬编码。

### 验收

- serial 的多容差重算与原 per-song `multi_tolerance` 完全一致；
- full-song 9 首均找到唯一 cache；
- 任意列都可追溯到行级 ids/absolute errors；
- 旧 report 中的 40% coverage/full-song candidate 不得出现在 v2 selection，除非由 v2 数据本身导出。

## 2. Task B — Retry 驱动的 Closed-loop Writeback

### 目标

使 retry 的实际 alignment 输出决定写回，而非仅增加 forward 成本或 observations。

### 固定数据流

```text
serial forward -> detector -> initial RoutePlan -> executor retry
  -> retry rows -> detector(retry rows) -> retry writeback plan
  -> apply writeback rows/state/timestamps -> next serial request
```

约束：

- `RouteExecutor` 只执行传入 plan、返回 retry rows/audit/cost；不得读取 detector score、GT 或自行改决策。
- 编排层是唯一可对 retry rows 再次调用 detector 并构造 retry writeback plan 的位置。
- GT 只在完整执行结束后的 evaluation 使用。
- L：原 ACCEPT prefix 可写回；retry plan 仅可从 gap 起连续提交，不能跨未解决 gap。
- W：retry whole-window 后依据 retry detector 结果重新决定可提交 prefix/未解决状态；不得将原
  whole rejection 当作 recovery 成功。
- 写回的 committed timestamps 必须来自实际写回的 serial/retry row，并记录 row provenance。

### 实现与测试

修改 `route_executor.py`、`run_closed_loop.py` 与对应 contracts；新增 fixture：

1. 同一 initial plan、不同 retry rows 时，writeback state、next request 和 final committed times 不同；
2. retry 无改善时不得虚报 recovery 或提交；
3. L/W 的 retry audio/query/writeback 仍有可观察差异；
4. Gate C 同时检查“写回改变后续 state/request”与“写回含至少一个实际 retry-derived row”；
5. 输出 baseline serial 与 selected closed-loop 的相同分母 delta，包含 cost、coverage、Safe/Grey/Unsafe、
   unresolved、retry provenance。

### 运行

使用新目录 `10_followup/closed_loop_v3/`；必须在 Task C 冻结新的 detector artifact 后才允许真实运行。

## 3. Task C — Detector Phase 4 重建

### 目标

按冻结标签、扩展证据特征和 source-song split 重新训练/冻结 detector；旧 8-feature MLP 只作 legacy baseline。

### 实现顺序

1. **Evidence adapter**：从 serial forward cache/records 提取 raw、official、posterior、跨窗 observations。
   调用 `extract_signal_features()` 与 `cross_window_features()`，而非手工只取 8 个字段。
2. **覆盖审计**：每个信号族输出 availability、missing reason、row/song coverage。若缓存字段不足，精确列出
   缺失字段与受影响 requests，才安排最小补采。
3. **H 分支**：在真实 inference 上尝试 hidden extraction，并验证 hook on/off 的 alignment 数值一致。
   成功则纳入；失败记录 `blocked_api` 和日志，不伪造特征。
4. **Dataset**：按 source-song 角色构造，排除 Grey；label 只由 GT error 得到。V/P/S/PR 特征不得使用未来
   trajectory、GT 字段或 mutation family。PR 仅在 Gate P corpus 通过后构造。
5. **训练/评估**：固定一个 tabular learner，并运行
   `H`、`R`、`O`、`H+R`、`H+O`、`R+O`、`H+R+O`、`H+R+O+selected(V/P/S)`；另运行一个 CNN1D/TCN。
   blocked 分支不算 executed，但必须留下输入、覆盖和原因。
6. **阈值**：仅 threshold-validation role 选择 SA60、SA80、R95；UNCERTAIN 留在 safe/unsafe 全分母，
   Grey 不进二元分母。随后固定并在 M4/MIR 只读 transfer，不重调。

### 验收

- `TRAIN_META_v2.json` 列出每个实际输入特征与覆盖率，不能只出现旧 8 特征；
- `SIGNAL_COMPLETION_MATRIX_v2.json` 的每个 executed/negative 行含 split、n_units、n_intervals、metrics artifact；
- 标签、工作点、interval metrics 均为 100/250 边界，且 320ms 不影响任一结果；
- 若只有 R/O 可用，报告为 partial detector evidence，而不是 Phase 4 complete。

## 4. Task D — Drift 修复与报告重生

### Drift 修复

`committed_end_exclusive` 为半开 cursor。已提交 `0..126` 时 cursor 为 `127`，最后已提交 row 是
`126`。`cursor_time_drift()` 应比较该 row 与 `GT[126]`，而不是 `GT[127]`；若最后 row 缺失，返回
合同缺失诊断，不能拿较早 row 替代。更新单测以覆盖首窗、末窗和 evidence 缺行。

### 报告实现

新增 report v2 入口，只读 Task A/B/C 的 authoritative artifacts，生成：

- `TRANSITION_REPORT_v2.{json,md}`；
- `FINAL_SESSION_REPORT_v2.{json,md}`；
- `NEGATIVE_RESULTS_v2.md`；
- `EXECUTION_AUDIT_v2.json`。

规则：

1. 禁止硬编码任何 candidate、coverage、成功/失败陈述或数量。
2. 每一条结论附 artifact path、scope、denominator、primary tolerance/label version。
3. Task B/C 未完成时明确输出 `not_executed`，不以旧 artifact 填充。
4. old final report/negative results 仅引用为 historical，声明其被 v2 report supersede。

## 5. 执行依赖与交接顺序

| 顺序 | 任务 | 是否需 GPU | 可并行 |
|---|---|---:|---|
| 1 | A：transition 离线重汇总 | 否 | 可与 D 的 drift 单测并行 |
| 2 | D：drift 修复 + v2 report 骨架 | 否 | 可与 C evidence adapter 并行 |
| 3 | C：detector evidence/重训/冻结 | 通常否；缺字段时最小补采 | 与 A/D 并行，完成后才交 B |
| 4 | B：retry writeback fixture 与真实 closed loop | 是（真实 run） | 依赖 C 新 working points |
| 5 | D：最终 v2 report | 否 | 依赖 A/B/C |

每个 agent 交接时需提交：改动文件、测试命令与结果、产生 artifact 路径、未完成原因、对下游的
明确输入版本。正式运行前先通过模块 CPU tests；真实运行结束后再运行该阶段的回归测试与 report gate。
