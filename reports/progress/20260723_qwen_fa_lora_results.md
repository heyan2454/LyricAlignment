> **Superseded for current status:** This is a historical 2026-07-23 report. Use `docs/status/project_current.md` and `docs/status/known_issues_20260724.md`. Its valid-only MAE and song-coverage fields are provisional pending metric repair.

# Qwen Forced Aligner LoRA 首轮结果

**状态日期：** 2026-07-23  
**阶段：** R2 全量训练完成；M4Singer sealed test 已有结果；full R2 MIR-1K OOD 尚缺

## 1. 本轮问题

本轮使用 M4Singer 当前 `accepted` 数据作为 `rule-validated weak supervision`，比较：

- R0：raw 模型；
- R1：仅完整训练 `multi_modal_projector`；
- R2：完整训练 projector，并对 audio tower 上半层 attention 注入 LoRA；
- R3：完整训练 projector，并对 audio tower 全部 attention 层注入 LoRA。

language model 与 timestamp classifier 在正式配置中冻结。

## 2. Pilot validation

| 配置 | Step | Song-macro boundary MAE | 相对 R0 |
|---|---:|---:|---:|
| R0 raw | 0 | 169.925 ms | — |
| R1 projector-only | 100 | 90.823 ms | -46.6% |
| R1 projector-only | 200 | 65.699 ms | -61.3% |
| R2 top-half audio LoRA + projector | 100 | **55.247 ms** | **-67.5%** |
| R3 all-layer audio LoRA + projector | 100 | 61.078 ms | -64.1% |

公平的 100-step 比较中，R2 比 R1 低 35.576 ms，约 39.2%。即使 R1 训练到 200 step，R2 的 100-step MAE 仍低 10.452 ms，约 15.9%。在本轮统一 pilot 预算下，R3 没有超过 R2。

辅助指标方向一致：R2 step 100 的 onset/offset MAE 为 43.618/53.524 ms，joint within 80 ms 为 86.372%，IoU 为 82.965%，invalid rate 为 1.085%。

## 3. Full R2 validation

正式全量 R2 使用 17,748 个 train items、1,110 optimizer steps，训练记录 wall time 为 5,620.47 秒。

| Step | Song-macro MAE | Onset MAE | Offset MAE | Joint ≤80 ms | IoU | Invalid |
|---:|---:|---:|---:|---:|---:|---:|
| 250 | 49.403 ms | 39.288 ms | 47.333 ms | 87.852% | 83.740% | 0.776% |
| 500 | 50.026 ms | 40.480 ms | 47.661 ms | 88.286% | 83.920% | 0.960% |
| 750 | 47.733 ms | 39.022 ms | 46.284 ms | 88.648% | 84.144% | 0.849% |
| 1000 | 46.734 ms | 38.639 ms | 45.771 ms | 88.845% | 84.234% | 0.816% |
| 1110 | **46.634 ms** | **38.480 ms** | **45.619 ms** | **88.924%** | **84.248%** | **0.802%** |

程序的 `best_checkpoint.json` 指向 step 1000，因为只有 250 的整数倍周期点参与 selector；最终 step 1110 的 `evaluation.json` 更低 0.100 ms，但未进入 selector。当前自动后处理被报告为使用 validation-best，因此下一步入口默认使用 `best_checkpoint.json` 指向的 step 1000，不根据 test/OOD 反选。

## 4. M4Singer sealed test

full R2 的 sealed test 已产生 `metrics.json`：

| 指标 | 结果 |
|---|---:|
| song-macro boundary MAE | 79.590 ms |
| all-item penalized MAE | 46.551 ms |
| valid-only MAE | 34.294 ms |
| onset / offset MAE | 41.854 / 51.249 ms |
| onset / offset p90 | 60 / 65 ms |
| joint within 80 / 160 / 240 ms | 89.755% / 96.639% / 97.884% |
| mean IoU | 84.579% |
| invalid / missing rate | 0.959% |
| item / song coverage | 99.041% / 100% |

相对此前 pilot R2 sealed test，full R2 的 song-macro MAE 从 100.986 ms 降到 79.590 ms，约改善 21.2%；onset、offset、IoU、joint threshold 与 invalid rate 的方向也一致。

**限制：** supplied `metrics.json` 未记录 checkpoint 路径或 hash。目录创建时间与 watcher 描述支持“训练完成后自动触发”，但仅凭该文件无法独立证明它使用 step 1000。归档不补写不存在的身份。

## 5. MIR-1K OOD

现有 `20260723_qwen_fa_r2_mir1k_ood` 是 full R2 训练完成前生成的 pilot OOD，不能作为最终 full R2 OOD：

- 17 songs / 2,035 characters；
- song-macro MAE 39.671 ms；
- onset/offset MAE 37.361/39.544 ms；
- joint within 80 ms 86.290%；
- IoU 83.205%；
- invalid rate 0.246%。

缺失项是使用同一个冻结 full R2 validation-best checkpoint 运行：

```text
/home/hyan/Data/lyricalign/runs/20260723_qwen_fa_r2_full_mir1k_ood
```

## 6. 当前结论

### 观察结果

- R1 证明 projector-only 有明显适配作用；
- 等 step pilot 中，R2 对 R1 有较大的额外收益；
- 当前预算下 R3 不优于 R2；
- full R2 继续改善 validation，并在 sealed test 上保持提升；
- invalid rate 随主指标改善而下降或维持低位，不是通过增加非法输出换取 MAE。

### 当前结论强度

当前为**单 seed、同一冻结 validation 上的清晰可行性证据**。可以支持“audio tower top-half LoRA 值得进入后续实验”，但还不能支持跨 seed 稳定性，也不能在缺少 final full R2 MIR-1K OOD 时判断最终域外泛化。

### 下一步

使用 `scripts/training/finalize_qwen_fa_r2_manual.sh`：

```bash
bash scripts/training/finalize_qwen_fa_r2_manual.sh inspect
bash scripts/training/finalize_qwen_fa_r2_manual.sh run-ood
bash scripts/training/finalize_qwen_fa_r2_manual.sh summarize
```

该入口不会重复运行 M4Singer sealed test；`run-ood` 默认读取 full run 的 `best_checkpoint.json`，并拒绝覆盖已有 full OOD 目录。
