# 2026-07-27 Inline Realign 归档验证

## 1. 验证对象

本验证覆盖本次新增或修改的：

- official B0–B3 基线矩阵；
- 提交前 shadow 诊断；
- 稳定段、稳定前缀和 anchor 失败分解；
- exact / +2 上下文 local realign shadow；
- Demo、M4Singer、MIR-1K manifest；
- smoke / formal 一条龙入口；
- 有限证据收集；
- official O0/O1 一次编码渲染。

## 2. 静态与回归测试

```text
python -m compileall -q src scripts tests
结果：passed

find scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
结果：passed

PYTHONPATH=src pytest -q \
  --ignore=tests/test_audio_contract.py \
  --ignore=tests/test_m4singer_preparation.py \
  --ignore=tests/test_mir1k_partial_align.py
结果：158 passed in 6.90s

PYTHONPATH=src pytest -q tests/test_inline_realign_pipeline.py
结果：11 passed
```

完整 `pytest` 未能进入执行阶段，因为当前归档容器没有安装 `pypinyin`，以下三个既有测试文件在 import 时被阻断：

```text
tests/test_audio_contract.py
tests/test_m4singer_preparation.py
tests/test_mir1k_partial_align.py
```

这属于验证环境依赖缺失，不应被记为这些测试已通过，也不是本次新增代码产生的断言失败。

## 3. 无模型流水线 Smoke

使用临时 WAV、MIR-1K selection、M4Singer label 和字符 GT 运行 manifest 构建：

```text
item_count: 4
mir1k: 1
m4singer native: 2
m4singer synthetic-long: 1
variant_set baseline_matrix: 2
variant_set official_primary: 2
heldout: excluded
```

使用人工构造的异常 alignment 运行有限证据收集：

```text
cap: 1 MiB
mode: full
item_count: 1
character_row_count: 100
window_row_count: 1
case_row_count: 1
archive_size: 3866 bytes
```

证据包包含 pipeline request/status/complete 元数据，不包含音频、视频、权重和完整日志。

## 4. Partial Failure 恢复验证

模拟已有部分 item 失败、但 `experiment_summary.json` 已生成：

```text
03_collect: executed
pipeline_complete.status: partial_failure
pipeline return code: 1
evidence archive: generated
```

因此单个样本失败不会使已完成结果无法收集；同一命令重跑时仍依据分支 request hash 恢复。

## 5. FFmpeg 实际渲染 Smoke

使用 2 秒临时音频和两份 official alignment 运行默认 review comparison：

```text
branches: official_no_realign, official_realign
encoding_passes: 1
profile: review
primary_link_method: hardlink
output_size: 22434 bytes
```

`decoder_realign_demo.mp4` 与 comparison 文件 link count 均为 2，确认没有重复保存第二份视频内容。

## 6. 尚未完成的验证

当前容器没有服务器上的：

- Qwen3 Forced Aligner 完整本地 snapshot；
- R2 step-750 checkpoint；
- 真实 M4Singer/MIR-1K/Demo 路径；
- 对应 GPU 运行环境。

因此尚未执行真实模型 inference smoke，也未生成任何关于新方法准确率或听感改善的结论。服务器应先运行：

```bash
bash scripts/demo/run_inline_realign_smoke.sh
```

只有 smoke 的模型加载、全部数据角色、B0–B3、shadow case 和 evidence 都完成后，才启动 formal。
