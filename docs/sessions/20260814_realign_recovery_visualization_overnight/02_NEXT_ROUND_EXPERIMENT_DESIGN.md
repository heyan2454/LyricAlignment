# 下一轮实验设计：困难区 Recovery Dynamics、细粒度拆分、Observation 改写与组合恢复

## 0. 总目标

本轮不再问一个过于宽泛的问题——“realign 平均有没有收益”。要回答的是：

> **什么类型的困难区，在什么 problem formulation 下能够从错误 basin 中被拉回；如果能拉回，是靠重复迭代、拆小、改变 audio observation、增加约束/线索，还是 coarse→fine 组合？**

同时保留系统级问题：

> **当前 full-slot baseline 是否在真实 Demo 上确实超过旧 pre-slot B4？**

可视化是正式实验的一部分，详细合同见 `03_VISUALIZATION_DESIGN_AND_ACCEPTANCE.md`。

---

# E0. Phase 0：冻结输入、口径、cache 与运行身份

## 原因

上一轮出现过不同 aggregate denominator、旧 adapter R-B、旧可视化 schema 等问题。若不先冻结，会把“方法变化”和“口径变化”混在一起。

## 目的

建立下一轮所有实验共享的：

- exact current baseline resolved config；
- historical B4 resolved config；
- unit-realign request schema/version；
- evaluator schema；
- no-GT / GT firewall；
- model/checkpoint/audio SHA/request identity；
- shared content-addressed forward cache；
- rerender-only presentation identity。

## 设计

1. 从当前工作目录实际代码解析 **Current baseline**，不能仅凭文档猜；输出 resolved config + hash；
2. B4 使用 `b4-60-silence-official-shadow-v1` 的 pre-slot/non-slot 语义，必须核实当前 runner 是否真正复现历史行为；
3. R-U 默认先冻结 `audio_margin_sec=0.5, context_neighbors=1, target=1–3 contiguous units`；
4. R-S 保持 full local window + active target slots + fixed context slots；
5. 所有新 family/iteration 把“上一轮 candidate、crop、iteration index、split identity”纳入 request identity；
6. no-GT runner 不得收到 GT path；GT 只在 `evaluate_*` 后 join；
7. 运行时 `actual_writeback=0`，迭代 chain 只在 isolated research state 中模拟 candidate-as-next-input，不改变 production baseline artifact。

## 预期结果

- 所有 run 可 resume；
- 相同 request 命中 cache，不重复 forward；
- 改了 crop/iteration/split 必须生成新 identity；
- presentation rerender 不改变 scientific artifact hash。

## 结果能说明什么

- 若 E0 不能通过，后续结果不允许用于方法比较；
- E0 通过只说明实验可复现，不说明模型能力。

---

# E1. Multi-Realign Dynamics：多次 realign 能否逐步纠回？

## 原因

上一轮 fixed-point 证明“第二次几乎不动”在部分 request 上成立，但没有系统比较：

- candidate 真正写入 isolated state 后继续；
- 每轮重新 crop；
- 每轮改变 observation。

用户明确提出要研究“多次 realign 能否纠回”。

## 目的

区分四类困难区：

1. 一次即可恢复；
2. 多次迭代逐步恢复；
3. 第一轮改善后停在错误 fixed point；
4. 越修越坏/振荡。

## 样本

先从有 GT 的 M4/真实 GT pool 中构造 hard cohort，至少覆盖：

- baseline >200ms、>500ms、>1s、>2s；
- 上轮 outcome = recovery / harmful / mixed / catastrophic；
- region 长度 1–3 与更长困难 span；
- 开头、窗口边界、静音附近、重复歌词/疑似多解、serial drift 等类型。

Screening 先用约 40–60 独立 regions；只对显示机制差异的 branch 扩到 >=200 regions。歌曲需分散，避免只在少数歌上重复。

## 设计

### E1-A. Direct chain

同一 request formulation，candidate 作为下一轮 isolated baseline：

```text
iteration = 1, 2, 3, 5
```

记录每个 target/unit 的完整轨迹。

### E1-B. Re-crop chain

每轮根据上一轮 target proposal 重新构造 audio crop，再 align。文本 target identity 不变，crop identity 变化。

