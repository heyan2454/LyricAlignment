# Full-slot 串行 Detector：Agent 实现方案

- 日期：2026-08-06
- 依据：`01_EXPERIMENT_PLAN.md`
- 面向对象：后续实现、测试、运行与 review agent
- 状态：实现蓝图；完成 Phase A–F 后才允许启动 formal

---

## 1. 目标与边界

本方案把实验计划转换成可直接拆任务、写代码和验收的实现顺序。首要目标是得到一条行为明确、可测试的串行闭环：

```text
统一 full-slot Base
-> clean B0/B1/B2 与历史 B4 shadow
-> 实际前向产生的 carried-state 错误
-> unit 三态 detector
-> 唯一 W/L route plan
-> 严格执行 route plan
-> M4 formal / MIR fixed transfer / 全量 demo 客观回归
```

本阶段不重新训练 forced aligner，不继续扩展旧 Detector V2 实验，也不把 sparse/overlap、decoder、route、阈值和 mutation 强度做全排列。

本方案不要求额外的签名、防篡改或复杂 manifest 体系。JSON/JSONL 只用于：

- 明确输入、参数和分母；
- 支持断点续跑与实际 forward 计数；
- 让报告可由机器重建；
- 检查 B4 shadow 与 route 状态转换。

内容哈希只在缓存身份、输入去重和 shadow 前后比较时使用。

---

## 2. 开始实现前的阅读顺序

1. `01_EXPERIMENT_PLAN.md`；
2. `02_B4_60_SILENCE_OFFICIAL_SHADOW_V1.md`；
3. 本文件；
4. `docs/research_v7_align_behavior/22_DETECTOR_V2_EXPERIMENT_RESULT_REVIEW_20260806.md`；
5. 当前 `src/lyricalign/research_v7/detector_v2_*` 与 `scripts/research_v7/detector_v2_serial.py`；
6. `AGENTS.md`。

若旧实现与本方案冲突，应复用底层数据结构和纯函数，但不继承旧 route 语义或旧报告结论。

---

## 3. 建议代码布局

新阶段使用独立模块，避免继续向 `research_v7` 堆叠实验语义：

```text
src/lyricalign/research_fullslot_serial_detector/
  contracts.py          # unit/window/state/plan 数据合同与校验
  labels.py             # safe/unsafe/grey/ambiguous 标签适配
  base_protocol.py      # full-slot Base 与 B4 resolved profile
  serial_state.py       # cursor、committed、provisional、gap 状态转换
  routes.py             # B0/B1/B2/W/L 计划生成；不得执行 forward
  route_executor.py     # 只执行 RoutePlan，不重新做策略判断
  mutations.py          # prefix/provisional/occurrence mutation 与 episode 生成
  evidence.py           # raw/official/hidden unit 与 sequence evidence
  hidden_audit.py       # hook 等价、token/row/unit 映射
  thresholds.py         # SA60、R95 和可选 joint 的确定性选点
  metrics.py            # detector、串行传播、route 与成本指标
  demo_regression.py    # 无 GT demo 硬断言、代理指标与 case 排名
  reporting.py          # 从 JSON/JSONL 重建摘要

scripts/research_fullslot_serial_detector/
  preflight.py
  run_base_smoke.py
  collect_clean_and_mutated.py
  train_detector.py
  run_closed_loop.py
  run_formal.py
  run_demo_regression.py
  build_report.py

tests/research_fullslot_serial_detector/
```

允许直接调用 `research_v7` 中已经测试过的 canonical mapping、label 和 feature 纯函数；新模块负责收紧串行状态、route 与本阶段指标语义。

---

## 4. 必须先固定的操作定义

### 4.1 Unit correctness 标签

M4 precise GT 的 raw 与 official target 分开标注：

