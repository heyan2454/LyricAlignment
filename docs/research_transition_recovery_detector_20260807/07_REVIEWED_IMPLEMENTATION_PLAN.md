# Transition–Recovery–Detector：Review 勘误与 Agent 实现计划

- 日期：2026-08-07
- 状态：`implementation_ready`；尚未接线、尚未产生新实验结果
- 适用范围：实现、测试、smoke、formal、报告与阶段 review
- 优先级：本文件是 00–06 与声明式 YAML 的 review/勘误层；冲突时以本文件为准

## 1. Review 结论

overlay 的研究顺序是合理的：先 Transition，再 propagation/oracle Recovery，再冻结 Detector
工作点，最后只在少数候选上做闭环。它也正确避免了 slot、decoder、transition、threshold、
recovery 和 mutation 的全笛卡尔积。

但原计划不能直接交给 Agent 执行，必须先修正以下 P0/P1 问题：

1. 现有代码只明确实现了一条接近 T2 的 strict core-boundary serial；T1、T3 不能仅靠改名获得；
2. T0 若按 canonical GT 选择每窗歌词起点，只能称 `oracle_independent`，不能称可部署 non-serial；
3. Transition 分叉后，query span、carried state 和 forward 输入会自然不同，不能要求“同一 query content/raw evidence”；
4. 现有静音压缩只保留每侧约 `0.20 s` edge padding，不等于计划中的总保留 `3–5 s`；
5. 当前 `detector_v2_serial.py` 是对已存 evidence 的仿真，不会真实构造下一请求、retry 或 writeback；
6. cross-window posterior 的精确 JS/L1/L2 需要同 class space 的全 posterior；top-k-only 只能标受限近似；
7. 原数据切分把模型选择和阈值选择混在同一 validation；必须改为四个 source-song-disjoint role；
8. 原 12h 表合计 `11.5 h`，却同时声明目标约 `10 h`，没有可靠预留；
9. phase 状态、依赖跳过和全局 blocker 口径不完整，可能导致 Agent 假完成或无限等待；
10. active session 入口仍指向 2026-08-06 阶段，Agent 容易从旧文档开工。

本文件给出修正后的行为定义、代码落点、任务分解、依赖、验收和预算。

## 2. 当前实现盘点与复用边界

### 2.1 可直接复用

| 能力 | 当前落点 | 复用方式 |
|---|---|---|
| 10+60+10 fixed windows | `src/lyricalign/demo/karaoke.py::build_serial_windows` | 作为 fixed control |
| silence snap、leading/trailing silence、short-tail redistribution | `src/lyricalign/demo/window_planning.py::build_silence_aware_window_plan` | 主 planner；冻结参数并导出 resolved plan |
| strict silence boundary | `build_strict_silence_boundary_window_plan` | 仅困难 case，不进首轮主矩阵 |
| reversible compressed/original clock map | `compress_silence_audio`、`map_*time*`、`project_*compressed*` | 复用映射与测试框架，重写 retain 语义 |
| core ownership 与连续 prefix commit | `split_core_commit_prefix`、`append_strict_core_commits` | 作为 T2 adapter 的底层纯函数 |
| 真实串行 forward 骨架与状态注入钩子 | `scripts/demo/align_qwen_fa_serial_demo.py::windowed_alignment` | 抽薄 adapter；不得复制整份脚本 |
| full-slot、raw/official/top-k evidence | `infer_slice`、`research_v7.real_executor`、`detector_v2_evidence_converter` | 统一 evidence schema；补 full-posterior availability |
| canonical mapping、label、tri-state、interval metrics | `src/lyricalign/research_v7/` | 通过稳定 adapter 复用，避免改旧结论语义 |
| content-addressed request identity | `research_v7.requests.AlignmentRequest` | 扩展新 request/state identity，不按文件名缓存 |
| atomic JSON/run state helpers | `src/lyricalign/demo/run_state.py` | 新 session state/event log 复用 |

### 2.2 不可误当成已实现