建议 screening 只用少量规则，例如：

- recenter around latest candidate；
- 左右各增加固定 margin；
- 保持 target span 不变。

### E1-C. Perturb-and-retry

不是完整网格，只预注册 3–5 个差异明显的 audio views，例如：

- base crop；
- left boundary earlier；
- left boundary later/recenter；
- wider crop；
- narrower/local crop（若不破坏 target coverage）。

每个 view 产生 candidate；selection 不得用 GT。

## 指标

逐 unit：

- initial error；
- error@iter1/2/3/5；
- best error；
- first hit 100/200/500/1000ms iteration；
- monotonic improvement ratio；
- improve-then-regress；
- fixed-point iteration；
- oscillation / divergence；
- target displacement；
- fixed-context displacement/collateral harm。

逐 region：

- all-target recovered；
- >=75% target recovered；
- any catastrophic regression；
- forward count / wall time。

## 预期结果与解释

### 结果 A：Direct chain 明显继续改善

说明模型并非一次就到 fixed point，多次 realign 本身有价值；下一轮可研究 no-GT stop rule。

### 结果 B：Direct chain 很快停止，但 re-crop/perturb 能继续改善

说明核心问题是 **observation/reference frame**，不是“迭代次数”；应转向 recrop/multi-view。

### 结果 C：所有 chain 都稳定在错误处

支持“当前 aligner 对这类困难区不存在可达 recovery basin”，需要 coarse localization/不同模型/不同任务。

### 结果 D：多次迭代平均改善但 collateral harm 增加

说明不能用 iteration count 直接换 accuracy，需要后续 bounded/sparse refinement 与安全 gate。

---

# E2. Fine-Grained Split：困难 region 拆小是否扩大 recovery basin？

## 原因

当前 region 可能把“真正错误的 1–2 个 unit”和周围正确 unit 绑在一起。整段重新对齐可能让模型承担不必要的全局分配问题，也可能破坏 context。

用户明确提出“将难段分成更细粒度分开”。

## 目的

验证失败到底来自模型本体，还是 region formulation 太粗。

## Screening 设计（避免笛卡尔积）

先比较四种具有明显机制差异的 partition：

1. **1-unit** target；
2. **2-unit** contiguous target；
3. **adaptive detector span**：按连续 REJECT/UNCERTAIN + safe gap 切；
4. **anchor/gap split**：遇稳定 ACCEPT anchor、长静音或明显时间 gap 分开。

4-unit 只在 1/2-unit 过碎或 adaptive 需要时补，不与所有路线全交叉。

### 方向性子实验

对同一拆分方案仅在 hard subset 测：

- left→right serial repair；
- right→left；
- independent repair + deterministic merge。

## 特别关注 catastrophic

上一轮 oracle catastrophic 0/15。下一轮必须优先让这些/同类 case 进入 split 研究：

> 如果 catastrophic 在整段不可救，但 1/2-unit 可救，说明失败主要来自 problem granularity，而非纯模型能力。

## 指标

- strict 100/200ms recovery；
- 500/1000ms coarse recovery；
- context preservation；
- split boundary harm；
- merge collision / overlap / non-monotonic；
- recovered unit fraction；
- region all-hit / >=75%-hit；
- extra forward cost。

## 预期结果与解释

- **小粒度显著提升**：后续 realign 默认应以 local subregion 为单位，而非整困难 span；
- **只有 adaptive/anchor split 提升**：说明语义/稳定边界比固定 unit 数更重要；
- **方向性显著**：说明 serial state/cursor 的方向是恢复机制组成；
- **拆多小都无效**：增强“basin 不可达/需 coarse localization 或其他模型”的结论。

---

# E3. Observation / Context Study：改变 audio observation 与补齐 k1 vs k3

## 原因

上一轮 perturbation 中少量 text context 改动几乎无响应，而 audio-left 在个别 case 能触发秒级变化。与此同时 `context k=1 vs k=3` 只有 request，未完成 forward。

## 目的

判断哪种上下文真正能把模型从错误 basin 中拉出来。

## E3-A. 补齐 k1 vs k3

直接复用现有 `09_context_k1_vs_k3/REQUESTS_k1.jsonl` 与 `REQUESTS_k3.jsonl` 的设计意图，但必须：

