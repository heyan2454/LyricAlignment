# Agent 执行合同：新 Session、不中途停止、可恢复执行

本文件是强制合同。实现/运行 Agent 不能只读实验概述后自行简化。

## 1. 必须创建全新 SESSION_ROOT

不得继续使用或覆盖旧：

- `runs/research_v7_align_behavior/...`；
- 旧 Detector V2 OUT_ROOT；
- 旧 `research_fullslot_serial_detector` 运行目录；
- 任意已有 formal evidence 目录。

默认创建：

```bash
SESSION_ROOT="runs/research_transition_recovery_detector_20260807/session_$(date -u +%Y%m%dT%H%M%SZ)"
```

若用户/环境指定更大磁盘 OUT_ROOT，可改父目录，但 session basename 和内部结构保持独立；必须把实际绝对路径写进 `SESSION_META.json`。

建议目录：

```text
SESSION_ROOT/
  00_meta/
  01_precheck/
  02_transition/
  03_propagation/
  04_oracle_recovery/
  05_legacy_gaps/
  06_detector/
  07_closed_loop/
  08_transfer_demo/
  09_reports/
  cache/
  logs/
  SESSION_STATE.json
```

旧 evidence 只读引用；任何修复后重新生成的数据写进本 session。

---

## 2. Agent 不得“中途停止”的具体含义

以下均**不是停止整个 session 的理由**：

- 某个 experiment result 很差；
- 某个 detector 无增益；
- SA60+R95 joint 不可行；
- 某个 mutation family 诱发率低；
- 某个 family 达不到 64 个有效 propagated episodes；
- hidden 没增益；
- CNN/TCN 没增益；
- MIR 跨域明显下降；
- 某个 demo 失败；
- 单个脚本/item 异常。

处理方式：

1. 写入 authoritative failure/negative-result artifact；
2. 标状态 `negative_result`、`bounded_insufficient` 或 `item_failed`；
3. 保存真实分母与失败原因；
4. 继续执行不依赖该成功结果的后续阶段；
5. 对依赖该分支的阶段使用预注册 fallback（例如 sequence 无增益则使用 simple MLP；joint 不可行则分别用 SA60/R95）。

### 只有全局阻塞才允许停止

例如：

- 模型 checkpoint 不存在/损坏且所有 GPU 阶段都无法运行；
- 必需数据整体不可读；
- CUDA/环境损坏导致所有 forward 无法执行；
- 磁盘不可写且无法切换到用户允许的 OUT_ROOT；
- 发现会污染全部结果的严重 identity/split 错误。

即使全局停止，也必须先写：

- `GLOBAL_BLOCKER.json`；
- 已完成阶段清单；
- 最后成功 artifact；
- 失败命令/log；
- **可直接复制执行的 resume 命令**。

不得只留一句“实验失败/时间不够”。

---

## 3. 状态机与继续规则

`SESSION_STATE.json` 至少包含：

```json
{
  "session_root": "...",
  "current_phase": "phase_x",
  "phases": {
    "phase_0": {"status": "complete|partial|blocked|pending"}
  },
  "gpu_seconds_used": 0,
  "hard_budget_seconds": 43200,
  "resume_command": "..."
}
```

每完成一个 phase 原子更新。

Phase 的 `partial/bounded_insufficient` 不等于 session failure。

---

## 4. Phase 0 不得省略

Agent 首先阅读：

1. 本目录全部文档；
2. `docs/sessions/20260807_transition_recovery_detector_discussion_record.md`；
3. 上游 `docs/research_fullslot_serial_detector/`；
4. Detector V2 最新 result review / BACKLOG25 summary；
5. `AGENTS.md`。

随后必须：

- 搜索已有 T0–T3 代码；
- 输出 implementation map；
- 跑 CPU/small smoke；
- 冻结 resolved config；
- 再启动 formal。

禁止一上来重新写一套全新的 serial pipeline，除非证明现有实现无法映射。

