# D1–D8 架构评价与当前收敛

## D1 Detector 先行反馈

价值：形成 align→detect→realign 循环。问题：旧 detector 过弱，且多为完整 align 后补救。保留 post-hoc 和 per-window precommit 两种基线，但 detector 不得直接写 committed state。

## D2 Request 标准接口

最小 Request 只描述 audio/text/slot/workflow/mutation 和 parent。它类似可重放任务记录，不要求 detector 自动写复杂原因。是实验公平性和 realign lineage 的核心。

## D3 EvidencePack

定位为每次 attempt 的不可变 cache。动态分窗和 realign 会产生多个 pack，而不是把所有变量塞入一个 pack。分 Runtime Evidence 与 Research Evidence。

## D4 SerialController

最终需要，但第一版只支持 provisional、accept、reject、rollback、unresolved 和最大尝试数。不要先建庞大 FSM。

## D5 Post-hoc detector

长期不作为主架构，只保留 shadow monitoring、数据收集和离线评价。应基于新 Request/Evidence 重写，不继续依赖旧耦合 pipeline。

## D6 Request pool

思想保留。旧 E9 不能作为可靠反证。未来每次只生成 2–5 个有明确语义的候选，达到 acceptance 即停，全部失败则 unresolved，并记录 RTF。

## D7 连续评分

不先堆大量人工规则。输出多维 QualityReport 或学习式 acceptance 概率。少数硬规则只负责非法顺序、越界、运行失败和回滚完整性。

## D8 Contract-first

是 D2/D3/D4 的实施原则：先定义 Request、Attempt/Evidence、QualityReport，再做 Controller。

## 当前最小架构

```text
Minimal AlignmentRequest
        ↓
Aligner Attempt
        ↓
Runtime / Research Evidence
        ↓
QualityAssessor: safe / danger / unknown
        ↓
Bounded Request Proposals
        ↓
New Attempts
        ↓
Acceptance Gate
        ↓
Commit / Rollback / Unresolved
```

## 关键边界

- QualityAssessor 不必解释全部错误原因；
- Request proposal 初期可以是固定枚举策略；
- 不强制候选排序，只判断是否达到接受标准；
- 串行不是项目定义，整首/sparse/localize-first 都要公平比较。