- `safe`：onset 和 offset 绝对误差都 `<=100 ms`，时间合法且 occurrence 正确；
- `unsafe`：任一边界误差 `>250 ms`，或输出缺失、时间反转/越界、wrong occurrence、连续全局错位；
- `grey`：不属于 safe/unsafe 的 100–250 ms 过渡带；
- `ambiguous`：GT 无法唯一确定 occurrence；
- `gt_unavailable`：没有可用精确 GT。

训练和 SA/R 选点只使用 safe/unsafe。grey、ambiguous、gt_unavailable 必须报告数量，但不进入二分类分母。只评价当前 query/full-slot 中要求输出的 canonical units；纯上下文 unit 不因没有输出而标 unsafe。

MIR weak GT 使用同样字段，但单独报告，不能与 M4 pooled。

### 4.2 两类“有效错误”必须分开

`induced_state_error`：mutation 经 `t-1` 真实 forward、decoder 和 route 后，确实改变了 committed/provisional/cursor/occurrence 中至少一项。

`propagated_serial_error`：同时满足：

1. 已满足 `induced_state_error`；
2. 窗口 `t` 从该错误 carried state 构造输入；
3. 没有 GT reset；
4. 在 `t` 或更后窗口仍出现错误 cursor、wrong occurrence、duplicate/missing commit、错误时间轨迹或相对 clean trajectory 的实质偏离。

只有 `propagated_serial_error` 可以计入“累计错误 episode”主配额。仅在 `t-1` 出现的局部错误、三 unit 的当前窗异常或随后立即恢复的情况，进入诱发率/局部鲁棒性统计，但不能充当传播样本。

每个 episode 保存 mutation attempt 数、是否改变 state、是否传播、传播窗口数、错误 units、是否自主恢复及恢复距离。

### 4.3 自主恢复

自主恢复要求：不使用 GT cursor/prefix，连续两个窗口满足以下条件：

- cursor 与 clean/GT canonical cursor 一致；
- committed IDs 没有新增 missing/duplicate/wrong occurrence；
- 已有 unresolved gap 被解决或保持明确阻塞；
- 后续一个窗口不立即复发。

形式上允许报告“首次重新汇合”和“稳定恢复”两个时间点，主指标使用稳定恢复。

---

## 5. 核心数据合同

### 5.1 SerialState

```python
@dataclass(frozen=True)
class SerialState:
    song_id: str
    next_cursor: int
    committed_end: int
    committed_ids: tuple[int, ...]
    provisional_ids: tuple[int, ...]
    unresolved_gap: tuple[int, int] | None  # half-open canonical interval
    occurrence_by_id: Mapping[int, str]
    window_index: int
    retry_count: int
```

硬断言：

- `committed_ids` 严格递增、无重复且从歌曲起点到 `committed_end` 连续；
- `next_cursor == committed_end + 1`；
- provisional 不得出现在 committed 中；
- unresolved gap 存在时，禁止提交 gap 后方 unit；
- state transition 不得回退或覆盖已永久提交结果。

### 5.2 RoutePlan

```python
@dataclass(frozen=True)
class RoutePlan:
    route: str
    window_id: str
    commit_ids: tuple[int, ...]
    provisional_ids: tuple[int, ...]
    unresolved_gap: tuple[int, int] | None
    retry_request: RetryRequest | None
    next_cursor: int
    reason_codes: tuple[str, ...]
```

`build_plan(detector_output, state, window)` 可以判断策略；`apply_route_plan(plan, state)` 只能验证并执行。executor 不得重新读取概率、重新决定 commit，或把 REJECT 当 ACCEPT。

每次执行同时输出简洁 `ROUTE_PLANS.jsonl`，供测试、调试和报告使用；不需要额外签名。

### 5.3 WindowRecord

至少记录 nominal/actual input/core 边界、query canonical interval、左/右上下文、decoder、实际模型调用次数、baseline/retry/local-realign 耗时。所有 runtime forward 必须来自实际调用计数器，不能用模拟 action 数代替。

---

