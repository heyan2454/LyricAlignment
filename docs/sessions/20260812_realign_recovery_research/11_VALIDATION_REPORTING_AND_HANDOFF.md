# WP-E：验证、报告与持续交接

## E1. 分层测试与 review

每个实现工作包至少运行对应 unit tests、`python -m compileall -q src scripts` 和 `git diff --check`。在首次真实 runner、writeback 和 formal report 前分别运行相关模块测试；阶段收尾运行：

```bash
PYTHONPATH=src python -m pytest -q tests/realign_recovery tests/research_transition_recovery_detector
PYTHONPATH=src python -m pytest -q tests/research_v7
```

测试失败不能用历史“1056 passed”替代当前结果。任何现有 dirty-change failure 要隔离记录，说明命令、首个失败和是否与本 work package 有关。

每个阶段完成后做 P0/P1 review：GT leakage、split/provenance、cache identity、state/writeback ownership、指标分母、resume。只在这些问题清零或明确阻塞后进入下一 GPU work package。

## E2. 统一报告结构

`09_reports/FINAL_REPORT.md` 和机器可读 `FINAL_SUMMARY.json` 必须以漏斗报告：

```text
effective episodes
-> detector detected
-> proposal audio covered
-> proposal text/occurrence covered
-> realign produced better candidate
-> quality gate accepted it
-> writeback caused no safe damage
-> serial trajectory recovered
```

每级均有 numerator/denominator、labeled/unlabeled、song/language/family 分层和 A/B/diagnostic scope。分别报告 unit、event/unsafe interval、window、episode、song、continuation；不得用 pooled unit accuracy 替代 closed-loop 结论。

历史 `14--16%`、exploratory 0.45、retrospective light-merge 数值必须沿用其 provenance 标签。所有 null/negative branch 都写 hypothesis、setting、denominator、观察、替代解释、真正排除的范围和未解决项。

## E3. 收尾与自由探索

结束 formal 前写 `00_meta/REPO_STATE_FINAL.json`、环境、resolved config、input/output/cache SHA、commands、budget、failure/resume 清单和 `NEXT_RESUME.md`。不提交 audio/checkpoint/大 prediction。

formal 完成、GPU cap 或某分支 bounded-insufficient 后，如果用户未打断，立即执行 `05_FREE_EXPLORATION_PROTOCOL.md`：创建 `FREE_EXPLORATION_TODO.md`、LOG、RESULTS。TODO 的最后一项必须是 `TODO-LAST-EXPAND-NEXT-ROUND`，按 05 的原文扩展下一轮并继续，不得以“等待用户”为结尾。

## E4. OpenCode 最终回复格式

仅回复：完成/阻塞状态；本批产物路径；测试与 GPU/CPU 实测；关键结果及 provenance；下一条正在执行的 TODO。长日志、表格和代码写入 session 文件，不粘贴到对话。
