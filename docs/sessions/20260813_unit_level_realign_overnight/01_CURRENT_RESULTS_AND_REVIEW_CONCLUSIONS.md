# 当前实验结果与 review 后结论

基线：`LyricAlignment_realign_gate_20260813_delivery.zip`

本文件区分：

- **当前 delivery 中确实执行/记录的事实**；
- **可以保留的结论**；
- **因为评价粒度或实现问题需要降级/重算的结果**；
- **下一轮需要验证的假设**。

---

## 1. P0 Detector：可保留结果

当前 formal summary 记录：

- real-GT songs：13；
- production baseline requests/windows：40；
- detector units：4093；
- ACCEPT：0.8507207；
- UNCERTAIN：0.0053750；
- REJECT：0.1439042；
- frozen validation bridge safe-accept：0.8688525；
- historical retrospective 83.2% / 95.67% 对应 source 仍未恢复，状态为 `not_reproduced_source_missing`。

因此可以保留：

> 当前 production-style detector **unit 状态比例**约 85% ACCEPT，与可复现 frozen validation 的 86.9% 接近；旧 15.5% ACCEPT 主要来自错误 proposal population / cross-variant contamination，而不是 detector 本身突然退化。

注意：85% 是状态比例，不是 GT accuracy。

---

## 2. 97.5% whole-window unsafe：不再作为主要实验结论

当前 40 个 windows：

- unsafe windows：39；
- any-reject trigger：97.5%；
- unsafe intervals total：237。

这个数字在修复后的 production population 中仍然真实存在，但它主要由：

> `任何一个 REJECT unit -> 整个 60s window unsafe`

这一聚合契约决定。

因此：

- 不再把 97.5% 当作 detector 生产质量 KPI；
- 不再用 whole-window unsafe 直接触发整窗 realign；
- detector→realign 接口必须下沉到 contiguous unsafe unit interval / local region。

---

## 3. 当前 Realign formal run：执行事实

当前 final summary 记录：

- region cases：60；
- request/candidates：105；
- 当前 strata 主要为 S2=21、S3=39；
- 当前 formal 不做 actual writeback；
- no-GT gate 输出保持 `DIAGNOSTIC_ONLY_NO_WRITEBACK`。

当前 delivery README 记录：

- 约 35 个 region 得到 R-U/R-A/R-B active candidates；
- 未构造的 case 主要与 bilateral safe anchor 不足有关。

这说明：

> 相比更早版本，本轮已经开始真实运行多 request candidate，且真实 GPU forward 本身不是明显瓶颈；因此 overnight 可以增加独立 region 数量。

---

## 4. 当前 candidate-level harm 不能作为 realign 最终评价

当前 gate summary 中 paired units：

- paired units：957；
- improve：67；
- harm：227；
- neutral：663；
- candidate holdout harm rate 约 0.786。

但现行 candidate harm 语义过于保守/粗糙：一个 candidate 内只要任一 target unit 恶化 >=200ms，就可能把整个 candidate 归为 harm。这会混合：

- target 大幅恢复 + 一个 unit 轻微恶化；
- target 完全没修 + collateral damage；
- 整段 catastrophic collapse；
- 大量 neutral + 一个边缘 200ms 越界。

因此这些 candidate harm rate 只保留为 diagnostic，不作为“realign 80% 不可靠”的精确定量结论。

下一轮必须以 unit 状态转移和 target/context 分离评价重算。

---

## 5. 当前 gate feature：必须按 unit-level 重算

当前 candidate-song holdout 中出现较高数值：

- max displacement AUROC≈0.933；
- sum displacement≈0.929；
- abs p_bad delta≈0.923；
- n_big≈0.874。

这些结果目前不能直接支持 writeback gate，原因：

1. outcome 仍受粗 candidate harm 定义影响；
2. displacement / abs delta 很可能主要识别“这次改得多不多”，而不是“改得对不对”；
3. `abs_p_bad_delta` 混合了好→坏和坏→好，丢失方向；
4. `n_big` 本质是 candidate changed-unit count，不应替代 unit-level behavior；
5. 某些 feature 仍缺完整 entropy/margin/consensus 数据。

