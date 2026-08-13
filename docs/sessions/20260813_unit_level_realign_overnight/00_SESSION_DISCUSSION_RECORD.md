# 会话记录：Realign Gate review → Unit-level / Sparse Overnight Exploration

日期：2026-08-13

本文件记录当前阶段从 `detector_realign_gate_evidence` review、P0/P1 修正讨论、最新 `LyricAlignment_realign_gate_20260813_delivery` review，到下一轮 overnight 计划冻结的完整过程。用户意见与疑问尽量保留原意和原话，不将后续解释反向写成用户原始观点。

---

## 1. 用户要求 review 当前工作

用户请求：

> “进行review”

对 `detector_realign_gate_evidence.tar.gz` 的 review 确认：

- P0 production detector population 已基本从旧 E5 proposal contamination 中剥离；
- 40 个唯一 baseline windows、13 songs、4093 detector units；unit-level ACCEPT≈85.1%；
- 旧 15.5% safe accept / 97%+ trigger 的一部分来源是旧 proposal population 错误；
- 但 `any reject unit -> whole window unsafe` 的 39/40=97.5% 在修复后的 40 个真实 production windows 中依然成立，因此该值本身更多反映聚合规则，不等价于 detector unit 级表现；
- P1 whole-window strata 导致 S2 hard-negative 严重不足；已有数据里其实存在大量 `GT<=200ms` 且 detector REJECT/UNCERTAIN 的 unit；
- 当时的 R-B 实际为 null/no-op：没有真实 anchors、request 与 baseline 一致、GT delta 全 0；
- `n_big AUROC` 被 no-op easy negatives 和 candidate/unit 统计问题美化；
- `delta_error_ms -> harm` 的 AUROC=1 是 GT leakage，不能用于 writeback gate；
- Test Demo 只有 discovery 有效，真实行为尚未完成。

核心 review 结论：

> P0 基本修正成功，但 P1 必须改到 interval/unit-region；P3 仍未通过；Realign Gate 仍是必要问题。

---

## 2. 用户要求给 OpenCode/Codex 的 P0/P1 修正 prompt

用户说明：

> “当前正在要求opencode寻找之前artifact对应的行为设置并排查原因。现在给出所有需要纠正的P0P1问题的prompt。”

随后形成了 P0/P1 修正要求，主要包括：

- 继续追溯历史 detector artifact、threshold、feature/schema、raw/official 输入与 metric 定义；
- 禁止为了复现 80% safe accept 而调 threshold；
- 重建唯一 `production_raw_baseline` population；
- P1 只能从 original baseline + GT 构造；
- correctness 主口径向 200ms 对齐；
- S1/S2/S3/S4 必须重新构造；
- “样本不足”需主动补救，不能直接放过；
- Test Demo mock 不得进入结论。

---

## 3. 修复后再次 review：P0 已恢复，但 P1/P3 仍有问题

随后新的 evidence review 得到：

### P0

- 13 songs / 40 unique production windows / 4093 detector units；
- ACCEPT≈85.07%、UNCERTAIN≈0.54%、REJECT≈14.39%；
- 与 frozen validation 的 safe-accept≈86.89% 输出比例接近；
- 旧 15.5% 可以明确归因到 proposal-bank contamination + cross-variant conservative merge。

同时确认：

- 39/40 whole windows unsafe（97.5%）仍存在；
- 原因是当前 window 规则为 any REJECT → whole-window unsafe；
- 因而 97.5% 不应作为 detector quality KPI，也不应直接变成“整窗 realign”。

### P1 / realign

- 表面有 R-A/R-B 成对执行；
- 但旧 R-B 实际是 null re-run；
- P1 仍主要是 whole-window strata，导致 S2 数量过少；
- unit-level join 显示 GT-safe 但 detector REJECT/UNCERTAIN 的 unit 实际很多。

### Gate

- `n_big` 更像“改动规模/不稳定性”而不是“改动方向”；
- `delta_error_ms` 作为 feature 的 gate 结论无效；
- candidate-level harm 定义过粗。

### Test Demo

- 真实模型调用还没有形成真正的 local realign 行为。

---

## 4. 用户提出第一轮 realign request / gate / Test Demo 修订要求

用户原话：

> “1. 我觉得可以要求它尝试多种realign的请求方式，或者是切出更接近unit级别的realign请求。，97.5%窗口报警这个数据没有太大实际意义。  
> 2. 在上面的更换realign请求的基础上，测试RARB实际效果，并且真实地运行RB。  
> 3. n big看起来不够好，还有什么其他信号比较好吗？没有的话继续要求尝试其他信号。  
> 4. 好像还是没有看到test demo数据  
> 5. 没有足够样本之类的问题，不应该直接放过，要要求agent发挥自己的能力去修正。  
>  
> 给出提供给codex的patch，codex拟定实现方案后我会交给agent实现、。”

据此冻结：

- request 粒度从 whole-window/粗 region 迁移到 unit/interval；
- 97.5% whole-window unsafe 降级为聚合现象；
- 真 R-B 必须有真实 anchors 与真实 request change；
- `n_big` 降级，主动探索其他 no-GT 信号；
- Test Demo 必须真实执行；
- insufficient sample 必须主动修复。

