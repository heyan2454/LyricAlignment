# align/detect 抽象设计 — 探索性多设计草案

> 状态：探索性讨论稿（非定稿）；formal v8 仍在跑，本文档不触碰 `research_v6`。
> 目标：把 **align（Alignment）** 与 **detect（Detection/Detector）** 抽象为可独立讨论、
> 可独立实现的模块，为后续架构改造提供候选方案。
> 基线事实来源：`docs/research_v6/03_PIPELINE_ARCHITECTURE_AND_IMPLEMENTATION.md`、`requests.py`、`detector.py`、`decoders.py`、`run_alignment_research_suite.py`（file:line 见文末）。

## 0. 现状契约基线（所有设计共同的输入）

- **请求契约**：`AlignmentRequest`（`src/lyricalign/research_v6/requests.py:8`，frozen dataclass）
  `audio_start/end_sec`、`text_start/end`、`ownership_*`、`decoder_names`、`parent_request_id`、`metadata`。
  可 `derive()` 出派生请求。→ **可复用**。
- **Detection**：纯函数 `inspect_alignment(...)`（`detector.py:350`）
  输入 `rows` + 可选证据（`input_candidates`/`window_candidates`/`audio_support_by_index`/`cursor_disagreement_by_index`/`risk_model`），
  输出 `risk_spans`/`safe_boundaries`/`features`（含 `risk_score`/`safe_boundary_decision_score`…）/`selected_detector`/阈值。
  claim：**decoder 无关、阈值透明**（`detector.py:3-7`）。→ **可复用**。
- **Generation（align）**：`decode_rows(rows, DecoderConfig(...))`（`decoders.py:309`）、`DecoderConfig`（`decoders.py:18`，frozen）。
  decoder 名：`raw/official/joint_start_end/topk_sequence/weighted_isotonic`（suite:78）。→ **可复用**。
- **现状闭环（E8）**：`risk_span → 构造 AlignmentRequest → run_request → 多 decoder decode_rows → continuation → 再 inspect_alignment 排序选优`
  （suite:1990-2100）。这段强耦合在 suite，脱离 `SERIAL`/demo 模块无法独立复用。
- **强耦合不可复用**：`run_request`/`propagate_realign_candidate`/`run_cursor_window_beam`/`serial_args` 等（suite），
  以及 `SERIAL.windowed_alignment`（`align_qwen_fa_serial_demo`）、demo 模块。

**核心设计张力**：03:39 明言「模块同层不代表相互独立」——既反对无约束耦合，也反对随意拆独立。
各设计是在这对张力下的不同取舍。

## 1. D1 — Detector 先行-反馈（最小，贴近现状 E8）

- **交互**：detect → 产出 risk/request → 重跑 Generator。
- **抽象**：`align` = f(request)→candidates；`detect` = g(candidates)→risk_spans/新 request。二者经显式 request 通道迭代。
- **优点**：就是 E8 已实现的闭环，改造风险最低；复用 `inspect_alignment`/`decode_rows`/`AlignmentRequest` 即可。
- **风险**：detect 仍"驱动"align，耦合在"detect 先判"；实时/commit 场景需把闭环搬进 Serial（暂 shadow）。
- **复用**：inspect_alignment、decode_rows、AlignmentRequest、candidate_record。

## 2. D2 — request 为标准接口的流水线（产线）

- **交互**：align 与 detect 都只吃/吐 `AlignmentRequest`，经一个显式 request 队列流水化（`req_in → align → candidates → detect → new_request → …`）。
- **抽象面**：`request` 是唯一耦合面；每个环是 `detect` 产出 0..n 个派生 request 供 `align` 继续。
- **优点**：标准化、可重放（request 全程可序列化）、易加日志/审计/离线重算（对齐 03:31 "EvidencePack 可离线重算"）。
- **风险**：要保证 request 循环终止（有界步数/收敛判据）；流水线天然串行。
- **复用**：AlignmentRequest/derive、risk_spans→request 的映射（可抽成纯函数）。

## 3. D3 — 并行独立单元（黑盒，不可变证据契约）

- **交互**：align 与 detect 各自独立、无共享可变状态；二者经**不可变 EvidencePack** 通信（对齐先全量采集证据 → detect 离线独立计算）。
- **抽象**：`align(evidence)→aligned_rows`；`detect(evidence)→report`。committed prefix 只读。
- **优点**：最大解耦、可插拔可替换（任何 align 只要产出契约内证据即可被任何 detect 评估）；天然支持单变量公平比较（03:28）。
- **风险**：03:39 警告——若证据契约不严，"独立"会退化为"无约束耦合"或两套逻辑漂移（03:14 曾出现两套 crop/stable/gate）。
- **复用**：inspect_alignment（本质已是纯函数）、DecoderConfig、requests 数据类。

## 4. D4 — 统一 Serial 状态机（两策略 hook）