## 6. B0/B1/B2 的可比实现

B1 与 B2 必须使用同一批歌曲、同一实际 window plan、同一 10+60+10 音频输入、同一 full slots、同一 official decoder。两者只允许在提交状态机上不同：

- B0：每窗 oracle canonical start，独立运行；
- B1：core ownership 内合法输出直接永久提交，不保留 provisional；
- B2：只提交满足稳定条件的连续前缀，右边缘/lookahead 保留 provisional，下一窗重新观察。

如果实现发现 B1 必须使用不同 window plan，新增一个明确的 `B1-shared-plan` 消融；不得用同时改变窗口和提交规则的 B1/B2 差异声称 stable-window 有因果收益。

B2 的稳定条件从现有 inline-realign 参数开始，运行时解析为配置值；不得在 M4 formal 或 demo 结果出来后修改。

---

## 7. W/L 确定性状态机

### 7.1 W：整窗否决

W 只查看当前可提交连续区域：

1. 存在 REJECT：`commit_ids=()`，保持原 cursor，从最近已永久提交边界重新发一次 retry；
2. 无 REJECT、存在 UNCERTAIN：`commit_ids=()`，保持原 cursor，发一次扩大右观察的 retry；
3. 全 ACCEPT：提交 B2 本来允许提交的稳定连续区域；
4. retry 后仍有 REJECT/UNCERTAIN：标记 unresolved，当前窗口不再追加 forward，等待下一实际窗口继续观察；
5. 每个 nominal window 最多一个 W retry。

默认 retry 只增加右侧观察 10 秒，音频上限受歌曲边界约束；不改变歌词 cursor，也不引入 GT。REJECT 时硬断言 `committed_count == 0`。

### 7.2 L：可信前缀与局部 gap

1. 从 cursor 开始取连续 ACCEPT 且满足 B2 稳定条件的前缀；
2. 第一个 REJECT/UNCERTAIN 开始形成 gap；
3. gap 后输出只可作为 provisional anchor candidate；
4. 右 anchor 至少连续 2 个 ACCEPT units，并在两次观察中 occurrence 一致、时间差不超过冻结容忍度；
5. local retry 使用左 committed anchor、gap、右 provisional anchor 和有限上下文；
6. local retry 成功后只提交从 cursor 开始的新连续前缀；
7. 失败后 gap 保持 unresolved，禁止越过 gap；
8. 每个 gap 最多一个 local retry，后续新窗口可以重新观察，但不能在同一窗口无限循环。

默认 local audio 上下文为 gap 预计时间左右各 5 秒，并受当前 80 秒 input 边界限制。若无合法右 anchor，不发 local retry，直接保持 unresolved。

### 7.3 Retry 可配置但不可临场改规则

上述 `max_retry=1`、W 额外右观察 10 秒、L 左右各 5 秒、anchor 连续 2 units 是首版默认值。agent 可以在 CPU/small GPU smoke 中因接口错误或明显不可运行而修正，但进入 threshold-validation 前必须写入 resolved config，之后只修 bug，不根据 formal/test 质量调参。

---

## 8. Mutation 与累计错误收集

### 8.1 首版 major families

为消除“主要 family”歧义，首轮只有以下四类进入主配额：

1. `prefix_replace`：未提交 prefix 的 1/2/4/8 units 或 5%/10%/20%；
2. `provisional_edit`：删除、重复、交换 provisional tail；
3. `near_occurrence_prefix`：替换为另一重复 occurrence 的相似 prefix；
4. `cursor_local_edit`：cursor 邻域局部替换或 occurrence state 扰动。

相邻句、同音词、机械重复等作为 family 内选择策略，不另行膨胀主矩阵。

### 8.2 配额

每个 family 目标：

- `>=64` 个 propagated episodes；
- `>=8` 个 source songs；
- 单歌占比 `<=25%`；
- 同时完整报告全部 attempts 和 induced-state success rate。

