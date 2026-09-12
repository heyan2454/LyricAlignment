# 落地说明：fixed 阶段时间戳策略开关（2026-09-13）

> 本页是给主线的**可执行改动说明**。所有数字来自
> `reports/progress/20260912_combined_repair_shadow.md` 与 `reports/progress/20260912_fixed_stage_root_cause.md`，
> 由 `runs/20260912_*/` 下的 JSON 生成（不手抄）。

## 1. 背景（一句话）

交付时间线里"没有位置的字"（起止时间相同）来自上游处理器 `_fix_timestamps` 的单调化修补：
当被判为异常的一段**贴着序列任一端**（或两侧好值相等）时，它**用同一个常数填满整段**，
于是整段字的时间被抹平。33 首真歌交付线上 16.28% 的字处于这种状态，最长一段连续 251 字。

## 2. 改动的形态（默认关，行为不变）

`scripts/demo/align_qwen_fa_serial_demo.py` 新增参数：

```
--fixed-timestamp-policy {upstream_repaired,raw_with_targeted_repair,upstream_with_block_repair}
```

- 默认 `upstream_repaired`＝**与今天完全一致**（逐位返回上游值；`tests/evaluation/test_fixed_timestamp_policy_contract.py`
  会守住这个默认值不得被改动、以及"默认路径逐位不变"）；
- `raw_with_targeted_repair`＝**已实测的推荐项**：改用我们自己的 argmax 时间戳，**只重排**被压平/倒序的块，
  块边界由健康邻居决定，其余字保持原位；
- `upstream_with_block_repair`＝实验项，**尚未实测精度**，仅备比较。

选中的策略会写进产物的 `audit.fixed_timestamp_policy`，便于事后区分批次。

## 3. 启用方式

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/demo/align_qwen_fa_serial_demo.py \
    --fixed-timestamp-policy raw_with_targeted_repair \
    ...（其余参数与现有批次命令完全一致）
```

## 4. 启用后如何验收

```bash
PYTHONPATH=src python scripts/evaluation/audit_batch.py --batch <新批次目录>
```

期望：

- `observations.collapse_blocks.blocks == 0`（当前批次为 16 块、641 字、最大 199 字）；
- `checks.structural_legality.value.zero_share` 接近 0（当前批次为 16.28%）；
- 不应出现新的非法类别：当前批次在定向修复后残余非法全部继承自原始阶段（重叠 11.36%→9.44%、
  起点回退 6.57%→4.16%）。

## 5. 实测收益与代价

- **收益**（GTSinger 人工词级真值，30,600 字；对现交付值）：
  误差<0.1s **+1.02pp**、<0.2s **+1.09pp**、<0.25s **+1.01pp**；中位误差不变（40ms）；零长度 4.44%→**0%**；
- **真歌批结构**：零长度 16.28%→**0.00%**，同一时刻长块 16→**0**；
- **代价**：无实测精度代价；该策略**不引入新的违规类别**；
- **明确不要做的事**：不要把"治重叠"或"整体合法化求解"叠加在它之后——实测分别掉 **3.60pp** 与 **4.32pp**
  （0.2s 档），而产品流水线本已处理重叠（现交付值的重叠只剩 0.10%）。

## 6. 边界与回滚

- 精度收益只在 GTSinger（录音室清唱、人工词级真值）上有对照；**真歌批只有结构证据**（无真值）；
- 因此建议先在**单曲**上启用并人工抽听，再决定是否全批切换；
- 回滚＝去掉该参数（默认即旧行为）；也可显式传 `--fixed-timestamp-policy upstream_repaired`。

## 7. 相关产物

- 根因取证：`reports/progress/20260912_fixed_stage_root_cause.md`
- 代价对照：`reports/progress/20260912_shadow_repair_value.md`、`reports/progress/20260912_combined_repair_shadow.md`
- 代码：`src/lyricalign/analysis/monotone_repair.py`
- 测试：`tests/evaluation/test_monotone_repair.py`（14 项）、`tests/evaluation/test_fixed_timestamp_policy_contract.py`（3 项）、
  `tests/evaluation/test_fix_timestamps_collapse.py`（3 项，锁上游行为）
