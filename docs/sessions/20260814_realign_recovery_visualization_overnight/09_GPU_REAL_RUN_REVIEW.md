# 09 GPU 真实运行后 Review（2026-08-14）

> 补充 `08_SESSION_FINAL_REPORT.md`：在用户提供 full-access + GPU 后，真实运行了部分实验。
> 运行数据全部外置 `/home/hyan/Data/lyricalign/runs/20260814_*`；本文件只记录轻量结论/命令，进 git。

## 环境
- GPU：RTX 4080 SUPER 32GB（Qwen 0.6B 显存峰值 ~2.5GB，余量极大）。
- 内存充足（1TiB, ~900Gi avail）；工作区 7.6G 未污染（run 数据均写数据盘）。
- torch 2.8.0 + CUDA；模型 `Qwen/Qwen3-ForcedAligner-0.6B-hf@c07281df` + R2 `step-000750`。

## 真实运行的实验与结果

### E1 multi-realign R-U（40 region × 10 歌 × 5 迭代 = 200 forward, 54s）
- target 位移 ≤200ms：32/40（target 相对稳定）。
- **fixed-context displacement median 320ms / max 4920ms** → R-U 是 coarse proposal、context safety 弱（与 01 文档一致）。
- multi-iteration 整窗平移 artifact（本例 -20ms/iter）→ 当前 `oscillation_or_divergence`/`fixed_point_iteration` 判定需按 signed 轨迹细判（39/40 被判振荡多为整窗偏移）。

### E2 fine-split R-U（one_unit + anchor_gap，各 5 region）
- `recovered_unit_fraction = 1.0`（拆小让 target 全恢复）。
- `context_preservation = False`（每子请求仍 R-U non-sparse，context 仍漂移）。
- → 分区**扩大 target recovery basin**，但 context 保护需 sparse/fixed（R-S / R-CF Stage-B）。

### E3 audio views R-U（base + wider，3 region）
- 全部 forward 完成，**no-GT selector 选中 base**（target±0.5s）3/3，wider 无增益。
- 样本小（3 region），audio-view 相对纯迭代的优势待扩量。

### E4 coarse→fine R-CF（5 region, 20 forward；修复 Stage-B 后）
- **修复前**：Stage-B 5/5 not_constructible（whole-region 校验过严，窗口外 unit 误判）。
- **修复后**：3/5 Stage-B 真正精修，**fixed-context displacement = 0ms**（sparse/fixed 保护 context）。
- 1/5 仍 fail-closed（recrop 窗口内真冲突，正确）；1/5 stage-A 不可构造（非连续 target span）。
- → **核心目标达成**：R-U coarse 定位 + R-CF sparse/fixed 精修 → target 恢复 + context 0 位移。

## 真实运行中发现的实现修复（P0/P1，代码已提交）
| 修复 | 作用 | commit |
|---|---|---|
| multi-realign identity 并入 region_id/song_id（否则同窗不同 region 被算成同一 identity，resume 错误 skip 整批） | 内容寻址契约 | e327251 |
| E4 Stage-B constructibility 作用域 = recrop 窗口（否则 whole-region 使 fine refine 全 fail） | coarse→fine 可构造 | 49edf1c |
| E3 audio-views duration 从 region span 推断（默认 30s 裁剪长音频 target） | crop 不越界 | 38bed1f |

## 科学结论（真实 forward，非 smoke）
R-U 负责 coarse target 定位（target 相对稳定），context 保护弱；R-CF/R-S 的 sparse/fixed refine 把 fixed-context 压到 ~0ms。
**R-U → coarse → fine 组合是有效机制**：目标精修 + 上下文保护。四路可视化（Current / R-U / R-S / R-CF）应能肉眼体现这一差异。

## 复现命令（均需 GPU）
```bash
SNAP=/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064
CKPT=/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750
M=/home/hyan/Data/lyricalign/runs/20260814_E1_screening_manifest.jsonl
PYTHONPATH=src python scripts/unit_realign/run_multi_realign.py --regions $M --out-root <run>/E1 --targets auto:1 --iterations 1,2,3,5 --family R-U --real --model-dir $SNAP --revision main --checkpoint-path $CKPT --limit 40
PYTHONPATH=src python scripts/unit_realign/run_split_realign.py --regions $M --out-root <run>/E2 --partition one_unit --direction L2R --real --model-dir $SNAP --revision main --checkpoint-path $CKPT --limit 40
PYTHONPATH=src python scripts/unit_realign/run_audio_views.py --regions $M --out-root <run>/E3 --views base,wider --real --model-dir $SNAP --revision main --checkpoint-path $CKPT --limit 40
PYTHONPATH=src python scripts/unit_realign/run_coarse_fine.py --regions $M --out-root <run>/E4 --family R-CF --real --model-dir $SNAP --revision main --checkpoint-path $CKPT --limit 40
```

### E4 coarse→fine R-CF 正式扩量（40 region，20s / 87 outcome rows）
- stage-A 可构造 27/40；13 个 fail 原因均为 `invalid_unit_target_span`（筛选 manifest 中 target 非连续 span，fail-closed 正常）。
- stage-A 中 stage-B 可精修 **15/27**；25/40 未到 stage-B（多数为 stage-A 不可构造或 recrop 真冲突，正确 fail-closed）。
- **stage-B 全部 fixed_context_displacement_ms = 0.0ms**（15/15）→ coarse→fine 精修上下文零位移，核心假设在 40 region 上成立。
- stage-B 恢复率：`target_recovered_200` 10/15 (≥1.0 全恢复)，`_500` 12/15，`_1000` 13/15；20s 内瞬时恢复多数目标。
- catastrophic_regression：8/40（需检查是 target 本就远偏，还是 refine 引入；见遗留）。
- **`test_demo_structural_regressions.ok` 恒 false 且 overlap_pairs 在所有 region（含 13 个完全未精修的 stage-A-fail region）均非空** → overlap 是**源 timeline 固有**，非 R-CF 引入，作为"refine 是否引入回归"信号是假阳性（可在 regress 合约中放宽为"相对 refine 前后新增 overlap"）。

## 遗留 / 下一步
- E2 fine-split、E3 audio-view 各扩量到 40 region（0.6B 极快，分钟级）。
- 四路可视化正式渲染（用真实 collection）。
- catastrophic 8/40 归因：区分 target 原本远偏 vs refine 引入。
- E4 Stage-B 真冲突 region：检查 re-crop 前移/后移是否能避免（adaptive recrop）。
