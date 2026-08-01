# Research v6 正确性修复记录（2026-07-31）

## 修复结论

本轮将上一版标记为 `formal blocked` 的问题全部落实到代码、指标、控制流与报告中。当前状态为：**静态与 CPU 测试通过，可以进入单 Demo GPU smoke；尚未在本归档环境中声称真实 GPU/formal 结果。**

## 1. Decoder 时间坐标

Top-K timestamp class 仍是窗口内类别。实现不新增持久字段，而从已有 local/global 成对字段稳定恢复窗口偏移：

```text
offset = raw_global_start_sec - raw_local_start_sec
全局时间 = offset + timestamp_class * timestamp_segment_sec
```

start/end、raw/official/fixed 的已有字段均可参与恢复；多个可用差值取中位数。若旧缓存只有明显非零全局时间、却没有任何 local 字段，代码明确报错，不静默按零偏移解释。

## 2. 指标作用域

局部实验统一同时保存：

- `metrics`：固定 target/ownership 的 local GT；
- `spliced_full_metrics`：局部候选写回 baseline 后的整首指标；
- `spliced_delta_vs_baseline`：整首变化；
- `metric_scope`：字符起止和 reference 数量。

E2、E4、E8 不再用几十字候选对整首 GT 直接评分。

## 3. 冻结 Detector 真正进入 formal

- 规则分数保留为 `rule_risk_score`；
- 冻结 Logistic/Stump 输出 `learned_risk_score`；
- 下游统一读取 active `risk_score`；
- risk span、safe boundary、E5 和 E8 都由 active score 与其同量纲 threshold 生成；
- safe-boundary 评测使用 `safe_boundary_decision_score`，严格复用“active risk 足够低 + boundary evidence 足够高”的规划判据；
- `detector_model_threshold` 与 `detector_risk_threshold` 分离，禁止概率阈值误用到规则分数。

Pilot 按 `source_song_id` 划分 train/calibration；模型只在 train 拟合，阈值只在 calibration 选择。Formal 仅用冻结模型与阈值，并把 formal threshold curve 标为诊断用途。

## 4. E0–E9 补全

- **E0**：增加 raw 正确被改坏率、raw 错误修复率与 candidate movement。
- **E1**：接入跨输入、跨窗口、cursor 和音频支持；增加 unit/event PRF、repairable PRF、safe-boundary PRF、source-song cluster bootstrap。
- **E2**：baseline/corrupted 共同进入跨输入特征；平滑整体偏移不再只靠结构特征；增加 corruption 分组和 event PRF。
- **E3**：同时运行 GT oracle span 与冻结 Detector span 的 local weighted isotonic / local top-K，同 logits、无额外前向。
- **E4**：固定 local GT；实现 oracle、fixed shortest/longest、Detector 选择、顺序扩展；96 与 3×32 使用相同 96 字 scope，并报告 seam、调用数、cache 与 RTF。
- **E5**：safe exact/-2/-4 同步修改下一窗音频起点和歌词 cursor；少于两窗标记 not-applicable；汇总 cursor、漏/多字、seam、first failure、恢复距离与 fallback。
- **E6**：静音压缩后的 alignment 与 trace 一起映射回原时钟；无静音不重复运行无意义候选；按静音长度汇总静音前/后边界。
- **E7**：短样本 not-applicable；汇总注入后的持续恶化、text/time/full reset 恢复和因果支持率。
- **E8**：保存主输入和扩展上下文备用输入；局部候选写入 committed prefix 后，从目标所在 baseline 窗重跑同窗尾部和全部后续窗口；输出 local、spliced-full、clean harm、oracle match、真实 downstream delta 与 continuation failure。
- **E9**：不再分析历史 attempts 的 rank。每条模型 hypothesis 带着 committed/input cursor 与 previous-window state 跨窗继续，最多保留 3 条；无推进路径淘汰，按无 GT 的透明规则剪枝，全失败时显式 baseline fallback。行级粗定位仍不读取字符级 alignment。

## 5. 数据与公平性

- M4Singer manifest 保留 `split`、`selection_role`、`training_exposure`、`source_song_id`；synthetic-long 禁止跨 split 拼接。
- MIR-1K 保留 development/extra/spare/heldout role，正式汇总不再混为一个不可区分结果。
- Decoder 汇总提供 dataset/split、selection role、training exposure 和主泛化（排除 training exposure）口径。
- Synthetic-long 提供 source-song cluster bootstrap 和 seam-near/seam-far。

## 6. 可恢复性与计算控制

- E2–E9 每 phase 独立落盘并可 resume；item summary 只有在已覆盖本次请求 phases 时才整体跳过。
- local inference 使用确定性磁盘 cache；同一 request 只做一次 Qwen 前向，decoder 离线复用。
- cache 命中时分别记录 `actual_forward_wall_sec=0` 与 `estimated_uncached_wall_sec`；实际运行成本和无缓存公平比较成本不再混用。
- request hash 排除运行期私有对象，避免 resume 身份不稳定。
- Formal 默认消费 manifest 中每个 item，并令 local windows、96字组、realign spans 三类上限均为 0，即穷举全部 eligible case；正整数上限只用于显式 case-level subsampling 诊断，不能与完整 formal 混称。
- 模型检查要求存在 `processor_config.json` 或 `preprocessor_config.json`。

## 7. 验证

当前归档环境结果：

```text
compileall: passed
research_v6 correctness + related targeted tests: 23 passed
all tests excluding 3 modules blocked by missing pypinyin: 261 passed
full pytest collection: blocked only by ModuleNotFoundError: pypinyin
empty aggregate + formal report smoke: passed
```

未在本环境验证：真实 Qwen/R2 GPU forward、完整 MIR-1K/M4Singer formal wall time、全量 GPU 数值结果。正式结果必须由服务器 smoke/formal 产物给出。

## 8. 二次 review 后补修

首次正确性修复后再次逐链路审查，发现并修复：E5 风险否决边界仍可能被 planner 选中；E8 downstream 静态 splice 必然为零；E9 仅重排历史 attempts；极端全无效候选可使 aggregate 崩溃；E4 尾部 24–95 units 被误标为完整 96；冻结规则未覆盖 safe/repairable thresholds。对应实现与测试见 `07_E8_E9_AND_BEST_EFFORT_FREEZE_FIXES_20260731.md`。