| 计划能力 | 当前真实状态 | Agent 动作 |
|---|---|---|
| A1 保留总长 3–5 s 的静音压缩 | 未实现；当前近似只保留两侧各 0.20 s | 新增明确 `retained_total_sec` 语义和测试 |
| T0 deployable independent | 未发现 | 先实现 `oracle_independent` 诊断；产品型 T0 单列 gate |
| T1 direct serial | 没有独立、冻结的 commit policy | 新实现纯状态策略；不得把 T2 重命名 |
| T2 core+boundary serial | 基本存在，但耦合在 demo runner | 抽 contract/adapter、补行为与 equivalence 测试 |
| T3 stable-boundary serial | 只有 stable diagnostics；没有延迟/稳定提交状态机 | 新实现 provisional/stable-prefix policy |
| W/L unique RoutePlan executor | 未实现 | 新建 plan 与 executor；executor 不读分数 |
| true closed-loop retry | 未实现 | retry 必须真实 forward，并影响下一 request/state |
| SA60/SA80/R95 新工作点 | 未完成 | 四角色切分后重新冻结；旧 protected point 不复用为 R95 |
| exact cross-window posterior JS | 多数 evidence 仅 top-k | 加 availability gate；重点 corpus 才保存 full posterior |
| hidden experiment | converter 支持 schema，但实际 hidden availability 曾为 0 | hook/equivalence/mapping gate 通过后才运行 |

## 3. 修正后的正式行为合同

### 3.1 共用 request 与 state

新增不可变合同：

```python
@dataclass(frozen=True)
class TransitionState:
    song_id: str
    transition: str
    window_index: int
    next_input_cursor: int
    committed_end_exclusive: int
    committed_ids: tuple[int, ...]
    provisional_ids: tuple[int, ...]
    unresolved_gap: tuple[int, int] | None
    occurrence_by_id: tuple[tuple[int, str], ...]
    previous_committed_end_model_sec: float
    retry_count: int

@dataclass(frozen=True)
class WindowRequest:
    request_id: str
    parent_state_hash: str
    audio_identity: str
    original_bounds: tuple[float, float, float, float]  # input_start, core_start, core_end, input_end
    model_bounds: tuple[float, float, float, float]     # same fields on the model/compressed clock
    query_canonical_ids: tuple[int, ...]
    slot_canonical_ids: tuple[int, ...]
    decoder_evidence: tuple[str, ...]
    transition: str
```

硬断言：

- committed ids 是从 0 开始的连续 prefix，无重复、无倒退；
- `committed_end_exclusive == len(committed_ids)`；
- `next_input_cursor <= committed_end_exclusive` 只允许用于左声学上下文回看，不能跳过未提交歌词；
- provisional 与 committed 不重叠；
- unresolved gap 存在时不能提交 gap 右侧；
- original/model clock 边界均单调，输出评价统一回到 original clock；
- carried timing state 明确使用 model clock；写盘时同时保存映射后的 original-clock diagnostic；
- 同一 state + config + input identity 必须产生相同 request identity。

### 3.2 T0–T3 精确定义

`T0_oracle_independent`：每窗 query span 由冻结 canonical timeline/GT binding 独立构造，不读取上一窗预测
state；只作为单窗能力与传播上界。若后续实现无 GT 的产品型 independent planner，命名
`T0_product_independent_v1`，单独 qualification，不能覆盖 T0 oracle 结果。

`T1_direct_serial`：对当前 input 音频可观察区中所有 uncommitted、合法且连续的 decoded rows，提交到
`input_end` ownership boundary；right lookahead 也可被直接提交，因此它刻意暴露最直接的 carried-state
风险。永久提交仍必须是连续 prefix，越界/倒序行停止提交，不能跳过后继续。

`T2_core_boundary_serial`：只提交 start time 位于 `[core_start, core_end)` ownership 的连续合法 prefix；
left context 已提交行只供上下文，right lookahead 不永久写回。当前 strict serial demo 的行为最接近该项，
但必须通过抽取后的 equivalence fixture 才能宣称已映射。