保留结论：

> `n_big`、displacement、abs detector change 都可能是 **change magnitude / instability** signal，但是否能区分 improve 与 harm 尚未证明。

下一轮必须对每个 unit 单独计算 signed change，并检查 target 与 safe context 的方向差异。

---

## 6. Reject-Safe 是当前最关键的缺口之一

此前 whole-window S2 数量曾很少，但 unit-level join 已证明数据中存在大量：

- GT <=200ms；
- detector REJECT 或 UNCERTAIN；

的 unit。

当前 60-region formal 虽然有 S2=21，但仍主要围绕 suspicious region，且没有足够 S1 Accept-Safe 对照。

因此当前不能回答：

> detector 判 REJECT 的 GT-safe unit 是否比 detector ACCEPT 的 GT-safe unit 更容易被 realign 打坏？

这将成为下一轮主问题。

---

## 7. Request family：当前已证明需要进一步拆机制

现有 R-U / R-A / R-B 虽已比更早版本前进，但还不足以解释 realign 的稳定性。

需要新增/细化：

- very local contiguous unit request；
- sparse active-unit / slot-local；
- detector unsafe interval direct；
- bilateral stable anchor；
- one-sided left/right stable anchor；
- oracle-direct diagnostic。

目标不是做所有参数组合，而是比较不同机制。

---

## 8. Test Demo：当前仍不能算真正的 local realign 实验

当前 P0 inventory 曾发现 36 个 Demo items；本次实际 Test Demo stress summary 记录：

- n_items=33；
- n_failed=3；
- real demo requests=4；
- executor 为 real；
- 4 个 context request 因 bilateral anchors 缺失标成 R-NULL。

更严重的是，`TEST_DEMO_REALIGN_BEHAVIOR.jsonl` 中所谓 `R-U_unit_local` 的 target_unit_ids 实际覆盖整首/整 item，例如：

- Chinese/此处通往天空：0..285；
- Chinese/人造卫星：0..476；
- English/Past Lives：0..161；
- English/Renegade：几乎整首。

所以：

> Test Demo 已经验证“真实 executor 能运行”，但尚未验证“真实 production detector local region → local/sparse realign”的行为。

下一轮必须重新接线。

---

## 9. 当前结论强度

### 可以相对有把握地说

1. Detector unit-level production behavior 没有表现出旧 15.5% 那样的崩坏；约 85% ACCEPT 是当前可信行为量。
2. whole-window 97.5% unsafe 对研究 local recovery 的意义有限。
3. Realign 对输入/request 很敏感，当前行为明显不够稳定，Gate/请求设计仍是主问题。
4. 真实 GPU forward 数量可以扩大；当前主要限制更多来自 case/request construction，而非单次 forward 成本。
5. Test Demo 需要真正接入 local detector region，当前 4 个 whole-item pseudo-local request 不能代表结果。

### 当前不能说

1. “Realign 约 80% candidate 都 harmful”作为稳定生产结论。
2. `n_big` / max displacement 已经是可靠 writeback gate。
3. R-U/R-A/R-B 已经完成公平、充分的机制比较。
4. Test Demo 已经验证多语言 local realign。
5. Reject-Safe 的 harmful rate 已经得到充分估计。

---

## 10. 下一轮工作假设

以下均为待验证假设，不是当前结论：

- H1：realign 的主要问题可能来自 request basin 太窄，而非 aligner 完全没有 recovery 能力。
- H2：Sparse active-unit realign 能降低 safe-context collateral damage。
- H3：Reject-Safe unit 比 Accept-Safe unit 更脆弱，说明 detector 的 false positive 中包含“内部不稳定但当前 GT 恰好正确”的样本。
- H4：多个机制不同 request 对同一 unit 的 consensus 比单一 `n_big` 更有希望成为 no-GT reliability signal。
- H5：one-sided anchor 对串行场景可能比强制 bilateral anchor 更实用。
- H6：Oracle-direct 附近轻微 request perturbation 的稳定范围可以刻画 aligner 的 realign basin of attraction。

