# 研究线 C：Detector 工作点与新信号

## 1. Detector 的角色重新定义

旧 detector 主要回答“当前 unit 是否 correctness-unsafe”。下一阶段保留该任务，但增加第二个更贴近产品的问题：

> 如果当前错误被 commit，它是否会导致后续 Transition 明显恶化？

因此区分：

1. **correctness detector**；
2. **propagation-risk detector**。

只有主线 A 有真实 propagation corpus 后，第二种标签才可定义。

---

## 2. 正式工作点

### SA60-primary

约束：

`safe_accept_rate >= 0.60`

在此条件下尽量提高 unsafe reject / 降低 unsafe commit。

### SA80-primary

约束：

`safe_accept_rate >= 0.80`

高吞吐工作点。它不保证“更安全”，但非常适合暴露会真正进入 carried state 的错误，也是 serial propagation 研究的关键点。

### R95-primary

严格定义：

`unsafe_reject_recall >= 0.95`

**UNCERTAIN 不计入 REJECT。** 旧 `protected = REJECT + UNCERTAIN` 不得替代 R95。

### Joint feasibility

尝试同时满足：

- safe_accept >= 60%；
- unsafe_reject_recall >= 95%。

若不存在合法双阈值：

- 报告不可行和 Pareto gap；
- **不得停止**；
- 必须继续分别完成 SA60-primary 和 R95-primary；
- SA80 同样独立完成。

---

## 3. 静态指标

至少报告：

- AUROC / AUPRC（辅助，不作为唯一验收）；
- safe_accept；
- safe_reject；
- unsafe_accept / false accept；
- unsafe_reject；
- uncertain rate；
- interval@75 / interval@100；
- unit-level 与 interval-level 分开；
- raw-target 与 official-target 若同时报告必须明确标签口径。

不同数据集、不同 metric schema 不得混成一个总分。

---

## 4. 新信号优先级

### D1 Cross-window consistency — 最高优先级

同一 canonical/provisional unit 在相邻重叠窗口中的：

- timestamp displacement；
- posterior JS/L2；
- top-k candidate displacement；
- raw/official change；
- occurrence identity stability。

重点找：单窗低 entropy / 高 confidence，但换上下文后整段跳位置的 stable-but-wrong。

### D2 Posterior competing coherent path

不只看单点 entropy，而寻找两条连续合理路径：

```text
path A: 60, 61, 62, 63 ...
path B: 102,103,104,105 ...
```

特征：

- best vs second coherent path score gap；
- 两 path 时间距离；
- second path 连续性；
- 是否对应另一个真实 occurrence。

优先服务 repeated chorus / occurrence ambiguity。

### D3 Sequence trajectory

连续 unit 的：

- entropy trend；
- margin trend；
- timing velocity / acceleration；
- zero-duration/compression run；
- repair cluster；
- posterior mode switch；
- raw→official correction pattern。

### D4 Per-unit CNN/TCN

输入序列特征，输出每 unit 风险/三态；禁止使用旧 any-bad sequence label 广播协议。

只保留一个轻量 sequence model + simple MLP baseline。若无增益，不扩 Transformer/更多模型。

### D5 Hidden sequence

仅在 hidden extraction gate 通过后：

- adjacent hidden cosine；
- change point；
- multi-layer trajectory；
- raw-safe / hidden-risk / GT-wrong case mining。

无增益即停止。

---

## 5. Propagation-risk target

从主线 A episode 定义结果标签：

- low risk：当前有误差但 ≤1 窗自恢复，且没有额外错误 commit；
- medium：2–3 窗恢复或有有限 corrupted commits；
- high：persistent / amplifying / occurrence jump / catastrophic corruption。

训练/评估时不能把后续 GT 结果泄漏到输入 feature，只能作为 label。

比较：

- correctness detector 对 high-risk propagation 的 recall；
- propagation-risk detector 的 high-risk recall；
- 在相同 safe acceptance 下，哪一个减少 closed-loop corrupted committed units 更多。

若 propagation-risk detector 能允许“无害小错”通过而仍阻断高危传播，才算对产品有实质价值。

---

## 6. Failure-family generalization

只在 propagation families 上做 leave-one-family-out：

- cursor shift；
- time shift；
- partial tail/boundary；
- occurrence；
- model-native alternate path。

目的：判断 detector 学的是通用 instability 还是记住异常类型。

不再为普通 replace/missing/extra 做大量 classifier 网格。

---

## 7. Closed-loop 使用规则

静态工作点冻结后，才进入主线 A 的 selected Transition。

建议：

- Product candidate：SA60 / SA80 / R95；
- Mechanism candidate：优先 SA80 + R95；
- Recovery：L 与 W 按 `02_TRANSITION_RECOVERY_MAINLINE.md`。

同一 threshold 在不同 Transition 上若分布明显漂移：

- 首先报告 fixed-threshold transfer；
- 不得偷偷为每个 Transition 重新调阈值后称公平比较；
- 若需要 transition-specific calibration/threshold，作为第二层明确实验。

---

## 8. 何时停止某个 detector 分支

以下情况可停止该**分支**，但不能停止整个 session：

- hidden extraction 成功但 heldout/transfer 无增益；
- per-unit sequence 不优于 simple MLP；
- competing-path 只能识别 seam artifact；
- propagation-risk target 样本量不足达到预注册门槛。

必须保存 negative result、分母、配置和停止原因，然后继续其他独立分支与最终闭环。