`T3_stable_boundary_serial`：在 T2 可提交 prefix 内，仅永久提交满足冻结 stability predicate 的连续前缀；
其余保留 provisional，下一窗重新观察。stability 至少绑定两次真实观察或一个预注册等价证据，不能只凭
同一 forward 的 raw/official 一致就称 cross-window stable。首轮最多保留一窗 provisional，不实现无限历史。

T1/T2/T3 使用相同 planner、音频、模型、decoder evidence 和 query-construction algorithm；但 state
分叉后实际 query span 可以不同。比较必须记录：

- `shared_prefix_request_count`：分叉前 exact identity 相同的请求；
- `divergence_window`：首次 state/request 分叉；
- 分叉后各自真实 forward 与成本；
- system-level effect；只有共享 exact request 的局部比较才能声称纯 commit-policy effect。

### 3.3 RoutePlan 与真实闭环

```python
@dataclass(frozen=True)
class RoutePlan:
    route: str                 # none|shadow|L|W
    window_id: str
    commit_ids: tuple[int, ...]
    provisional_ids: tuple[int, ...]
    unresolved_gap: tuple[int, int] | None
    retry_request: RetryRequest | None
    next_input_cursor: int
    reason_codes: tuple[str, ...]
```

唯一数据流：

```text
DetectorOutput -> build_route_plan(...) -> RoutePlan -> execute_route_plan(...)
```

`execute_route_plan` 只能验证并执行，不得读取 `p_bad` 或改变决策。W 的 REJECT plan 必须
`commit_ids == ()`；L 只能提交 cursor 起始的连续 ACCEPT prefix，不能越过第一个
REJECT/UNCERTAIN gap。retry 必须调用真实 aligner，更新 forward/audio-seconds/wall-time；旧 evidence-only
simulation 只能作为 CPU fixture，不能进入 closed-loop 正式结论。

### 3.4 静音压缩合同

新增参数：

```yaml
silence_compression:
  min_original_silence_sec: <pilot freeze>
  retained_total_sec: 3.0 | 5.0
  retained_distribution: centered
  boundary_guard_sec: <resolved>
```

`retained_total_sec` 是每段被压缩静音在 compressed audio 中保留的总时长，不是每侧 padding，也不是
删除时长。长度不超过阈值的静音保持原样；长静音删除中部并保留总长；leading/trailing 使用单侧 guard
但仍需在 mapping 中记录。必须测试：

- 无静音、短静音、恰好阈值、长静音、相邻静音、前导/尾随静音；
- original→compressed→original 在 kept segment 内往返；
- splice 点 start 右连续、end 左连续；
- 所有最终 rows 在 original clock 合法、单调、不过音频长度；
- 3 s/5 s pilot 只用 development songs，formal 前冻结一个值。

## 4. 数据、切分、缓存与 evidence 修正

### 4.1 四个 source-song-disjoint role

同一源歌及其窗口、mutation、重复构造不得跨 role：

1. `detector_train`：拟合 detector；
2. `model_selection`：选择 feature family、模型、hidden layer/schema 和 calibration 方法；
3. `threshold_validation`：只选 SA60/SA80/R95 双阈值；
4. `m4_formal`：选择全部冻结后一次性评价。

MIR 是 fixed transfer；Test Demo 无 GT。若 M4 歌曲数不足以支持四角色，先输出 source-song coverage 和
最小分母，减少模型复杂度或将分支标 `bounded_insufficient`，不得退回 unit-random split。

### 4.2 两级缓存

`forward_cache_key` 至少包含：audio content SHA、preprocessing schema+resolved params、model/revision/checkpoint
content SHA、exact model-clock bounds、query units/span、slot topology、generation config、decoder evidence、
hidden hook schema、code identity、environment identity、canonical mapping schema。

`trajectory_cache_key` 另加：parent state hash、transition policy/version、route/retry policy/version、detector
model/scaler/threshold identity。只有 forward key 完全相同才共享 raw/official forward；state 分叉后不能
因为 song/window 名相同而复用 trajectory。

### 4.3 posterior 与 hidden availability