- 核实 request identity 与当前 builder 一致；
- 如代码/schema 已变，重新 materialize，不静默复用；
- 完成 forward、unit evaluator、paired song-level comparison。

这是低成本 closure，不作为主矩阵扩张。

## E3-B. Audio recrop / multi-scale

Screening 预注册少量 views：

- base ±0.5s local；
- wider local crop；
- left-context enriched crop；
- recentered crop around R-U proposal。

具体秒数由 Codex 根据当前音频/region duration 设计，但不得形成 margin×context×split 的大网格。

## E3-C. Stable anchors as observation constraints

只在真实 anchor 可用 subset 比较：

- no anchor local；
- genuine bilateral anchor；
- one-sided left/right anchor（若当前接口需要实现，先做小 pilot）。

## 指标与解释

- 若 audio view 明显强于 text k1/k3：优先把下一阶段资源放到 audio observation；
- 若 anchor 只保护 context、不提升 target：把它作为 refinement/safety 机制而非 recovery 主机制；
- 若 one-sided 对 serial/start-error 更有效：说明强制 bilateral 约束过于保守。

---

# E4. Coarse -> Fine 组合：R-U Proposal -> Re-crop -> Sparse/Fixed Refinement

## 原因

当前证据显示：

- R-U target recovery 更强；
- R-S context protection 更强；
- 两者直接二选一无法同时得到 target 与 safety。

用户同意把它作为当前四路消融的第四路候选。

## 目的

验证“自由度用于定位，约束用于精修/写回保护”的组合是否成立。

## 设计

Stage A：

- 对 target 执行 R-U；
- 输出 coarse proposal；
- **不直接写回 production baseline**。

Stage B：

- 以 proposal 为中心重新构造 local audio crop；
- 保留可信 context/fixed slots；
- 只允许 target/必要邻域 active；
- 使用 sparse/fixed refinement；
- 若 proposal 与固定 context 产生不合法几何，fail closed / not_constructible。

比较四路：

1. baseline；
2. R-U；
3. R-S；
4. R-U->refinement。

## 指标

- target 100/200/500/1000ms；
- fixed context displacement；
- catastrophic regression；
- constructibility/coverage；
- forward cost；
- no-GT safety signals；
- Test Demo objective structural regressions。

## 预期结果与解释

- **组合 target≈R-U 且 context≈R-S**：这是最有希望的下一代 recovery mechanism；
- **组合退化到 R-S**：fixed constraints 限制了 recovery，自由 proposal 没有真正传递到精修；
- **组合仍破坏 context**：re-crop/remerge contract 有问题或 proposal 太不稳定；
- **组合只对某类 case 有效**：进入 conditional routing，而不是全局启用。

---

# E5. 真实 no-GT 线索：候选选择与 stop/safety gate

## 原因

上一轮 timing-only `p_bad` proxy 失败，但不能据此否定真正 detector/model signal。

## 目的

在不读取 GT 的前提下，研究是否能选择 multi-view / multi-iteration candidate，或至少安全地拒绝明显坏 candidate。

## 候选信号（按可获得性分层）

优先接真实已有信号：

- raw/official disagreement；
- raw/official per-unit timing/sequence evidence；
- hidden/posterior-derived confidence；
- entropy/margin（若当前模型接口可稳定导出）；
- detector tri-state / score；
- context displacement（safety）；
- fixed-point / multi-view spread（stability only）。

禁止把 GT delta、GT label 或 evaluator-only字段进入 runner/ranker。

## 设计

- 先 CPU/offline 用已缓存 candidate 做特征可用性审计；
- 再在 validation/discovery split 冻结简单 selector/rules；
- heldout 只做一次评价；
- 不因为一个标量无法同时做到高 recovery + 低 harm 就停止，应分别报告 recovery-first 与 safety-first operating point。

## 结论边界

- 高 AUROC 但来自 GT leakage：无效；
- 只区分 collateral harm：只能做 safety gate；
- 能在 heldout 提高 strict recovery 且控制 harm：才支持 candidate selection。

---

# E6. Recovery-Basin Atlas + Hard-Case Mining（挂机持续任务）

## 原因

