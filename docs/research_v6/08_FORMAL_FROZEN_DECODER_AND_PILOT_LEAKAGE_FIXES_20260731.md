# Formal 冻结 decoder、pilot 泄漏与 E8 成功条件统计修复（2026-07-31）

## 本轮决定

- 冻结器选出的 decoder 必须进入 formal 的实际执行路线，而不是只写入报告；
- decoder 必须在每个模型窗口完成后、ownership/core commit 和下一窗 cursor 更新之前生效；
- decoder 选择仍使用当前 pilot 汇总口径，本轮不继续调整训练样本组成权重；
- 修复 pilot 误用 M4Singer test、E8 失败样本伪装成零传播效应等其余 review 问题。

## 1. 冻结 decoder 的正式执行路线

Formal 从 `frozen_parameters.json:selected_decoder` 读取并验证 decoder。支持：

- `raw`
- `official`
- `joint_start_end`
- `topk_sequence`
- `weighted_isotonic`

对于三个 research decoder，`infer_slice()` 先保存同一 Qwen 前向的 raw、official 和 top-K evidence，然后立即重解码本窗全部候选单位，并把结果投影到 `fixed_local_*` / `fixed_global_*`。随后 `windowed_alignment()` 才执行：

1. context/core/lookahead 切分；
2. core ownership 与 commit；
3. next-window transcript cursor；
4. stable suffix、attempt、E8 continuation 和 E9 beam state 更新。

因此 decoder 会改变真实串行轨迹，而不是只修改最终 alignment 文件。

Formal 若冻结 decoder 不是 `official`，每个 item 会按 B4 的冻结窗口计划先执行一次 model-backed baseline rerun，产物写入：

```text
formal/items/<item_id>/frozen_decoder_baseline/alignment.json
```

该 rerun 的 rows/trace 成为 E1 以及 E5–E9 的 operational baseline。E0 仍使用原始统一 B4 evidence 做 decoder 公平比较，避免不同串行轨迹破坏 decoder 离线对照。

局部 request、E7 注入、E8 continuation、E9 每个 beam branch 也统一读取 `selected_decoder_name`。request cache identity 已加入 decoder 名称、top-K 和 beam size。

## 2. Pilot/test 隔离

Pilot 选择器现在排除：

- `split in {test, heldout}`；
- `selection_role in {heldout, m4_test}`；
- 显式 `pilot_selection_eligible=false`。

M4Singer synthetic-long 保留源 `split`，因此由 test 构造的 synthetic-long 同样不会进入 pilot。显式使用 `--item-id` 指向上述 item 时，pilot 直接报错，不再绕过隔离规则。

同时修复 duration-diverse 抽样公式：当可用 item 数少于 `pilot_items_per_dataset` 时，旧公式可能重复位置并少取样本；现在按实际 `take` 数均匀覆盖。

## 3. E8 传播失败统计

Continuation 失败时仍保留：

- 局部候选；
- static splice alignment；
- static full/downstream metrics；
- 异常类型与错误文本；
- `eligible_for_selection=false`。

但以下字段改为 `null`：

- serial-continuation downstream metrics；
- downstream delta vs baseline；
- downstream delta vs static splice。

项目级传播效应均值只对 `propagation_status == complete` 的候选计算，并同时报告 complete count、failure count、failure rate 和明确 conditioning。失败后的静态零变化不再稀释真实传播效应。

## 4. Provenance

`item_summary.json` 新增：

- `frozen_decoder`
- `frozen_decoder_route.decoder`
- `frozen_decoder_route.source`
- `decoder_applied_before_serial_commit`
- `window_count`
- 非 official rerun 的 `wall_sec`

`research_summary.json` schema 更新为 `alignment_research_suite_summary_v3_frozen_decoder_route`，包含 `frozen_decoder_execution` 和每个 item 的 route。

## 5. 验证

已完成：

- Python `compileall`；
- 全部 shell `bash -n`；
- 新增 pilot test 隔离、抽样、frozen decoder 参数贯通、research decoder fixed-field 投影、E8 成功条件统计测试；
- 除本地环境缺少 `pypinyin` 而无法收集的 3 个既有模块外，其余 266 项测试通过。

尚未完成：真实 Qwen/R2 GPU 前向下的非 official formal baseline rerun、显存/速度和最终指标。服务器运行必须使用全新 `OUT_ROOT`。