- top-k evidence 可用于 entropy/margin/top-k displacement；
- 精确 JS/L1/L2 只在同 class-space 的 full posterior 可用时计算；
- 缺 full posterior 写 `not_available_topk_only`，不得填 0；
- full posterior 只保存 Transition candidates 的 overlap、occurrence、propagation-prone 和 safe-control 子集；
- hidden hook on/off 必须在同请求上证明 logits、posterior、raw、official 和 transition decision 数值等价；
- generated token→row→canonical unit 任一映射不闭合，hidden 分支标 `blocked`，raw/official 主线继续。

## 5. 确定性 Detector 工作点

候选阈值仅来自 `threshold_validation` 的唯一 `p_bad` 值加 0/1 边界，要求
`0 <= T_accept < T_reject <= 1`。grey/ambiguous/GT-unavailable 不进入 safe/unsafe 分母。

SA60：在 `safe_accept >= .60` 的候选中，依次最小化 unsafe accept、最大化 unsafe reject、最小化 safe
reject、uncertain、threshold gap，再按阈值字典序 tie-break。

SA80：与 SA60 同一算法，只把 safe accept 约束改为 `.80`。

R95：在 `unsafe_reject >= .95` 的候选中，依次最大化 safe accept、最小化 unsafe accept、safe reject、
uncertain、threshold gap，再按阈值字典序 tie-break。UNCERTAIN 不算 REJECT。

Joint：同时满足 SA60 和 R95 时按 unsafe accept、safe reject、uncertain、threshold gap 唯一选点；不存在则
输出完整 Pareto gap，继续独立 SA60/SA80/R95。阈值函数必须为纯函数并穷举小 fixture 验证。

## 6. Agent 实施阶段与任务拆分

每阶段先实现/自测，再由独立 review agent 只审 P0/P1；修复后才进入下一阶段。子 agent prompt 统一写
`STEP BUDGET=8`，并要求返回改动、测试、产物、未完成项和下一步。不同 agent 使用独立 worktree；主 agent
负责合并和最终测试。

### Phase 0：inventory、preflight 与 freeze skeleton（CPU）

改动/新增：

```text
src/lyricalign/research_transition_recovery_detector/contracts.py
src/lyricalign/research_transition_recovery_detector/session_state.py
src/lyricalign/research_transition_recovery_detector/identity.py
scripts/research_transition_recovery_detector/preflight.py
tests/research_transition_recovery_detector/test_contracts.py
tests/research_transition_recovery_detector/test_identity.py
```

产出 `TRANSITION_IMPLEMENTATION_MAP.md/json`、`PRECHECK.json`、四角色 split、resolved-config skeleton、
SESSION_META/STATE。implementation map 对 T0–T3 必须标 `mapped|partial|missing`，列出函数、真实行为、
decoder、测试与差异；不得预填全部 mapped。

验收：旧 OUT_ROOT 只读；新 root 唯一；state 原子更新/resume；identity 对 audio/query/slot/state/config 任一
变化敏感；preflight 不加载 GPU 模型。

### Phase 1：shared runner、T0–T3 与静音 preprocessing（CPU + small GPU）

改动/新增：

```text
src/lyricalign/research_transition_recovery_detector/audio_preprocessing.py
src/lyricalign/research_transition_recovery_detector/transitions.py
src/lyricalign/research_transition_recovery_detector/runner.py
scripts/research_transition_recovery_detector/run_transition_smoke.py
tests/research_transition_recovery_detector/test_audio_preprocessing.py
tests/research_transition_recovery_detector/test_transitions.py
tests/research_transition_recovery_detector/test_runner_resume.py
```

先把现有 demo pure helpers 包成 adapter；不要复制模型加载、decoder 或 planner。实现 T1/T3；T2 做旧 runner
equivalence fixture；T0 明确 oracle。保存每窗 state-before/request/evidence/decision/state-after。

先跑合成 3+ 窗 trajectory，再跑每种 Transition 1–2 首 development song。3s/5s pilot、original/compressed
mapping 和 raw/official same-forward qualification 都在本阶段完成并冻结。

验收：四 Transition 均能在同 initial state 启动；分叉可追踪；T1/T2/T3 commit 语义不同且测试能区分；
T3 stability 不靠单次同视图伪造；resume 不重复 exact forward；resolved config 不含 null formal 参数。

