# 正式实验后的持续自由探索协议

- 用户明确要求：正式实验完成后，如果没有主动打断，OpenCode 必须进入自由探索。
- 自由探索不是无记录随机试验；必须维护 TODO、证据、预算和负结果。

---

## 1. 进入条件

满足任一：

1. `03_REALIGN_EXPERIMENT_PLAN.md` 的计划实验已经完成；
2. 主要 GPU forward 已达到 hard cap，但已有 candidate/cache 可继续 CPU 分析；
3. 某分支因 bounded insufficiency 无法继续，但其他独立探索仍可进行。

如果用户发来新指令，优先执行用户新指令；否则不得停在“等待用户”。

---

## 2. 必须先生成 TODO 文件

进入自由探索时创建并持续更新：

```text
FREE_EXPLORATION_TODO.md
FREE_EXPLORATION_LOG.md
FREE_EXPLORATION_RESULTS.md
```

每个 TODO 至少写：

```text
id
question / hypothesis
why it matters
input artifacts
GT allowed? (oracle/eval-only/no-GT)
expected cost
stop condition
expected artifact
status
result summary
```

---

## 3. 第一轮自由探索优先来源

优先从正式结果中找：

- oracle 能修但 auto proposal 失败的 episode；
- proposal 对但 aligner 仍失败的 family；
- detector 错误接受 harmful repair 的 episode；
- candidate ranking regret 最大的 case；
- C1 已恢复但 C3 反而变坏的 case；
- recursive shrink 出现 sweet spot 的 case；
- repeated occurrence / long vowel / silence 边界的异常族；
- 自然 Demo 中 detector 高风险但 GT 缺失的 case（只能做 no-GT mechanism exploration，不伪造 correctness）。

---

## 4. 自由探索优先使用缓存

在 GPU 12 h hard cap 内还有预算时，可以对高价值 hypothesis 增加少量 forward。

达到 GPU hard cap 后仍继续：

- candidate bank 重分析；
- detector repair-quality scoring；
- threshold / ranking / writeback policy；
- case clustering；
- failure taxonomy；
- visualization/data mining；
- Test Demo 自动统计；
- 文档与 negative-result synthesis。

不得为了“保持运行”无意义重复 forward。

---

## 5. 每轮 TODO 的最后一项是强制的自续航项

**每一版 `FREE_EXPLORATION_TODO.md` 的最后一条 TODO 必须逐字表达以下含义，不得删除：**

> **重新展开下一轮自由探索 TODO 与延续 TODO：复盘本轮已完成、失败、异常、未决和新的证据；把所有未完成且仍有价值的事项作为 carry-over；根据最新结果再生成下一轮可执行 TODO，至少包含一个结果复核/反例任务、一个机制解释任务、一个与 no-GT realign/quality gate/closed-loop 或 negative result 相关的任务。完成本条后立即进入新 TODO 列表继续执行，在用户未主动打断且仍有安全可执行工作时，不因当前 TODO 列表耗尽而停止。**

建议固定 ID：

```text
TODO-LAST-EXPAND-NEXT-ROUND
```

执行这一项时必须：

1. 总结本轮 TODO completion；
2. 收集 carry-over；
3. 从新结果产生新 hypothesis；
4. 写出下一轮 TODO；
5. 把新的 `TODO-LAST-EXPAND-NEXT-ROUND` 再放到新列表最后；
6. 继续执行下一轮。

因此 TODO 是循环展开的，而不是一次性清单。

---

## 6. 允许停止/暂停自由探索的条件

仅在以下情况下暂停：

- 用户主动打断或给出新任务；
- 存储/环境/数据安全风险，需要人工决定；
- 所有可安全进行的 GPU 与 CPU 探索均确实耗尽，且下一轮 TODO 只能重复已有实验；此时仍必须生成完整 carry-over / why-no-new-work 记录，而不是静默结束。

网络/GPU 单项故障不等于整个自由探索停止；能做缓存 CPU 分析时继续。

---

## 7. 自由探索不能改变冻结 baseline 的边界

自由探索默认仍不得重新打开：

- 模型训练；
- decoder 大矩阵；
- transition 大矩阵；
- slot/non-slot 大矩阵；
- detector 全特征搜索。

如果正式结果清楚证明某冻结模块成为 load-bearing blocker，可以建立 TODO：

```text
propose_unfreeze_<module>
```

但只能先形成证据与最小验证建议；未经用户新指令，不把它扩大成新主线。