当前 40–100 region 规模只能看到机制线索。用户挂机，希望有任务可以持续扩展，而且不局限当前一条路线。

## 目的

形成可复用的困难区分类和 recovery capability map。

## 自动采样来源

- M4Singer real GT；
- MIR-1K fixed-transfer（若 GT 口径可用则 evaluator-only join）；
- 全量自动发现 Test Demo（no-GT mining）；
- serial accumulated-error episodes；
- 开头/窗口边界；
- 重复歌词/多 occurrence；
- 长静音/弱人声；
- high raw-official disagreement；
- 多次 realign 分歧大；
- catastrophic / mixed；
- detector safe-reject / bad-accept。

## Atlas 字段

每个 region/unit 至少保存：

- baseline error bucket（仅 evaluator side）；
- detector state；
- region length；
- song/language/domain；
- start/boundary/silence/repetition flags；
- request family；
- split/iteration/audio-view identity；
- best achievable 100/200/500/1000ms；
- context harm；
- forward cost；
- whether oracle/split/recrop/iterative/combined can rescue。

## 最终分类目标

至少区分：

1. once-realign recoverable；
2. iterative recoverable；
3. split-only recoverable；
4. recrop/multi-view recoverable；
5. coarse->fine recoverable；
6. oracle/local mechanisms still unrecoverable。

这张 atlas 比继续给一个全局平均 recovery rate 更有研究价值。

---

# E7. Serial accumulated-error stress test（并行长期方向）

## 原因

孤立 region recovery 不等于真实产品串行恢复。此前已经发现前窗 cursor/prefix 错误会自然传到后窗。

## 目的

验证 recovery 是否真正阻断错误传播，而不是只修单个 local timestamp。

## 设计

构造/收集自然或受控的 serial episode：

```text
前窗轻微错误
-> commit/provisional state
-> 下一窗错误 cursor/query
-> detector
-> recovery strategy
-> 后续至少 2–3 windows
```

比较 baseline / selected recovery family / combo；仍不允许 GT reset。

重点指标：

- downstream error area / duration；
- cursor recovery latency；
- windows-to-recover；
- cumulative bad units；
- extra forwards/wall time；
- false recovery on originally safe windows。

如果 local GT 指标改善但 serial downstream 不改善，则不能作为产品 recovery success。

---

# E8. 可视化实验

可视化不是最后随便画图，而是两个明确实验：

1. **B4 vs Current baseline 双路 system-level A/B**；
2. **Current baseline / R-U / R-S / R-U->refinement 四路机制消融**。

完整实现、顺序、画面和验收要求见 `03_VISUALIZATION_DESIGN_AND_ACCEPTANCE.md`。

---

# E9. 运行顺序与自适应扩量

建议顺序：

```text
E0 freeze / smoke
-> E8 visualization adapter + Side by Side smoke
-> E1 multi-realign screening
-> E2 fine split screening
-> E3 recrop + k1/k3 closure
-> E4 coarse->fine pilot
-> 根据 strict recovery + safety 选择 1–2 个方向扩量
-> E5 no-GT selector/safety
-> E6/E7 long-running atlas + serial stress
-> Test Demo 批量视频与客观统计
-> free exploration loop
```

不要求某一方向 positive 才继续。Negative result 本身应写入 atlas，并触发下一种机制。

---

# E10. 本轮希望最终回答的问题

1. 相同 formulation 的多次 realign 是否真的逐步纠回，还是快速进入错误 fixed point？
2. re-crop / audio multi-view 是否比纯重复更有效？
3. 困难区拆成 1/2-unit 或 adaptive span 是否扩大 recovery basin？
4. catastrophic 是否有一部分在拆小后可救？
5. R-U proposal -> sparse/fixed refinement 能否同时接近 R-U target recovery 和 R-S context safety？
6. 是否存在真实 no-GT 信号能选择 candidate 或判断停止？
7. 哪些 case 即使 oracle/split/recrop/multi-iteration 仍不可救？
8. 当前 baseline 在真实 Demo 上是否比旧 B4 更好？
9. realign 的局部改善能否转化为 serial downstream recovery？

若这些问题能被回答，即使最终结论是“某些困难区当前模型不可救”，本轮仍视为成功研究，而不是失败实验。
