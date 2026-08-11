# OpenCode / Agent 执行合同：Realign Recovery Session

本文件为强制执行约束。Agent 不能因为用户挂机就减少记录，也不能因为单项负结果提前结束整个 session。

---

## 1. 必须创建新的运行 Session

文档 session 已固定为：

```text
docs/sessions/20260812_realign_recovery_research/
```

实验运行必须再创建一个新的 `SESSION_ROOT` / `OUT_ROOT`：

- 不覆盖任何 20260807 / 20260808 / 20260810 / 20260811 旧 evidence；
- 将本目录 00–06 文档、Codex review/implementation plan、resolved config 复制/引用进新 session；
- 记录 repo commit、dirty diff、environment、model identity、data manifests、GT provenance、detector artifact/hash。

---

## 2. 正式运行前先做 implementation mapping，不重新做 baseline selection

必须确认当前实际实现：

- full-slot；
- 60/10/10；
- silence-aware planner / skip / leading / tail；
- current product serial transition（预期 nominal T2 core-boundary）；
- Raw output path；
- fixed Raw detector after `light_merge`；
- real-GT loader。

如果 config 名称与文档略不同：

> 记录实际 mapping，做最小适配；不要重新跑旧大消融决定谁是 baseline。

---

## 3. GT Firewall

### Oracle phases

GT 可以用于：

- 定义 target unit span；
- 定义 oracle audio coverage / correct text span；
- 最终评分。

GT 不得作为：

- per-character timestamp input；
- decoder correction；
- hidden retry hint，除非该 branch 明确命名为更强 oracle diagnostic。

### No-GT phases

GT **完全不能**参与：

- detector trigger；
- audio proposal；
- text proposal；
- candidate generation/ranking；
- retry choice；
- writeback；
- serial cursor/state update。

建议实现：

- no-GT runner 不接受 GT path 参数；或
- control phase 完成后再独立 join GT evaluator。

必须有测试证明 control artifact 在 GT unavailable 时也能生成。

---

## 4. Candidate cache 与 request identity

每个 model forward 的 cache key 必须至少包括：

```text
model/checkpoint/processor
source audio identity
audio start/end
text unit ids/text identity
slot/query mode
context/window configuration
relevant baseline preprocessing identity
```

不得把 detector threshold、writeback threshold、GT label 放进 model-forward identity。

这样后续：

- detector threshold sweep；
- candidate ranking；
- writeback policy；
- metric 更新；

全部基于缓存重算，不重复 GPU。

---

## 5. Resume / failure behavior

- 每个 candidate / episode 原子落盘；
- 每阶段有 manifest、FAILURES、completed ids；
- 支持 `--resume` 或等价机制；
- 单个 case 失败只记录并继续独立 case；
- 禁止因为一个 family 失败就停止其余 phase；
- 达到 hard resource limit 时保存精确 resume plan。

---

## 6. 预算与挂机行为

- GPU target：约 10 h；
- GPU hard cap：12 h，继承此前项目约束；
- 用户挂机意味着可以把 GPU budget 用于更大的 natural trajectory / candidate bank，而不是只跑 smoke 后停；
- 达到 GPU hard cap 后：停止新的 GPU forward，但**不能因此结束整个 session**；继续进行缓存分析、统计、报告、negative results、free exploration CPU 工作，直到用户主动打断或出现无法安全继续的资源/数据问题。

优先级：

1. E1 oracle repairability；
2. E3/E4 有效 propagation corpus；
3. E5/E6 candidate bank；
4. E7 quality judgement；
5. E9 closed-loop；
6. E10 retry；
7. 非必要额外候选。

---

## 7. 有效错误 episode 配额

受控 perturbation 必须区分：

```text
attempted
no_effect
effective_propagation
```

Recovery 主指标只以 `effective_propagation` 为主要 denominator。

主要 family 目标有效 episode >=64；若资源上限仍不足：

```text
status = bounded_insufficient
```

并继续其他 family，不得把“没制造出错误”写成 recovery 成功。

---

## 8. 不得原样 rerun 冒充 realign

same audio + same text + same model 的简单再次 forward 可以保留为 null control，但不能包装成 recovery 方法。

Realign branch 必须记录 request 相对 original 的变化：

- audio range；
- text range/occurrence；
- context/anchor；
- window size。

---

## 9. 正式结果必须区分层级

至少分：

- unit-level；
- unsafe interval/event-level；
- window-level；
- propagation episode-level；
- song-level；
- serial continuation outcome。

不能用 pooled unit accuracy 替代“系统是否从错误轨道恢复”。

---

## 10. 必须记录 Negative Results

每个无收益/失败分支记录：

```text
hypothesis
setting
denominator
observed result
possible explanation
alternative explanation
what is actually ruled out
what remains unresolved
```

不能把一个负结果过度推广到所有 realign。

---

## 11. 正式实验完成后不得自动停止

如果：

- 预定 formal phases 已完成；
- 用户没有发来主动打断/新指令；

则 OpenCode/Agent **必须立即进入 `05_FREE_EXPLORATION_PROTOCOL.md` 定义的自由探索环节**。

不得输出“实验完成，等待下一步”后停止。
