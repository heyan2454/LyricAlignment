# Codex 合并与后续实现规划 Handoff

## 1. 本 patch 的用途

用户将先把本 patch 交给 Codex：

1. 合并到当前 LyricAlignment 工作目录；
2. 核对这些文档与当前仓库真实实现/数据路径是否冲突；
3. **不要直接把文档中的假设路径/函数名当成已存在实现**；
4. 在合并完成后，由 Codex 给出下一轮的具体实现方案；
5. 用户随后把该实现方案交给 OpenCode 实现与运行。

本 patch 本身不包含实验代码实现。

---

## 2. Codex 必须先核实的事实

### 2.1 当前 detector exact identity

核实并记录：

- `light_merge` 修复后的 artifact 路径；
- Raw threshold / tri-state aggregation exact config；
- retrospective A 中 safe accept≈0.8320、protected recall≈0.9567 的 exact source artifact/metric schema；
- 当前 production-style runner 是否与 retrospective evaluation 使用同一 unit/window aggregation。

如口径不同，必须在实现计划里明确 bridge，不能只比较数字。

### 2.2 当前可用 M4Singer / real-GT 数据

不要继承 5+5 hardcode。检查：

- accepted real-GT loader；
- source-song split；
- long-timeline builder；
- 现有 cache；
- 当前能合法构造多少 production 60/10/10 windows；
- realign GT sampling 可覆盖多少首歌。

### 2.3 当前 Test Demo 实际 inventory

必须动态发现当前机器上的 Demo，不使用历史固定数量。

核实多语言目录、媒体路径、已缓存 alignment、可复用 detector outputs。

### 2.4 Oracle/recovery metric 实现

核实上一轮 oracle evaluator：

- `thresholds_ms` 是否确实未进入汇总；
- raw evidence 是否足够离线补算 start/end 100/200/500ms；
- `repaired@1s` 是 after-threshold 还是 before→after transition。

能离线补算则不要重跑 GPU。

### 2.5 E8/E9 语义

实现方案不得继续把：

- E8 `net_improved` 当 seconds improvement；
- shadow `actual_writeback=0` 的 E9 当真实 stateful closed loop。

---

## 3. Codex 输出具体实现方案时必须包含

### A. 文件/模块级 mapping

对每个阶段列：

- 复用哪些现有模块；
- 新增哪些 script/module/test；
- 哪些旧结果只读；
- 新 `SESSION_ROOT/OUT_ROOT`；
- 输入/输出 schema。

### B. 一条龙执行与阶段命令

至少设计：

```text
00_inventory
01_detector_production_audit
02_realign_behavior_collect
03_gate_feature_analysis
04_test_demo_behavior
05_report
```

每阶段可单独 resume；给 smoke 与 formal/light-formal 入口。

### C. 预计成本

分别估算：

- CPU/cache-only；
- GPU forward 次数；
- 60–100 GT cases × 2 variants；
- 10–20 Test Demo realign cases；
- conditional stability probes。

若预计 GPU >6h，优先减少 candidate/stability probe，不减少 cached detector audit 的 song coverage。

### D. 测试

至少覆盖：

- GT firewall；
- no-GT feature 不含 GT；
- dynamic Test Demo discovery；
- song-held-out split；
- candidate text identity；
- before/after metric correctness；
- threshold transition；
- cache identity；
- resume；
- no Cartesian explosion assertion / run-count sanity。

---

## 4. 需要保留给 OpenCode 的自由探索空间

实现方案应允许 OpenCode 在完成预注册结果后，直接在机器上基于 feature table 做 bounded exploration：

- 新的可解释 before/after signal；
- harmful/improved counterexample；
- 简单 gate 组合；
- Test Demo high-risk pattern。

但不得：

- 无限制扩大模型/decoder/transition 大轴；
- 反复看 holdout 调 threshold；
- 把 Test Demo 人工观感当 GT；
- 因某个 exploratory feature 好看就跳过 counterexample/holdout。

建议在实现计划中明确 exploration TODO，最后必须回到“下一步验证什么、哪些结论仍弱”的收束，而不是自动转为无边界长跑。
