# Codex Handoff — Unit-level Realign / Sparse Overnight Exploration

## 1. 任务

请将本 session 合并到当前 LyricAlignment 工作目录后，**不要直接开始大规模实验**。先 review 当前 `realign_gate` / detector / slot alignment / Test Demo 实现，并给出一份可执行的具体实现方案，再把该方案交给 OpenCode/agent 实现与运行。

本轮用户准备挂机，允许 overnight 8–12h 级实验。因此实施方案要同时支持：

- 正确性优先；
- cache/resume；
- 自动补样；
- 自适应 request-family screening → expansion；
- agent 在预定义信号不足时继续探索，不要跑完一个小表就停止。

---

## 2. 在拟定实现方案前必须先核实的当前实现

### 2.1 Unit pairing / metric schema

确认当前 GT pair metrics 是否能稳定得到：

- onset/offset/max-boundary before/after；
- unit identity 跨 request family 一致；
- missing/extra；
- detector original/after score。

若当前 schema 只支持 candidate-level harm，需要先设计 unit outcome schema v2。

### 2.2 Detector region builder

确认能否从真实 production detector output 生成 contiguous unsafe unit spans，并切到 1–8 unit local region。

禁止 Test Demo 再出现 target_unit_ids 覆盖整首。

### 2.3 Slot / sparse capability

重点查当前项目已有：

- full-slot alignment；
- sparse-slot；
- fixed slot / active slot；
- timeline slot constraint；
- request text 与 slot mask 的接口。

判断能否实现真正 `R-S_sparse`：

> only suspicious units active, stable units fixed/reference.

如果已有接口，优先复用；如果没有，设计最小可验证实现。

禁止用“删除 safe 文本，只送 active 文本”伪造 sparse。

### 2.4 R-B / one-sided anchors

核查：

- bilateral anchor search；
- anchor confidence/state；
- request identity；
- no-op detection；
- left-only / right-only 是否已有可复用机制。

### 2.5 Oracle direct

核查如何在严格 GT-firewall 下构造 R-O，只允许进入 evaluation-only branch。

### 2.6 Test Demo

核查当前为什么 4 个 R-U request target 是整首 unit list；定位 region-selection/serialization bug，并在实现方案中明确修复位置。

同时核对 inventory 36 vs stress stage 33/3 failed 的原因。

---

## 3. 需要 Codex 给出的具体实现方案内容

实现方案必须明确到：

- 修改/新增哪些模块、类、函数；
- 每个 request family 如何构造；
- unit outcome schema；
- no-GT feature schema；
- sparse 的真实语义；
- cache key；
- resume；
- case sampling / auto supplementation；
- screening / expansion 控制器；
- Test Demo local pipeline；
- CLI；
- tests；
- smoke 命令；
- overnight formal 命令；
- failure recovery；
- artifact 路径与 provenance。

不要只给高层 todo。

---

## 4. 建议实现模块

名称可调整，但职责应分离。

### A. `unit_outcome.py`

- pair original/candidate units；
- 计算 100/200/500/1000ms bucket；
- transition labels；
- target/context role；
- candidate summary 由 unit 聚合。

### B. `region_sampling.py`

- RS/US/AS/BR/BG/BA population；
- contiguous 1–8 unit region；
- per-song cap；
- adaptive refill；
- exhaustion audit。

### C. `request_families.py`

统一实现：

- R-U1；
- R-U3；
- R-S；
- R-A；
- R-B；
- R-L；
- R-R；
- R-O；
- R-NULL explicit control。

所有 request 返回结构化 provenance，包括 text span、audio span、active/fixed slots、anchors、forward identity。

### D. `intervention_check.py`

fail-fast：

- claimed active family 但 request identity==baseline → FAIL/NULL；
- R-B missing bilateral anchor → 不得标 R-B；
- R-S 没 active/fixed slot 差异 → FAIL；
- R-U target 覆盖整首/明显超 local cap → FAIL；
- R-O 被送入 no-GT feature → FAIL。

### E. `unit_gate_features.py`

- signed detector delta；
- temporal displacement；
- context protection；
- local structural feature；
- consensus feature。

feature 表禁止 GT/error-derived 字段。

### F. `consensus.py`

按 `(song, region, canonical_unit)` 聚合不同 family：

- median/MAD；
- cluster；
- agreement ratio；
- coverage/order/duration agreement。

### G. `request_sensitivity.py`

Oracle/local request perturbation、fixed-point subset。

### H. `test_demo_local.py`

- dynamic discovery；
- real detector spans；
- local region selection；
- real production family forwards；
- cross-language summary/ranking。

---

## 5. Screening → Expansion 的自动控制

不要把 200–300 regions × 全 family 写死成笛卡尔积。