配额是目标而不是制造假完成的理由。达到 family GPU 上限仍不足时，输出 bounded-insufficient，并继续执行已经具备有效分母的主实验。严禁把当前窗局部异常重命名为 propagated episode 补数。

### 8.3 构造数据控制

机械重复必须同步复制音频、歌词和 canonical labels。每种 seam 处理配一个相同 cut/rejoin、但不改变歌词结构的 control，比较 detector 是否只识别拼接噪声。若 seam control 触发率异常升高，该构造 family 只能做诊断，不能支撑 occurrence 结论。

---

## 9. Evidence、特征与 Hidden 顺序

### 9.1 一次 forward，多种离线特征

同一请求尽量一次保存 raw posterior、official rows 和可选 hidden，再离线构造 R-unit、R-sequence、H-unit、H-sequence 组合。GT、mutation family 和 error magnitude 不得进入 feature columns。

缓存只需正确区分模型、音频、歌词/slots、窗口、carried state、decoder/hook schema；无需建立额外可信链。

### 9.2 Hidden gate

hidden pilot 必须在最终 detector/threshold 冻结前完成：

1. 固定少量 development 请求；
2. hook off/on 比较 logits、posterior、raw/official rows 和 cursor；
3. 完成 generated token -> output row -> canonical unit 映射；
4. 失败则将 H 标为 blocked，继续 R 路线；
5. 成功后只在 detector train/calibration 上比较特征组合。

不得用 M4 formal、MIR 或 demo 选择层、hidden schema 或 feature set。

### 9.3 数据切分顺序

按 `source_song_id` 固定四个角色：

```text
detector_train
model_calibration
threshold_validation
M4_formal
```

- train：拟合 detector；
- calibration：选择 feature/model，并做概率校准；
- threshold-validation：只选择 SA60/R95 双阈值；
- M4 formal：所有选择完成后一次性评价。

构造样本继承源歌曲角色。同一源歌及其全部 mutation、机械重复和窗口不得跨角色。

---

## 10. 确定性工作点选择

候选阈值来自 threshold-validation 的唯一 `p_bad` 值，加 0/1 边界；只接受 `T_accept < T_reject`。

### SA60-primary

在 `safe_accept_rate >= 0.60` 的候选中按以下 tuple 升序选择：

```text
(unsafe_accept_rate,
 -unsafe_reject_recall,
 safe_reject_rate,
 uncertain_rate,
 T_reject - T_accept,
 T_accept,
 T_reject)
```

### R95-primary

在 `unsafe_reject_recall >= 0.95` 的候选中按以下 tuple 升序选择：

```text
(-safe_accept_rate,
 unsafe_accept_rate,
 safe_reject_rate,
 uncertain_rate,
 T_reject - T_accept,
 T_accept,
 T_reject)
```

### Joint

同时满足 SA60/R95 时，以 `unsafe_accept_rate`、`safe_reject_rate`、`uncertain_rate` 的顺序选唯一点。不存在时记录 Pareto 表，但 SA60-primary 和 R95-primary 仍继续运行。

选点函数必须是纯函数，并用穷举小样本测试验证约束、tie-break 和空分母行为。模型/feature 选择先于阈值选择，不能在 threshold-validation 上重新选 feature family。

---

## 11. 指标与主比较

### 11.1 主指标

- Detector：六格计数、SA、unsafe reject/accept、最长连续 unsafe accept；
- Serial：downstream erroneous units、传播窗口数、稳定恢复率、duplicate/missing commit；
- Route：正确提交覆盖率、错误提交率、unresolved units、额外 forward；
- 成本：实际 forward、重算音频秒、wall time、p50/p90/p99、峰值显存。

拒绝全部内容不能靠较低 committed-unit error rate 获胜。W/L 必须同时报告：

```text
correct committed units / all evaluable units
unsafe committed units / all unsafe units
unresolved units / all queried units
actual forward count
```

