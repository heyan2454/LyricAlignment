# 主流程抽象与当前实现对照

## 建议抽象

1. **Initial Planner**：给出初始音频范围、ownership、歌词范围候选。
2. **Alignment Generator**：一次 Qwen 前向产生标准 EvidencePack，并由 raw/official/new decoder 生成同层 AlignmentCandidate。
3. **Detector**：只读取音频、歌词、request、candidate 和历史状态，输出风险、安全边界、候选排序及新的 request。
4. **Serial Controller**：管理 provisional/committed/pending 状态和有限重试。

Realign 不再是一套独立算法，而是 Detector 修改 request 后再次调用 Generator。

## 与旧实现的差异

旧 `windowed_alignment()` 同时负责 planner、歌词预算、Qwen、decoder、cursor、commit、stable 和 precommit detector。旧 detector 多为旁路记录，旧 realign 在完整 baseline 后 shadow 重建，因而产生两套 crop/stable/gate 逻辑。

v6 暂时保持旧 B4 生成路径以保证行为兼容，同时新增 `src/lyricalign/research_v6`：

- `requests.py`：统一 request 与腐化；
- `decoders.py`：同 logits 多 decoder；
- `detector.py`：标准化特征与模型；
- `windowing.py`：动态窗口、静音映射、state injection；
- `audio_support.py`：音频证据；
- `metrics.py`：统一口径；
- `run_alignment_research_suite.py`：E0–E9 执行器。

## 优势

- decoder、Detector、window 的单变量公平比较；
- raw/official 在接口上同层，但元数据保留派生关系；
- realign 可自然迁移到 precommit retry；
- 固定 EvidencePack 可离线重算 Detector/decoder；
- 可明确区分 cursor、time、window 状态传播。

## 劣势与迁移风险

- 真正即时 realign 需要 provisional state 和回滚，当前 formal 仍以 shadow/独立候选为主；
- 接口若只保存时间戳会损失 logits/top-K，因此已扩展 baseline 保存 top-K；
- 动态 request 会增加调用量，正式实现必须限制每窗 retry/beam；
- 模块同层不代表 raw/official 独立，报告必须保留 `derived_from`；
- 主流程迁移前必须做 B4 新旧逐字符等价测试。

## 当前实现完成度

- 已完成研究接口和全部实验执行代码；
- 已完成 top-K evidence 保存和 state injection 钩子；
- 已完成独立实验候选落盘、best-effort 参数冻结和 evidence 收集；
- 尚未把 Detector 直接接入旧 production commit 状态机，避免在 Detector 未验证前改变正式输出；
- E8 已实现局部修正写入串行前缀后，从目标所在窗继续真实模型推理至歌曲结尾；
- E9 已实现模型支持的跨窗 beam，而不是对 baseline 历史 attempts 重新排序；
- E9 行级粗定位仍只是可运行 baseline，不等同于最终 ASR/embedding 粗定位产品方案。

## 2026-07-31 正确性贯通

- `experiment_analysis.py` 统一 local/spliced 指标、serial/silence/causal/line-level 诊断；
- top-K class 使用已有 local/global 边界恢复 offset；
- active Detector score 直接生成 formal spans，而非旁路记录；
- E5 window plan 同时写入 `input_start_sec` 与 `planned_input_character_start`；
- E2–E9 phase 级 resume 与 request cache 避免失败后重做已完成前向；
- 项目汇总和 `formal_report.md` 直接消费 E2–E9 专项结果，不再只列产物目录。

## 2026-07-31 E8/E9 二次贯通

- E5 规划器只消费经过 active-risk gate 的 `safe_boundary_decision_score`，原始边界证据仅作诊断；
- E4-C 只纳入完整 96-unit group，24–95 unit 尾组不再冒充 96-unit 对照；
- E8 continuation 复用冻结 baseline window plan，但携带修正后的 committed prefix/cursor，重跑同窗尾部与后续窗口；
- E8 候选 Detector 使用其自身 continuation trace 的 attempt/window/cursor 证据；
- E9 每个 surviving state 真正进入下一窗口前向；无推进状态淘汰，风险按 evidence 加权均值累计，并显式约束当前进度缺口；
- metric aggregate 对全部负时长或某指标全缺失的候选返回 `null`，不再使 formal 汇总崩溃；
- Pilot freeze 不再以局部失败硬阻断 formal，而是输出 normal/degraded/default 三档效力和明确 warning。

## 2026-07-31 formal decoder 路线补全

- formal 读取 `selected_decoder`，非 official decoder 按冻结 B4 window plan 重跑 operational baseline；
- research decoder 在每窗 ownership/core commit/cursor 更新前投影到 `fixed_*`，因此真正改变串行状态；
- E1、E5–E9 使用冻结 decoder baseline 和 trace，E0 仍使用统一 B4 evidence 保持 decoder 比较公平；
- pilot 明确排除 test/heldout 与 test-derived synthetic-long；
- E8 downstream effect 仅对 continuation complete 候选求均值，失败 static splice 只作诊断。
