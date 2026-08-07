# 主线 A：Transition → Propagation → Recovery 详细执行计划

## 1. 主线核心假设

当前最基础的不确定性不是 detector，而是 **transition policy 本身**：已有多种串行推进方式，且 non-serial 也可能成立。只有先比较这些策略，才知道传播 benchmark 和 recovery 应绑定在哪些系统上。

本主线的研究顺序：

```text
统一 Align/Window/Audio
→ 比较 Transition
→ 选 candidate
→ 构造/收集真实 carried-state error
→ 测 stability/recoverability
→ 测 oracle recovery 上限
→ 接入 detector 工作点
→ L/W closed-loop
```

---

## 2. Transition formal：控制变量

四种 T0–T3 必须尽可能共享：

- 同一 source songs；
- 同一 audio preprocessing；
- 同一 actual window plan；
- 同一 10+60+10 input；
- 同一 full-slot query content；
- 同一 model forward config；
- 同一 raw evidence；
- official 若用于执行，必须记录并在各 transition 保持一致。

唯一允许不同的是 **状态推进/提交规则**。

如果某个历史 transition 强制绑定不同 planner/decoder，必须额外报告这一事实；不能把“planner+decoder+transition 同时变化”的差异解释为 transition 因果收益。

---

## 3. T0–T3 最小行为合同

### T0 Independent / non-serial

- 不读取上一窗预测的 cursor/occurrence/timestamp 作为本窗必要状态；
- 不把前窗错误写入本窗状态；
- 若当前实现依赖 oracle text start，明确标为 oracle diagnostic；
- 其主要用途是隔离“模型单窗能力/上下文敏感性”与“状态反馈传播”。

### T1 Direct serial

- 使用上一窗实际最终 state 推进；
- 不做 detector/recovery；
- 只要当前 transition 定义允许 commit，就成为下一窗事实；
- 作为自然 propagation harvesting 的首选机制 candidate 之一。

### T2 Core+boundary serial

- core ownership 决定可永久推进范围；
- lookahead 只用于辅助，不自动永久拥有；
- boundary unit ownership 必须固定，不允许相邻窗重复/漏失 canonical id；
- next cursor 必须由提交边界唯一计算。

### T3 Stable-boundary serial

- 只提交从当前 cursor 开始的连续 stable region；
- stable boundary 后不永久写回；
- 下一窗重新观察该区域；
- 不需要额外存储复杂 provisional-tail，除非当前实现本来就有且行为已测试；
- 不允许越过 unresolved/unstable 区域推进 canonical cursor。

---

## 4. Transition 指标

### Accuracy / correctness

同时区分：

- frame/timestamp-level；
- unit-level；
- event/interval-level（若适用）；
- raw 与 official 输出。

不得把不同 metric schema 混在一个“accuracy”。

### Serial / state metrics

- first_error_window / first_error_unit；
- cursor error（units 与比例）；
- time drift；
- missing/duplicate committed canonical ids；
- occurrence jump rate；
- propagation probability；
- propagation depth；
- amplification slope；
- corrupted committed units；
- self-recovery rate；
- recovery latency。

### Cost

- model forward count；
- processed audio seconds；
- decoder-only wall time；
- end-to-end wall time；
- cache hit/miss；
- retry/extra forward（Recovery 阶段）。

---

## 5. Natural propagation harvesting

### 方法

对 T1/T2/T3（以及若可定义的产品 non-serial 不适用传播）运行无 detector baseline，利用 GT **事后**定位第一个真正错误 commit。

一旦发现：

1. 保存 error-before state；
2. 不进行 GT reset；
3. 继续 2–5 个后续窗口；
4. 保存每窗 state、raw/official、posterior summary、commit、cursor；
5. 自动分类是否恢复/维持/扩大/occurrence jump。

### 禁止

- 发现错误后用 GT 修正再称“自然恢复”；
- 只记录当前窗误差而不保存后续 carried state；
- 把 detector 拒绝掉、从未进入 commit 的 unsafe 记作 propagated error。

---

## 6. Model-native forced commit

当自然传播不足时，优先从同一真实 forward 的候选中选错误状态。

候选来源：