### 11.2 预注册主比较

- B1 vs B2：同窗配对，比较 downstream error、duplicate/missing、正确提交覆盖和成本；
- W-R95 vs L-R95：同 episode 配对，主看 unsafe committed units 与额外 forward；
- B2 vs L-SA60：主看高 safe acceptance 下的错误传播和正确提交覆盖；
- R-unit vs 最佳含 H 组合：只在 M4 formal 报增量，不用 formal 结果返选。

首轮必须路线按 cohort 固定为：

| Cohort | 必须路线 |
|---|---|
| M4 development/formal | B0、B1、B2、W-R95、L-R95、L-SA60、B4-shadow |
| MIR fixed transfer | B1、B2、W-R95、L-R95、L-SA60、B4-shadow |
| 全量 test demo | B2、W-R95、L-R95、L-SA60、B4-shadow |

joint、SA80、R99 和 decoder 消融均为第二层。B4 与新路线只在共享输入上配对；效率比较只使用 B4 baseline 成本，shadow 成本另列。

报告 per-song macro、pooled unit 和 source-song cluster bootstrap 95% CI。计划中“显著改善”至少要求 paired bootstrap CI 不跨 0；同时报告绝对效应，避免只看显著性。效率是否可接受以相对 B2 的实际 forward 和 wall-time 呈现，不预先把单一成本阈值包装成质量结论。

---

## 12. Demo 自动回归门

Demo 无 GT，因此 gate 只约束确定的结构与相对行为，不声称 accuracy。

在全量 demo 运行前生成一份简单配置，至少包含：

### 硬失败

- 负时间、越音频边界、canonical commit 乱序或重复；
- cursor 非单调或不等于第一个未提交 unit；
- W 的 REJECT 窗口发生提交；
- L 越过 unresolved gap 提交；
- B4 `actual_writeback_count != 0` 或 baseline trajectory 被 shadow 改变；
- 某路线静默漏跑已发现歌曲。

### 回归告警

- 相对 B2，W/L 新增 missing/duplicate commit；
- clean-relative mutation 恢复率下降或恢复窗口明显变长；
- p90 wall time、forward/audio-minute 明显上升；
- 某语言的 unresolved ratio、零推进窗口或 occurrence instability 异常升高。

告警默认不自动宣称失败或提升，而是进入困难 case 排名。阈值使用 development/demo 历史基线预先写入，不根据本轮表现临时移动。每种语言随机抽查少量正常样本，并抽查最高异常和路线差异最大的样本。

---

## 13. GPU 预算与降级顺序

formal 前必须用真实小 pilot 估算每类实际 forward 和 wall time。建议 12 小时上限分配：

| 项目 | 目标预算 |
|---|---:|
| smoke、失败重试预留 | 0.5 h |
| M4 clean、mutation、W/L primary | 5.0 h |
| M4 formal primary | 2.0 h |
| MIR fixed transfer | 1.5 h |
| 全量 demo primary routes | 2.0 h |
| 机动预留 | 1.0 h |

预算不足时依次删除或缩减：SA80/R99、joint、decoder 消融扩展、额外 hidden 组合、非 major mutation 强度、次要可视化。不得删除 SA60-primary、R95-primary、B1/B2、W-R95/L-R95、M4 formal、MIR fixed transfer或全量 demo 的硬结构检查。

若剩余 mandatory 工作经 pilot 仍预计超过 12 小时，agent 必须停止扩矩阵，报告 projected cost，并将阶段标为 bounded-incomplete；不能偷偷抽样后仍称“全量完成”。可在用户书面放宽预算后继续。

---

## 14. 实现阶段与验收

### Phase A：合同与纯 CPU 状态机

实现 contracts、SerialState、RoutePlan、W/L plan 和 executor。

验收：

- W reject 零提交；
- L 不越 gap；
- apply 只执行 plan；
- cursor/committed/provisional 不变量 property tests；
- retry 上限与预算耗尽行为可复现。

