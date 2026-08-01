# 2026-07-31 Alignment Research v6 正确性修复与 formal 解阻

> **Superseded note:** 本记录描述首次 correctness 修复。E8 downstream 与 E9 beam 的实现后来发现仍不充分，已由 `20260731_alignment_research_v6_e8_e9_completion.md` 更正。

## 任务

对 `LyricAlignment_20260731_alignment_research_v6_full_implementation` 做实现级修复。用户明确要求：

- top-K decoder 不新增 offset 字段，只从已有 local/global 字段恢复偏移并正确转成全局时间；
- Smoke 默认单 Demo 保持不变；
- 其余 review 问题全部按方案落地。

## 核心问题与处理

1. **top-K 时钟混用**：改为从 `raw_local_*` / `raw_global_*` 等既有字段恢复 offset；加入 60s 非零窗口测试。
2. **局部候选对整首 GT**：E2/E4/E8 显式 local scope；E8 同时保存 spliced-full 与 baseline delta。
3. **冻结 Detector 未驱动 formal**：区分 rule/learned/active score；risk span、safe boundary、E5、E8 全部读取 active score。
4. **E5 音频/歌词不同步**：window plan 同时设置 `input_start_sec` 和 `planned_input_character_start`，serial trace 记录是否应用。
5. **数据切分丢失**：M4 split、role、training exposure、source song 写入 manifest；synthetic-long 禁止跨 split；MIR role 独立。
6. **Detector 特征/口径不完整**：接入 trace 的跨输入、跨窗口、cursor 与音频证据；增加 unit/event/repairable/safe PRF；safe 指标复用规划联合判据；pilot source-song train/calibration。
7. **E2–E9 只落 item 文件**：全部增加项目级 aggregate；正式报告直接呈现各阶段指标。
8. **E6 跨时钟诊断**：压缩音频输出的 alignment 和 trace 一起恢复到原时间轴。
9. **E7/E8/E9**：补 causal reset 汇总、E8 备用输入/clean harm/downstream、真实 beam coverage 和独立行级 baseline。
10. **计算与恢复**：E2–E9 phase resume、确定性 request cache、稳定 request hash；cache 命中实际耗时与无缓存估算成本分离；formal 全 item 且重复 case 默认均为 0（全部穷举）；正整数仅用于显式 case-level subsampling。

## 验证

```text
compileall: passed
research_v6 correctness tests: 9 passed
research_v6 targeted total at that revision: 15 passed
all collectable tests at that revision excluding missing-pypinyin modules: 252 passed
full pytest: 3 collection errors, all due packaging interpreter missing pypinyin
empty aggregate + formal report smoke: passed
```

没有真实 Qwen/R2 权重与完整数据，因此没有 GPU 数值或 formal 结果。当前结论是实现解阻，不是实验结论。

## Negative results / 限制

- 未实现并声称模型级 batch inference；当前用 request cache 消除重复前向，真实吞吐需服务器 pilot。
- E9 仍是能量跨度 + 歌词长度分配的独立 coarse baseline，不代表 ASR/embedding 最终方案。
- E8 仍是受控后处理/反事实候选，未写回 production commit 状态机。

## 下一步

1. 安装 `pypinyin` 后运行完整 pytest；
2. 单 Demo smoke 检查 E0–E9 schema、top-K 60s 以后时间和视频；
3. 使用新 `OUT_ROOT` 启动 formal；
4. 根据 pilot 实测 wall time评估完整 formal；如必须使用正整数 case 上限，应单独标记为 subsampled diagnostic。
