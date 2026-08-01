# E8/E9 与 best-effort freeze 修复（2026-07-31）

## 任务决定

本轮按用户决定执行：

- E8 的后续窗口影响必须用正式串行重推实现，不能保留静态 splice 指标冒充因果传播；
- E9 必须实现真实跨窗 beam；
- Resume/request cache 的强身份校验暂不继续加固，算法变化后仍依赖新 `OUT_ROOT` 隔离；
- pilot 不应因局部失败阻断最终结果，允许降低统计效力后继续 formal；
- 上一轮 review 的其余问题全部修复。

## 1. E5 安全边界贯通

Detector 对边界保存两种值：

- `safe_boundary_score`：未经过风险门控的边界证据；
- `safe_boundary_decision_score`：只有 active risk 不高于冻结 safe-risk ceiling 时才保留，否则为 0。

E5 planner 现在只消费后者，同时保留前者作诊断。Detector 的 `safe_boundaries` 列表、formal safe-boundary 指标和 E5 `minimum_score` 共用冻结的 `dynamic_safe_score`，不再分别写死阈值。

## 2. E8 正式下游串行传播

### 原问题

旧实现只替换目标 span，而目标之后的 baseline rows 完全不变，因此 downstream MAE/coverage delta 理论上恒为 0，只能证明静态 splice 没覆盖后文，不能回答 realign 是否改变错误传播。

### 当前实现

1. local raw/official/joint/top-K 候选只替换 Detector target span，形成 seed；
2. seed 中 `[0, target_end]` 成为不可回滚 committed prefix；
3. 找到 baseline 中拥有 target end 的窗口；
4. 从该窗口开始，复用冻结的 baseline window plan；
5. 重新运行该窗剩余字符和全部后续窗口；
6. 保存 continuation trace、失败原因、重跑窗口数、完整 alignment；
7. 候选 Detector 只使用该候选自己的 continuation attempts/window/cursor/audio 证据，不把偏离 baseline 当作异常。

### 指标

每个候选同时保存：

- target local metrics；
- 静态 splice full/downstream metrics，仅作为对照；
- serial-continuation full/downstream metrics；
- downstream delta vs baseline；
- downstream delta vs static splice；
- continuation failure；
- selector vs final-candidate oracle；
- clean harm。

传播失败的候选仍落盘，但不进入自动选择，避免静默丢失 negative result。其 static splice 指标保留；serial downstream metrics/delta 为 `null`，项目级传播效应只在 `propagation_status=complete` 条件下统计。

## 3. E9 真实跨窗 beam

### 状态

每条 hypothesis 保存：

- committed rows；
- committed cursor；
- next input cursor；
- previous committed count/core duration/stable suffix；
- 完整 branch path；
- fallback、进度缺口、风险、结构错误和调用诊断。

### 分支

默认每个 surviving state 在下一窗口尝试：

1. nominal；
2. cursor + audio-window backtrack；
3. wider text budget。

每个分支均真实调用模型并只推进一个窗口，再与其他 parent 的分支共同剪枝。它不是 baseline 历史 attempts 的离线重新排序。

### 淘汰与剪枝

- 本窗 committed cursor 没有前进的 hypothesis 直接判失败；
- 等价尾部状态去重；
- 最多保留 `system_beam_width` 条；
- 排序不使用 GT，依次比较：fallback count、当前进度缺口、risk span、结构错误、最大风险、按 feature 数加权的累计平均风险、attempt count、branch complexity；
- 全部模型分支失败时使用明确标记的 baseline fallback，保证尽量产出最终结果，而不是伪装成 beam 成功。

GT 仅在运行结束后计算 final-beam oracle rank，用于评估无 GT selector 的 regret，不参与搜索。

## 4. Pilot freeze 的含义与降级

Pilot freeze 的目的不是设置硬通过门槛，而是避免 formal/held-out 泄漏：Detector 模型、risk threshold、repairability threshold、safe-boundary evidence threshold、safe-risk ceiling、decoder 和 E8 selector 必须在正式评测之前固定。

Safe-boundary joint calibration 会使用最终选中的 rule/logistic/stump active risk 重新计算 boundary evidence，避免直接复用 pilot item 中按 rule risk 生成的旧 evidence 而混用分数尺度；证据阈值必须大于 0，风险门控产生的 0 分不能因阈值取 0 而重新进入 planner。

当前冻结器为 best-effort：

- 正常证据充分：`normal_pilot_freeze`；
- 有成功证据但 item/phase/切分不完整：`degraded_best_effort_freeze`；
- 缺乏可用曲线或 decoder 指标：按预先定义默认值生成 `default_fallback_freeze`。

所有等级均允许 formal 继续，并在 `selection_effectiveness` 中保存 warning、成功/失败 item 数、label 数和 split 状态。这样优先得到最终结果，但报告必须降低结论强度，不能把 fallback 冻结写成充分调参证据。

后续实现补全见 `08_FORMAL_FROZEN_DECODER_AND_PILOT_LEAKAGE_FIXES_20260731.md`：pilot 明确排除 test，冻结 decoder 已进入 formal 每窗提交与 cursor 链路。

## 5. 其他修复

- E4-C 只处理完整 96-unit group，尾部不足 96 不进入主对照；
- decoder 选择 tie-break 加入 negative/zero/overlap/regression/invalid 等结构错误；
- macro/micro 指标按每个 metric 自己的有效样本和权重计算；某项全为 `None` 时返回 `null`，不抛 `StatisticsError`；
- E8 候选选择改为固定 lexicographic Detector policy，不再使用无验证的手工加权 anomaly scalar；
- safe、repairable、dynamic-boundary 阈值分别冻结，不再让一个阈值承担所有语义。

## 6. 有意未改

Resume/request cache 不新增 checkpoint/audio/lyrics/code 内容哈希强校验。继续遵循：修改算法语义、歌词、模型快照或实现后使用全新 `OUT_ROOT`；不要在旧输出目录上混跑。

## 7. 验证边界

本地完成：编译、shell 语法、E5/E8/E9 回归、冻结降级、极端指标、完整 96 group 与其余可收集 CPU 测试。

本地未完成：真实 Qwen/R2 GPU 前向、真实单 Demo E8 continuation、E9 多 hypothesis 的速度/显存/效果、全量 formal 数值。必须由服务器 smoke/pilot/formal 产物确认。