随后生成了 revision patch，交给 Codex 先制定实现方案。

---

## 5. 最新 delivery 后，用户准备挂机，要求讨论更耗时探索

用户上传：`LyricAlignment_realign_gate_20260813_delivery.zip`

用户原话：

> “目前看来realign本身好像还挺不可靠的。我接下来要挂机，可以多做些耗时的探索工作。讨论下一步实验计划”

对 delivery 的初步审阅确认：

- 当前正式 region run 为 60 cases，记录为 S2=21、S3=39；
- 105 个 active R-U/R-A/R-B candidates 完成 forward；
- 其中约 35 个 region 得到三联 active candidates，另有大量 region 由于 bilateral anchors 不足无法构造真 R-B；
- 当前 Test Demo stage 虽然调用 real executor，但只实际 forward 4 个 request；
- Test Demo 里的所谓 `R-U_unit_local` 仍把整个 item 的 unit id（如 0..285、0..476 等）作为 target，实际上不是 local unit request；
- 4 个 context request 均因缺 bilateral anchors 成为 `R-NULL`；
- 当前 candidate harm 定义过粗：只要 candidate 中任意 target unit 恶化 >=200ms，就把 candidate 整体归 harm；
- 当前 region strata 没有 S1 correct+accept control；
- 因而 delivery 中 79%+ candidate harm、`n_big`/displacement 的高 AUROC 都需要更细评价后重新解释。

讨论后提出：

- 系统研究 realign request basin / stability；
- 多 request family consensus；
- signed/locality gate feature；
- fixed-point / boundary sensitivity；
- Test Demo 真正 local 化；
- overnight 可扩大 region 和 forward 数。

---

## 6. 用户进一步要求把评价下沉到 unit-level，并新增 Sparse 等 request

用户原话：

> “嗯，之前评价我觉得可能应该修改成更接近unit级。这些feature也需要重算。另外我还是好奇realign对于reject safe的影响。对realign的评价也应该更加细分。你的实验方案中存在了anchor（stable）、left/right、direct（oracle）几种，也可以考虑sparse之类的？可以进行初期尝试不用笛卡尔积。当前regions跑overnight的话，还可以进一步扩大。我感觉forward还是比较快的。”

对此达成以下决定：

1. **主评价单位改为 unit**。candidate/region 仍保留，但主要用于请求上下文与汇总，不再用一个 candidate label 覆盖几十个 unit 的行为。
2. 现有 gate feature 必须重算到 unit-level，并保留方向信息；`n_big` 只作为 candidate change-magnitude summary。
3. 新增 **Reject-Safe** 主实验：GT 实际正确（核心阈值 <=200ms）但 detector REJECT/UNCERTAIN 的 unit/小 region，研究 realign 是否把“碰巧正确但模型不自信”的内容打坏。
4. 增加 **Accept-Safe control**，与 Reject-Safe 做公平比较。
5. realign 评价至少拆为：recovery ability、preservation ability、collateral damage、catastrophic damage、selectivity/locality。
6. request family 增加：
   - unit-local contiguous；
   - detector interval direct；
   - genuine bilateral stable-anchor；
   - left-anchor / right-anchor；
   - direct oracle diagnostic；
   - **sparse / slot-local**。
7. Sparse 必须是真 sparse：只激活可疑 unit/slot，稳定 unit 保持 fixed/reference；不能通过删掉 safe text 伪造成 sparse。
8. 初期 screening 不做笛卡尔积；先少量 case 比较机制明显不同的 family，淘汰无效路线后再扩大。
9. overnight 的正式 region 可从当前 60 明显扩大到约 **200–300 个独立 GT regions**，在 forward 较快的情况下优先增加独立样本与跨歌覆盖，而不是不断细调同一批 60 个 region。
10. 多 request consensus 进一步下沉到 unit：如果多个不同 request 对同一 unit 收敛到相近时间，可以成为 unit-level writeback confidence；若 request 稍变就跳到不同位置，则应视为不稳定。
11. Test Demo 必须从真实 detector 连续 unsafe unit span 构造 local/sparse request，禁止再次出现“R-U target 实际覆盖整首”的情况。

---

## 7. 本 session 的最终冻结方向

下一轮不以“R-B 是否胜过 R-A”作为唯一目标，而是研究：

> **什么 detector/GT 状态的 unit，在什么 request mechanism 下能够被修复、被保持或被破坏；realign 的多视角输出是否能在无 GT 条件下形成可信的新 unit 时间。**

实验分两层：

- **Screening 层**：40–60 regions，少量机制型 request family，快速淘汰明显 no-op/高 harm/无 recovery 的路线；
- **Overnight expansion 层**：保留 3–4 个 production-capable family，自适应扩展到约 200–300 regions；Oracle / fixed-point / perturbation 仅在 subset 运行。

最终不是只给一个 candidate repair rate，而是必须给：

- unit 状态转移矩阵；
- Reject-Safe vs Accept-Safe preservation；
- bad-unit recovery；
- collateral/catastrophic harm；
- request-family coverage / intervention validity；
- unit-level no-GT feature 与 consensus；
- Test Demo 多语言真实 local behavior。