### Phase B：Base 与 B4 接线

把 YAML 解析到现有 inline-realign 参数，输出 resolved profile；实现 B4 shadow 前后 trajectory 比较。

验收：

- 10+60+10 实际边界可见；
- B1/B2 使用相同 window plan；
- B4 writeback 为 0；
- baseline/shadow forward 与耗时分开。

### Phase C：Clean baselines 与标签适配

运行 CPU synthetic 和少量真实 smoke，完成 M4 label adapter、split 和 B0/B1/B2。

验收：safe/unsafe/grey/ambiguous 分母闭合；raw/official 分开；context-only 不被误标 unsafe。

### Phase D：Mutation 与 episode collector

实现四个 major families、clean paired trajectory、induced/propagated 两级判定与 seam control。

验收：mutation 必须经过真实 forward；手工构造的 no-effect、local-only、propagated、recovered 四类测试均分类正确。

### Phase E：Evidence、Hidden、模型

实现统一 evidence、sequence features、hidden audit、source-song 切分与模型选择。

验收：GT 字段不能进入 features；hook 等价；同歌不跨 split；hidden blocked 时 raw 路线仍能完整运行。

### Phase F：工作点与闭环 smoke

实现确定性 SA60/R95/joint 选点，并在 development episode 上运行 B1/B2/W/L。

验收：纯函数穷举测试通过；actual forward 计数正确；RoutePlan 与最终 state 一致；运行预算估计完成。

### Phase G：Formal

按顺序运行：M4 formal -> MIR fixed transfer -> 全量 demo。formal 只允许修复执行 bug；修复后受影响 cohort 整体重跑，不重新选择模型、feature 或阈值。

### Phase H：报告与 review

从 JSON/JSONL 自动生成主表、失败项、预算使用、结论边界和困难 case。review 优先检查状态机、分母、split、actual forward、route 配对与无 GT 结论越界。

---

## 15. 最小测试集合

每个实现 agent 至少运行：

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
PYTHONPATH=src python -m pytest -q tests/research_fullslot_serial_detector
PYTHONPATH=src python -m pytest -q tests/research_v7/test_detector_v2_labels.py \
  tests/research_v7/test_detector_v2_metrics.py
python -m compileall -q src scripts
git diff --check
```

跨接 inline-realign 或 research_v7 时再运行 `tests/research_v7`。阶段合并与 formal 前运行全量 `tests/`。

---

## 16. 建议运行产物

只保留对执行和结论有直接价值的产物：

```text
resolved_base_profile.json
dataset_split.json
label_summary.json
clean_trajectories.jsonl
mutation_attempts.jsonl
serial_error_episodes.jsonl
feature_schema.json
hidden_audit.json
working_points.json
route_plans.jsonl
serial_trajectories.jsonl
m4_formal_summary.json
mir_transfer_summary.json
demo_objective_summary.json
runtime_summary.json
final_report.md
```

失败请求追加到 `failures.jsonl`。不要求为这些文件建立额外签名、登记或防篡改链；保证内容完整、字段明确、可从原始 evidence 重建即可。

---

## 17. Agent 完成定义

实现阶段完成需同时满足：

- 新模块和脚本具有可运行入口；
- B1/B2 输入可比，B4 shadow 零写回；
- W/L 使用同一 RoutePlan 语义，executor 不二次判断；
- propagated episode 不被 local-only 错误冒充；
- hidden 在阈值冻结前完成或明确 blocked；
- SA60-primary 与 R95-primary 均可确定性生成；
- M4/MIR/demo 分开运行、分开报告；
- 全量 demo 硬结构 gate 生效；
- 实际 forward、route 成本和预算状态可信；
- 测试、compileall 和 `git diff --check` 通过。

如果 formal 尚未运行，报告必须写“implementation-ready”或“formal-ready”，不能写实验结论已经完成。
