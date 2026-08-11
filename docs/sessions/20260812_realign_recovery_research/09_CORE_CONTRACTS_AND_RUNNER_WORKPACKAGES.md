# WP-B：核心契约、缓存与可恢复 Runner

**前置：** Phase A 完成。先实现小型 fixture 的纯函数和 JSON schema，再接模型；不要在 GPU 上调试状态机。

## B1. 必须落盘的对象

| 对象 | 最小字段 | 目的 |
|---|---|---|
| `Episode` | id、song/source role、kind=`natural|propagated`、source window/state checkpoint、target unit ids、family、attempt/effective status | 统一 E3/E4 分母 |
| `Proposal` | method、audio/text span、anchors、context、no-GT inputs、identity | 证明 request 如何变化 |
| `Candidate` | proposal identity、forward identity、Raw output path/hash、ownership、status/failure | 共享模型 forward |
| `Decision` | trigger、old/new no-GT scores、rank、accept/reject reason、writeback span | 判断绝不读取 GT |
| `Continuation` | before/after state、committed provenance、后续 windows、cost | E9 配对比较 |
| `Evaluation` | GT binding hash、labeled/unlabeled、metrics、stage labels | 运行后独立 join |

所有 JSONL 行都携带 schema version；大模型输出可在内容寻址路径保存，JSONL 只保存路径/hash。原子写入 `*.partial` 后 rename；每阶段写 `COMPLETED.json` 与 `FAILURES.jsonl`。

## B2. Forward identity 与 cache

forward key 的 canonical JSON 必须包含：model/checkpoint/processor；source audio SHA 与原始时钟裁剪范围；文本 unit IDs 和文本内容 hash；slot/query mode；context/window；preprocess/resample/silence mapping；代码版本或 dirty diff hash；schema version。不得包含 GT、detector 阈值、ranking 或 writeback 策略。

相同 key 只允许一个 forward；锁定/原子 publish 避免并发重复。任何 key 缺字段或旧 cache 无法证明 identity 时，cache 状态只能是 `not_reusable`。

## B3. Runner 分层

1. `serial_baseline_runner`：冻结路径、可输出 state checkpoint；不改变 state。
2. `episode_builder`：从 baseline 输出生成 natural episode，或只注入一次的 P1--P5 propagation；报告 attempted/no-effect/effective。
3. `proposal_runner`：仅消费 no-GT episode/state/Raw detector，生成 R-A/R-B/R-C request。
4. `candidate_runner`：消费 proposal、调用/复用 forward cache；不得评分 GT。
5. `decision_writeback_runner`：Raw quality signal 与预注册 policy 决策，写回后继续 serial state。
6. `evaluator` / `reporter`：唯一可加载 GT 的后处理。

每层接受/产出 manifest 路径而非隐式扫描目录；CLI 都有 `--resume`、`--dry-run`、`--limit`、`--out-root`，失败 case 继续运行。

## B4. CPU 验收 fixture

新增 tests 覆盖：identity 同输入复用/任一关键字段变化失效；GT 字段拒绝进入 B3--B5；P1--P5 从第二窗口起不再注入；no-effect 不进入 effective denominator；candidate 不能被同样 request rerun 标为 realign；unsafe-only writeback 不改 safe ownership；resume 幂等；evaluator 不改 control artifact。

通过这些测试前，只允许运行 fake backend smoke。
