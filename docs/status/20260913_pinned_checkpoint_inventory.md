# 常用检查点固定清单（生成，勿手改）

> 由 `scripts/evaluation/make_pinned_checkpoint_inventory.py` 生成；逐文件完整 SHA256 与验证曲线见 `results/by_run/20260913_pinned_checkpoints/metrics.json`。**只读生成**：不移动、不删除任何检查点。

## 为什么记这个

- 产品默认路径、批次产物身份与多个分析都指向同一个检查点；一旦它被覆盖或漂移，**历史批次与结论就无法复现**；
- 因此把逐文件指纹固定下来，作为重训前的对照基线。

## 检查点

- 路径：`/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750`
- 大小：50.01 MB（6 个文件）

| 文件 | 字节 | SHA256 |
|---|---:|---|
| `adapter/README.md` | 5,188 | `116df803b116e878…`（全长见 JSON） |
| `adapter/adapter_config.json` | 1,102 | `fbb489d9d84dce87…`（全长见 JSON） |
| `adapter/adapter_model.safetensors` | 13,399,672 | `5605b6dcaa19d1b8…`（全长见 JSON） |
| `checkpoint_identity.json` | 161 | `c702ea332be43e97…`（全长见 JSON） |
| `projector.pt` | 4,201,009 | `92d88b9b975cc510…`（全长见 JSON） |
| `trainer_state.pt` | 32,402,287 | `2db0b7651736c514…`（全长见 JSON） |

## 它的验证曲线（选择依据，全部来自验证集）

| 检查点 | 验证 song_macro_boundary_mae_sec | 训练损失 |
|---|---:|---:|
| 250 | 0.05098 | 0.6973 |
| 500 | 0.04751 | 0.6725 |
| 750 | 0.04716（被选中） | 0.6618 |
| 1,000 | 0.04837 | 0.6594 |

- 该阶段训练预算：**max_steps = 1110**（保存/评估每 250 步；无早停），所以停止原因是**步数预算用尽**，不是收敛判据；
- 记录的最优：step 750，mae 0.04715958845875161；**1000 步起验证指标变差**（见上表）⇒ 单纯加步数无收益。

## 谁在引用它

| 引用处 | 次数 |
|---|---:|
| `scripts/demo/demo_realign_overnight_env.sh` | 1 |
| `scripts/demo/inline_realign_env.sh` | 1 |
| `scripts/evaluation/run_productization_alignment.sh` | 1 |
| `scripts/evaluation/run_regression_rawdec_compare.sh` | 1 |
| `scripts/realign_recovery/visualization/batch_b4_dual.py` | 1 |
| `scripts/realign_recovery/visualization/batch_remaining_current.py` | 1 |
| `scripts/realign_recovery/visualization/rerun_current_silence.py` | 1 |
| `scripts/realign_recovery/visualization/run_ktv_b4_backfill.py` | 1 |
| `scripts/research/research_v6_env.sh` | 1 |
| `scripts/research_transition_recovery_detector/collect_evidence_v3.py` | 1 |
| `scripts/research_transition_recovery_detector/collect_pr_mild.py` | 1 |
| `scripts/research_transition_recovery_detector/collect_propagation.py` | 1 |
| `scripts/research_transition_recovery_detector/preflight.py` | 1 |
| `scripts/research_transition_recovery_detector/recollect_evidence_v3.py` | 1 |
| `scripts/research_transition_recovery_detector/run_demo_analysis.py` | 1 |
| `scripts/research_transition_recovery_detector/run_full_song_baseline.py` | 1 |
| `scripts/research_transition_recovery_detector/run_mir_transfer.py` | 1 |
| `scripts/research_transition_recovery_detector/run_oracle_recovery.py` | 1 |
| `scripts/research_transition_recovery_detector/run_recovery_decomposition.py` | 1 |
| `scripts/research_transition_recovery_detector/run_transition_formal.py` | 1 |
| `scripts/research_transition_recovery_detector/run_transition_smoke.py` | 1 |
| `scripts/research_transition_recovery_detector/train_detector.py` | 1 |
| `src/lyricalign/realign_gate/identity.py` | 1 |
| `src/lyricalign/realign_recovery/frozen_baseline.py` | 1 |

- 以 projector 指纹自检时，**4 个批次的对齐产物**引用了这份投影权重：`20260814_b4review`、`20260814_ktv_B4`、`20260814_ktv_current_silence`、`20260814_viz_B4`

## 重训前的硬要求

1. **保留原件**：新训练写到新的 run 目录，禁止复用/覆盖上面这个路径；
2. **重训后先比指纹**：若 `projector.pt` 或 adapter 权重变了，本清单里引用它的批次必须重新验证，不能继续沿用旧结论；
3. 检查点选择只允许用验证集（本例即 `M4Singer_validation` 的 song 宏平均边界 MAE），test/OOD 不参与选择——这条已由 run 内的 `final_checkpoint_selection.json` 记录。