- raw 与 official 对同一 unit/区间出现显著差异；
- posterior top-2 时间峰中次峰形成合理连续路径；
- 重复歌词存在 alternate occurrence；
- 旧 detector 判高风险但模型输出本身合法、单调、非明显 artifact。

强制点只在“一次 commit decision”；之后 route 恢复正常。

必须记录：

- 候选是否模型原生；
- 强制的 state diff；
- GT 仅用于事后判定该候选确实错误；
- 下一窗是否真正受到影响。

---

## 7. Controlled canonical state corruption

为跨 Transition 做公平比较，定义 transition-agnostic corruption，再由各 transition adapter 转为自身 next-state 输入。

### Families

1. lyric cursor ahead/behind；
2. time cursor ahead/behind；
3. lyric+time coupled/self-consistent wrong state；
4. wrong occurrence；
5. partial boundary/tail corruption。

### 强度

不要一开始做巨大网格。首轮仅少/中/大三级，外加 time 的 ±1/±3/±6/±12 s 机制曲线。根据 pilot 的 unit density 将 cursor 级别冻结，同时同时报告绝对 units 和百分比。

### 目的

固定完全相同的初始错误 `Δstate`，比较不同 Transition：

`P(recover | Δstate, transition)`。

这比“某个 transition 上随机异常”的比较更能说明 state policy 天生抗错能力。

---

## 8. Repeated occurrence benchmark

优先真实重复歌词/副歌；必要时机械构造。

### Natural

自动寻找同歌重复 n-gram / chorus，保存每个 occurrence 的 canonical identity 和真实时间。

### Mechanical

若真实样本不足，使用类似：

`ABCD → ABCABD`

但必须同步复制：

- audio；
- lyrics；
- canonical GT；
- occurrence identity。

必须做 seam control，排除模型只检测拼接噪声。

### 指标

- correct occurrence rate；
- alternate occurrence rate；
- top-2 是否对应另一真实 occurrence；
- cross-window occurrence consistency；
- occurrence jump 后传播深度。

---

## 9. Stability basin / recoverability

对于每个 candidate Transition 输出：

- 初始 cursor/time error → propagation probability 曲线；
- 初始 error → recovery latency；
- 初始 error → catastrophic occurrence jump。

将 episode 分类：

- self_recover；
- slow_recover；
- persistent；
- amplifying；
- occurrence_jump。

重点比较：同等当前误差大小下，后续风险是否完全不同。若成立，说明 detector 不应只预测当前 correctness。

---

## 10. Oracle Recovery

### Oracle-W

GT 指出当前待提交区域含真实危险错误 → 整个待提交窗口/区域不写回，从冻结的稳定 retry point 重做。

### Oracle-L

GT 指出真实错误子区间 → 保留错误前连续正确 prefix，只重做 gap，禁止越过 gap commit。

### Oracle reset（可选）

仅当 L/W 仍无法恢复时，用于区分：

- cursor state 错；
- occurrence state 错；
- aligner 在正确 state 下本身仍失败。

Oracle 只用于上限，不能进入实际 detector 训练输入。

---

## 11. Detector-driven Recovery 闭环

只有 Detector 线冻结工作点后运行。

### L route

1. 从当前 cursor 开始扫描三态；
2. 连续 ACCEPT prefix 可以提交，但仍需满足 transition 自身合法性；
3. 第一个 REJECT/UNCERTAIN 开始 unresolved gap；
4. gap 后 ACCEPT 不能直接推进 cursor；
5. local retry 仅处理 gap 及有限上下文；
6. retry 后仍只提交从 cursor 开始的连续合法 region；
7. 每个 nominal window/gap 的 retry 数量必须冻结并有限。

### W route

1. 当前待提交区域有明确 REJECT → 该 decision 下零提交；
2. 回到冻结的稳定 retry point；
3. 重跑一次；
4. 仍失败则标 unresolved，不允许同一窗无限重试。

### Shadow

L/W 都可以先 shadow，但 shadow 不能改变真实 trajectory。

---

## 12. Closed-loop 最小组合

在 Product candidate：

- None；
- Shadow；
- L-SA60；
- L-SA80；
- L-R95；
- W-R95。

在 Mechanism candidate：

- None；
- 只选一个高提交点（优先 SA80）和一个高保护点（R95）做 L/W 机制验证。

禁止四 Transition 全部乘上全部 Detector/Recovery。