---

## 5. Formal 后禁止临场调参

进入 formal 前冻结：

- long-silence retain seconds；
- silence snap search/threshold；
- tail merge/redistribution；
- window boundaries semantics；
- full-slot mapping；
- transition state semantics；
- detector scaler/model/threshold；
- L/W retry count/context；
- metric tolerances。

Formal 中只能：

- 修复明确代码 bug；
- 修复会导致结果无效的 schema/identity bug；
- 继续 resume。

修 bug 后若影响已完成结果，必须自动 invalidation 并只重跑受影响 identity。

---

## 6. 传播异常不得“造得太简单”

主数据优先级：

1. natural model error；
2. model-native alternate candidate forced commit；
3. canonical state corruption；
4. simple zero-duration / naive text corruption 仅 sanity。

禁止为了满足 propagated episode 数量而：

- 把当前窗局部异常当 propagated；
- 把从未 commit 的 rejected unsafe 当 propagated；
- 直接写一串明显零时长假输出充数量；
- 使用 GT 构造下一窗输入后再声称自然传播。

---

## 7. W/L route 必须唯一解释

必须采用：

```text
DetectorOutput
→ build_route_plan(...)
→ RoutePlan
→ execute_route_plan(...)
```

`execute_route_plan` 不得重新读取风险分数改变决策。

测试必须覆盖：

- W REJECT 时零提交；
- L 不越过 unresolved gap；
- cursor 始终等于第一个未永久提交 canonical unit；
- committed canonical ids 连续、无重复/漏失；
- shadow 不改变真实 trajectory。

---

## 8. SA60 / SA80 / R95 不得误解

- SA60：safe accept ≥60%；
- SA80：safe accept ≥80%；
- R95：unsafe **REJECT** recall ≥95%；UNCERTAIN 不算 reject；
- 旧 protected recall 不可替代 R95。

Joint 不可行不是停止理由。必须分别完成三者。

---

## 9. 不允许自动膨胀矩阵

未经明确证据触发，不得新增：

- decoder × transition 全组合；
- non-slot × 所有 transition/recovery；
- retain silence 多个细粒度值；
- 更多 classifier；
- 更多 hidden layer；
- strict silence 多参数扫描。

新增实验必须在 `EXPERIMENT_DEVIATIONS.md` 写：

- 为什么现有计划不足；
- 新实验回答什么；
- 预计额外 GPU 成本；
- 哪个低优先级实验被替换/缩减。

---

## 10. 结果报告必须自动生成

最终至少产出：

```text
09_reports/
  TRANSITION_REPORT.md/json
  PROPAGATION_REPORT.md/json
  ORACLE_RECOVERY_REPORT.md/json
  LEGACY_GAP_REPORT.md/json
  DETECTOR_REPORT.md/json
  CLOSED_LOOP_REPORT.md/json
  MIR_TRANSFER_REPORT.md/json
  TEST_DEMO_REPORT.md/json
  FINAL_SESSION_REPORT.md/json
  NEGATIVE_RESULTS.md
  EXECUTION_AUDIT.json
```

Markdown 关键数字必须来自 JSON；不得手工复制后失配。

---

## 11. 最终完成定义

Session 只有在以下全部有明确状态后才结束：

- T0–T3 完成或有明确 bounded/block reason；
- Product + Mechanism candidate 已选或说明无法选择；
- propagation benchmark 有真实分母；
- oracle L/W 已评；
- old gap 每项明确 complete/not-executed-with-blocker；
- SA60/SA80/R95 均有正式结果或不可行证据；
- selected L/W closed-loop 已完成；
- MIR fixed transfer 和 test demo 自动分析已执行到可用范围；
- negative results 已记录；
- final report 明确“已验证 / 探索性 / 未完成”。

不能因为某一分支失败而把整个 session 提前标 `complete=false` 后直接退出；应继续完成其余独立任务，再在最终报告中如实标部分缺口。