### Screening

40–60 regions，机制型 family 全/多数覆盖。

生成 screening report：

- valid intervention coverage；
- safe preservation；
- catastrophic harm；
- recovery；
- sparse correctness；
- runtime。

### Family selection

Codex 方案需定义明确但不僵硬的淘汰逻辑。

允许 agent 根据结果保留 3–4 个 production-capable family进入 expansion。

### Expansion

自适应补到约 200–300 regions；

- RS / AS / BR 为重点；
- 跨 song；
- cache hit 优先；
- 请求不可构造时自动补抽。

不要因为某一 family coverage 低就停整个 run。

---

## 6. 对 no-GT signal 探索的要求

预定义信号：

- signed detector change；
- per-unit displacement；
- context protection；
- structural sanity；
- multi-request consensus；
- fixed-point；
- request sensitivity。

如果这些都弱，agent 必须继续探索已有模型输出中合理的 no-GT 信号，例如：

- hidden/posterior stability；
- raw/official disagreement；
- anchor confidence/asymmetry；
- local score gradient；
- request-size sensitivity；
- candidate ranking feature。

但必须遵守：

- GT 不得进入 feature；
- 每个漂亮 signal 都做 shortcut audit；
- song holdout / leave-one-song-out；
- counterexamples；
- 不允许用同 candidate 的 unit rows伪造独立样本量。

若 agent 找到新信号，可自行追加小规模验证，不需等待用户交互。

---

## 7. Test Demo 是正式必做项

实现方案必须把 Test Demo 纳入 overnight formal，而不是 smoke 尾项。

必须做到：

1. 动态发现全部当前 Test Demo；
2. 全量真实 detector；
3. 从 detector unit spans 构造 local regions；
4. 约 40–60 个跨语言 local regions，或 exhaustion audit；
5. 真实 R-U / R-S / best-anchor / baseline family；
6. 输出 consensus/stability/collateral proxy；
7. 自动选 representative cases；
8. 若 visual pipeline 可复用，输出少量可检查图/视频索引。

Test Demo 无 GT，不得计算 accuracy/repair rate。

---

## 8. Tests / fail-fast 必须覆盖

至少新增回归测试：

- R-U 不得覆盖整首 target；
- R-S 必须真实 active/fixed sparse；
- R-B anchor 必须 non-null 且改变 request；
- R-L/R-R identity 正确；
- R-O GT firewall；
- unit bucket boundary 100/200/500/1000ms；
- candidate summary 不再由 any-harm 单一逻辑决定；
- RS/AS strata 构造；
- same candidate units 不作为独立 candidate AUROC rows；
- consensus 按 song/region/unit 聚合；
- no-GT feature schema 禁止 GT/error 字段；
- Test Demo whole-item pseudo-local request fail-fast；
- cache identity 不跨 family 碰撞；
- resume 不重复 forward。

---

## 9. 运行与归档要求

请在实现计划中给出：

### Smoke

- 每个 request family 至少 1 个有效 intervention；
- RS / AS / BR 各至少 1；
- Test Demo 至少 2 种语言；
- sparse correctness 可人工读取 manifest 验证。

### Formal overnight

应可一条命令在独立终端长期运行；支持日志文件、resume、cache。

用户下一步会把 Codex 的实现方案交给 agent/OpenCode。请不要要求用户守在终端人工补样。

### 归档

最终 session 至少保存：

- population / sample accounting；
- requests manifest；
- unit GT outcomes；
- no-GT unit features；
- candidate summaries；
- request-family coverage；
- gate/consensus analysis；
- request sensitivity；
- Test Demo summary；
- exhaustion audit；
- runtime / cache / failures；
- final report；
- negative results / counterexamples。

---

## 10. Codex 在交给 agent 前必须回答的问题

1. 当前 sparse/slot 接口究竟能否实现真正 active-unit realign？具体怎么做？
2. R-U Test Demo 为什么会退化成整首 target？在哪个函数修？
3. Unit-level outcome 和 feature schema 如何定义，怎样保证 GT firewall？
4. R-B / R-L / R-R 的 request identity 如何验证是真 intervention？
5. Screening 后如何自动选择 surviving family，而不是硬编码笛卡尔积？
6. 200–300 region population 如何自动补样并控制跨歌公平性？
7. Test Demo 40–60 local region 如何真实构造并跨语言覆盖？
8. overnight 运行如何 cache/resume/failure recovery？
9. 哪些现有 artifact 可直接复用，哪些因为旧 candidate-level 语义必须重算？
10. 如果没有找到可靠 no-GT gate，agent 下一步自动探索哪些信号，什么时候才允许停止？

只有这些问题形成具体实现方案后，再交给 OpenCode/agent 实现和执行。