### Phase 2：Transition pilot/formal 与候选选择

新增：

```text
src/lyricalign/research_transition_recovery_detector/transition_metrics.py
scripts/research_transition_recovery_detector/run_transition_formal.py
scripts/research_transition_recovery_detector/report_transition.py
tests/research_transition_recovery_detector/test_transition_metrics.py
```

先在 `model_selection` songs 做 planner/audio/align 的少量消融并冻结，再在同一 development role 对
T0–T3 运行 C0 None 的候选选择评价。这里不是 M4 formal，所有结果必须标 `development_selection`。
报告 per-song macro、pooled unit、paired delta/cluster bootstrap、first error、cursor/time drift、
missing/duplicate、occurrence jump、forward/audio-sec/wall-time。

候选规则在读取 selection 结果前写入 config：Product candidate 优先有效正确提交覆盖、低错误提交和成本；
Mechanism candidate 优先足量 carried-state error 与可解释性。不得使用 `m4_formal`、MIR、Demo 或某一首
人工观感选候选。输出机器可读 `CANDIDATE_SELECTION.json`，含 tie-break 和不可选择 fallback。

### Phase 3：propagation episode collector

新增：

```text
src/lyricalign/research_transition_recovery_detector/propagation.py
src/lyricalign/research_transition_recovery_detector/corruptions.py
src/lyricalign/research_transition_recovery_detector/occurrences.py
scripts/research_transition_recovery_detector/collect_propagation.py
tests/research_transition_recovery_detector/test_propagation_labels.py
tests/research_transition_recovery_detector/test_occurrences.py
```

按 natural→model-native forced commit→canonical state corruption 收集。每 episode 保存 clean pair、首次真正
wrong commit、state delta、2–5 个真实 follow-up forwards、recovery class 和全 attempt denominator。

主要 family 目标 64 个有效 episode，并增加 source-song 下限 8、单歌占比上限 25%。达到预注册 family
预算仍不足则 `bounded_insufficient`，继续其他 family。local-only、rejected-before-commit、no-effect 不计传播。

### Phase 4：Oracle Recovery 与 stability basin

新增：

```text
src/lyricalign/research_transition_recovery_detector/routes.py
src/lyricalign/research_transition_recovery_detector/route_executor.py
scripts/research_transition_recovery_detector/run_oracle_recovery.py
tests/research_transition_recovery_detector/test_routes.py
tests/research_transition_recovery_detector/test_route_executor.py
```

先实现唯一 RoutePlan，再用 GT 只做 oracle decision/anchor，输入模型时不泄漏 GT feature。扫描预注册 small/
medium/large cursor error、±1/3/6/12s time error、occurrence family；报告 self/slow/persistent/amplifying/
occurrence-jump 和 Oracle-L/W 上界。

验收：W reject 零提交；L 不越 gap；executor 不读取 score；retry 真实 forward；route/state/forward 计数一致。

### Phase 5：legacy gaps（与 Phase 3/4 已有 corpus 配对）

修 stress evaluator，使 model/scaler/feature/threshold/postprocess 完全相同；旧具体 accept-rate 降级。补 targeted
full-posterior cross-view、hidden gate、natural/mechanical occurrence+seam control；旧 CNN1D 只作为历史纠偏，
新 sequence 必须 per-unit supervision/output。

每项写 `complete|negative_result|blocked|not_executed_dependency`，不重新跑已闭合 identity/audit。

### Phase 6：Detector model/feature/threshold freeze

新增或扩展：

```text
src/lyricalign/research_transition_recovery_detector/detector_features.py
src/lyricalign/research_transition_recovery_detector/thresholds.py
scripts/research_transition_recovery_detector/train_detector.py
scripts/research_transition_recovery_detector/freeze_working_points.py
tests/research_transition_recovery_detector/test_no_label_leak.py
tests/research_transition_recovery_detector/test_thresholds.py
```