- **交互**：align 与 detect 不再是独立模块，而是同一 **SerialController** 内的两个策略 hook，共享 committed prefix / cursor / window plan。
- **抽象**：Controller 定义阶段接口（`on_before_align`/`on_after_align`/`on_commit`），detect 是 pre/post hook，align 是主执行。
- **优点**：符合"反对随意拆独立"（03:39）；实时/commit 场景天然；同一状态机内可做逐窗 precommit 诊断（呼应 `20260727` 的"逐窗提交前诊断"）。
- **风险**：大重构；把现状 suite 各 phase 搬进一个控制器，改动面大。
- **复用**：SerialController 抽象是新代码；内部可调用 inspect_alignment/decode_rows。

## 5. D5 — detector 后置（post-hoc 诊断）

- **交互**：先只跑官方 align 全程，detect 在完成对齐后**独立**评估并标示 risk/spans，不做实时干预。
- **优点**：完全不改 production 输出（最符合"detector 未验证前不改正式输出"03:47/05:5）；可对任意既有结果补 detect。
- **风险**：检测出的问题只能事后表述，无法形成闭环修复；本质回到"旁路记录"（03:14 的旧问题）。
- **复用**：inspect_alignment 后置调用；无需 request 重跑逻辑。

## 6. D6 — request 池化 / 批候选（beam over requests）

- **交互**：一次 detect 产出**多**个派生 request（beam），align 逐一执行，再 aggregate 选择最优（并记录 risk 路径）。
- **抽象**：detect 从"单个 risk_span→单 request"升级为"risk_span→request 集"，aligner 支持多请求。
- **优点**：贴近 E9 的"beam over windows"思想（suite 816 起 run_cursor_window_beam），外推到 request 级别。
- **风险**：组合爆炸；需要剪枝与收敛（复用 E9 的 fallback/风险排名思路）。
- **复用**：AlignmentRequest 集、risk 排名逻辑、E9 的 beam 剪枝概念。

## 7. D7 — detector 提供连续评分（scoring，非阈值）

- **交互**：detect 不只在 bin 化阈值上做标记，而是给出连续 `risk_score`，align（或重排器）以该评分做候选重排/选择。
- **优点**：与 xisting `detector_selection_score`/`min(detector_selection_key)`（suite:2162）方向一致，给出全局最优路径雏形（对应 pending 的 "official 全局概率最优路径"）。
- **风险**：需要定义"全局评分"语义；从局部候选排序到全局定序是架构级跳跃。
- **复用**：detector 的连续 score 字段、experiment_analysis 的 selection 逻辑。

## 8. D8 — 最小契约接口库（contract-first，不选端到端）

- **交互**：只定义 align/detect 之间的**稳定接口/数据契约**（schema + 纯函数签名），暂不实现端到端编排。
- **抽象**：交付物是"接口契约包"——`AlignmentRequest`（已有）、`EvidencePack` schema、`AlignmentGenerator` protocol、`Detector` protocol、风险/决策 record 类型。
- **优点**：推进风险最低、不触碰 suite；为 D1–D7 任一实现提供公共基座；可并行/可评审。
- **风险**：契约若不落到实代码/测试，易散；需至少接口级自洽检查（smoke 不占 GPU）。
- **复用**：requests.py、detector 纯函数签名、DecoderConfig 作为契约模板。

## 9. 对比速览

| 设计 | 耦合方向 | 谁驱动 | 通信媒介 | 实时/commit | 改动量 | 主要风险 |
|---|---|------|----|--|--|--|
| D1 先行反馈 | detect→align | detect | request 迭代 | shadow | 低 | detect 仍主导 |
| D2 流水线 | 双向 | 队列 | request | shadow | 中 | 循环终止 |
| D3 独立单元 | 无（黑盒） | 事件 | 不可变 EvidencePack | shadow | 中 | 证据契约漂移 |
| D4 状态机 hook | 内聚 | SerialController | 共享 committed/cursor | 可实时 | 高 | 大重构 |
| D5 post-hoc | detect 后置 | 无 | 只读 | 无干预 | 低 | 只诊断不修复 |
| D6 request 池 | detect→多align | detect | request 集 | shadow | 中高 | 组合爆炸 |
| D7 连续评分 | align 用 score | align/重排 | score | 中 | 中 | 全局语义难定 |
| D8 contract-first | 无（契约） | — | 接口库 | — | 低 | 需真契约 |

## 10. 前期准备建议

1. 先落 **D8**（契约库）作为基座——把 AlignmentRequest/EvidencePack/两 protocol/风险 record 固化成可复用代码 + 接口自洽检查（不占 GPU）。
2. 从 D8 派生对比实现 **D1**（最小闭环）与 **D5**（post-hoc），两者改动最小、最能验证契约是否够用。
3. 再评估 D2/D4（流水线/状态机）是否值得进入正式改造；D3/D6/D7 作为远期方向保留。
4. 所有代码放 `src/lyricalign/align_detect_designs/`，只 import `research_v6` 纯模块，不改 suite/`research_v6`。

## file:line 索引
- `03_PIPELINE_ARCHITECTURE_AND_IMPLEMENTATION.md:3-8,10,14,20,28-31,36,38-39,47`
- `requests.py:8-41`；`detector.py:3-7,350`；`decoders.py:18,309`
- `run_alignment_research_suite.py:78,176-251,816,1526-1531,1752,1990-2100,2101,2117,2162-2168`
- `20260727_inline_realign_discussion_and_experiment_plan.md:47-58,69-89`（逐窗/稳定段/静音等处）