按四角色顺序：train→model_selection→threshold_validation→冻结。信号顺序 D1 cross-window、D2 coherent
alternate path、D3 per-unit trajectory、D4 轻量 per-unit CNN/TCN、D5 hidden、propagation-risk。每一复杂分支
必须与 frozen simple MLP 公平比较；无 heldout 增益即停止分支。

输出 SA60/SA80/R95/joint/Pareto、六格计数、unit/interval 指标、按 failure family/source song 的分母。

### Phase 7：selected real closed loop

新增：

```text
scripts/research_transition_recovery_detector/run_closed_loop.py
src/lyricalign/research_transition_recovery_detector/closed_loop_metrics.py
tests/research_transition_recovery_detector/test_closed_loop.py
```

Product：None、Shadow、L-SA60、L-SA80、L-R95、W-R95。Mechanism：None、一个高提交 L 点、L/W-R95。
若预算 pilot 超限，按第 8 节降级，不扩全矩阵。报告正确提交覆盖、unsafe commit、unresolved、恢复延迟、
实际额外 forward/audio-sec/wall-time；拒绝全部不能凭低错误提交率获胜。

### Phase 8：M4 formal、MIR fixed transfer、all-discovered Demo

M4 在 Transition candidates、detector feature/model、working points 和 route 参数全部冻结后只运行一次，
同时完成 T0–T3 C0 比较与 selected closed-loop final evaluation；不得用该结果返选 candidate/feature/threshold。
MIR 不重调 scaler/model/threshold。Demo 自动发现全部输入，输出结构硬 gate、route disagreement、
cross-window jump、occurrence ambiguity、intervention/cost 和 suspicious ranking；无 GT 不报告 MAE/accuracy。
单 item 失败写 failures 并继续，不能静默漏歌。

### Phase 9：报告、双 review 与 handoff

所有 Markdown 数字由 authoritative JSON/JSONL 生成。两个并行 review agent 分别检查：

1. 状态机/route/真实 forward/恢复语义；
2. split/identity/分母/指标/预算/文档结论。

只阻断 P0/P1。修复影响结果的 bug 时按 identity invalidation 精确重跑。最后执行 L3 全量测试并生成
`FINAL_SESSION_REPORT.md/json`、`EXECUTION_AUDIT.json`、`NEGATIVE_RESULTS.md`。

## 7. 阶段依赖与允许状态

phase 状态枚举：

```text
pending | in_progress | complete | negative_result |
bounded_insufficient | blocked_global | not_executed_dependency
```

依赖规则：

- Phase 2 依赖 Phase 1 的四策略可运行和 formal config freeze；
- Phase 4 依赖至少一个有效 propagation family；不足时可用预注册 controlled family，仍须标来源；
- propagation-risk detector 依赖足量 episode，其不足不阻塞 correctness detector；
- Phase 7 依赖至少一个合法 Transition candidate、至少一个 detector point 和 RoutePlan smoke；
- 某 detector point 不可行只跳过对应 route，不阻塞其他 point；
- MIR/Demo 的独立结构分析可在 propagation-risk 分支失败时继续。

只有模型/数据/GPU/磁盘/全局 identity 等阻断所有剩余依赖链时，才写 `GLOBAL_BLOCKER.json` 并停止。
依赖不可满足时必须使用 `not_executed_dependency`，不得伪造 complete，也不得无限重试。

## 8. 修正后的 GPU 预算

目标 `10.0 h`，硬上限 `12.0 h`。formal 前用真实 smoke 估算并写 `BUDGET_PROJECTION.json`。

| 阶段 | 目标 GPU 小时 |
|---|---:|
| smoke、3s/5s pilot、失败重试 | 0.7 |
| Transition selection + 最终 M4 T0–T3 | 2.4 |
| propagation harvesting/corruption | 2.0 |
| oracle recovery + stability | 0.7 |
| targeted legacy/full-posterior/hidden | 0.7 |
| detector + working points | 1.3 |
| selected closed loop | 1.2 |
| MIR + all-discovered Demo | 0.5 |
| 目标内机动预留 | 0.5 |
| 合计 | 10.0 |

10h 预测将超时，按顺序缩减：更多 hidden layers、额外 context/strict-silence、额外 non-slot、更多 classifier、
额外 decoder、次要 mutation 强度。10–12h 只用于 mandatory 分母不足或失败重试，并记录 deviation。预测仍会
超过 12h 时停止扩矩阵，完成可独立 CPU/report 工作并请求用户放宽预算；不能偷偷抽样后称完整 formal。

## 9. 测试与验收命令

每个实现 agent 必跑：

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
PYTHONPATH=src python -m pytest -q tests/research_transition_recovery_detector
PYTHONPATH=src python -m pytest -q tests/research_v7/test_detector_v2_*.py
python -m compileall -q src scripts
git diff --check
```

跨接 demo runner 时增加相关 `tests/test_inline_realign_*.py`、`tests/test_qwen_fa_*`。阶段合并、formal 前与最终
收尾运行 `PYTHONPATH=src python -m pytest -q tests/`。

最低行为测试：

- T0 不读取 parent predicted state；T1/T2/T3 在同 fixture 上产生可区分 commit；
- T2 与当前 strict serial core ownership fixture 等价；
- T3 不越过 unstable prefix，下一观察可晋升 provisional；
- W REJECT 零提交；L 不越 unresolved gap；shadow trajectory hash 不变；
- compression 的 retained-total 与 clock mapping 边界正确；
- request/state/config 改变会改变正确层级 cache key；
- source song 不跨四 role；GT/future outcome 不进入 feature；
- SA60/SA80/R95 约束、tie-break、空分母、joint infeasible 正确；
- full posterior 不可用时 exact distance 为 unavailable 而非 0；
- actual forward/audio seconds 与调用记录一致；resume 不重复成功 item。

## 10. Agent 交付物与完成定义

新 session 至少包含：

```text
00_meta/SESSION_META.json
00_meta/RESOLVED_CONFIG.yaml
00_meta/DATASET_SPLIT.json
01_precheck/PRECHECK.json
01_precheck/TRANSITION_IMPLEMENTATION_MAP.md
01_precheck/TRANSITION_IMPLEMENTATION_MAP.json
02_transition/TRANSITION_SUMMARY.json
03_propagation/EPISODES.jsonl
03_propagation/ATTEMPT_DENOMINATORS.json
04_oracle_recovery/ORACLE_SUMMARY.json
05_legacy_gaps/LEGACY_GAP_STATUS.json
06_detector/FROZEN_WORKING_POINTS.json
07_closed_loop/CLOSED_LOOP_SUMMARY.json
08_transfer_demo/MIR_TRANSFER_SUMMARY.json
08_transfer_demo/TEST_DEMO_SUMMARY.json
09_reports/FINAL_SESSION_REPORT.md
09_reports/FINAL_SESSION_REPORT.json
09_reports/NEGATIVE_RESULTS.md
09_reports/EXECUTION_AUDIT.json
SESSION_STATE.json
```

“实现完成”要求 Phase 0–1 代码、合同、smoke、resolved config 和测试通过，只能标
`implementation_complete`；“formal-ready”还要求候选规则、split、预算投影、metric schema 与 freeze 全部闭合；
“session complete”要求每个 phase 都处于终态，并明确区分 verified、exploratory、negative、bounded、blocked/
dependency-skipped。任何未真实运行的实验不能因脚本或 YAML 存在而标 complete。

## 11. 建议首批 Agent 分工

首批只做 Phase 0–1，避免一开始启动 GPU formal：

1. inventory agent：输出 implementation map 与差异，不改运行语义；
2. contracts/identity agent：实现 state/request/session contracts 和 cache keys；
3. preprocessing/transitions agent：实现 retained-silence、T1/T3 与 T2 adapter；
4. review agents：代码/状态机与数据/identity 两路 P0/P1 review；
5. merge agent：修复 review、跑 L2/L3、生成 resolved config 与 small GPU smoke 命令。

Phase 1 验收后再拆 Phase 2–4；候选与 propagation corpus 成立后再拆 Detector/closed-loop，避免各 agent
在尚未冻结的状态合同上并行写出互不兼容的 pipeline。
