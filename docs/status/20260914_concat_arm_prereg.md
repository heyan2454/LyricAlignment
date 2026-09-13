# 长上下文臂（拼接 ~20 s 样本再训）预注册 · 2026-09-14

> 目的：在**动手之前**写死假设、主指标与停止规则，避免事后挑样本。本臂由用户在 01:52 明确要求
> （"试一下组合成长样本继续训练，但这批已有结果先保留"）。旧 run 与其全部产物原样保留，新 run
> 用新目录 `20260914_qwen_fa_r2_concat20b_seed20260724`。

## 1. 机制诊断给出的理由（见 `20260914_long_note_mechanism.md`）
- ≥2 s 字符的失败是**弥散 + 系统性偏早**：top-1 概率中位 0.24、熵 3.08 nats、中位带符号误差 **−710 ms**
  ⇒ 模型没有跟踪住长持续音内的时间进度；
- 短句训练是天然成因：每条训练样本只有 ~2–5 s，而产品要处理整首歌（真歌批 16.28% 零长度、
  最长同一时刻块 251 字，都发生在长流上）；
- 12000 步均匀训练**没有**修掉这个悬崖（≥2 s 超容差率 12.4% → 仍 ~12%）。

## 2. 干预
把**同一首歌的相邻短句**在显存里拼接成 ~20 s（上限 28 s，句间插入 0.4 s 真静音），标签按累计偏移
平移（保持单调，最大 bin 远小于 5000）。不落盘新音频（磁盘只剩 25 G，语料 18.8 G）。

| 项 | 值 | 与 20260913 臂的关系 |
|---|---|---|
| 底座 / revision | 官方 `c07281d…` | 相同 |
| 阶段 | r2（投影层 + 上半 LoRA） | 相同 |
| lr | 投影 2e-5 / LoRA 5e-5 | 相同 |
| 调度 | 分段余弦，峰值每周期 ×0.8 | 相同，仅 `cycle_len` 900 |
| 步数 | 3600（= 4 个周期） | 旧臂 12000 |
| 有效批 | 4 × 2 = 8 条 ≈ 190 s 音频/步 | 旧臂 32 条 ≈ 119 s/步 |
| 验证 | 同一份短条目验证集 + 同一漏斗 | **完全相同，用于跨臂可比** |
| 早停 | 关闭（`patience_cycles: 99`） | 主指标是长上下文视图，短集指标可能先降 |

## 3. 主指标（预先指定，只有一个）
**长上下文验证视图**：把验证集条目用**同一个拼接函数**（不同随机种子，与训练无关）合成 ~20 s 样本，
用同一测试口径（`max(|Δonset|,|Δoffset|)` ≤ 0.2s，歌平均）打分。

- 比较对象：旧 `r2/step-000750`（线上在用）与 `r2/step-001110`，以及本臂的 1SE 选点；
- 判定：本臂在主指标上相对旧 750 的**逐歌配对**差值 z ≥ 2 且方向为正 ⇒ 假设成立；
  |z| < 2 ⇒ 判为"长上下文拼接对本任务无收益"，写负结果并停止这条线。


## 3b. 基线实测（2026-09-14 02:26，全量长流视图：418 条 / 15,204 字符 / 29 首歌）

| 存档 | fixed | raw | raw+定向修复 | 可用率(fixed) | MAE(fixed) |
|---|---|---|---|---|---|
| old-r2-1110 | 0.9630 | 0.9676 | 0.9664 | 0.9912 | 63.6 ms |
| old-r2-750 | 0.9626 | 0.9680 | 0.9669 | 0.9911 | 64.0 ms |
| uniform-12000 | 0.9643 | 0.9682 | 0.9680 | 0.9918 | 63.0 ms |

同 29 首歌上「长流 − 短条目」的配对退化：
- old-r2-750：**−0.24 pp**（SE 0.17，z=−1.42，14/29 首变差）；
- uniform-12000（上一臂终点）：**−0.56 pp**（SE 0.24，z=−2.32，15/29 首变差）；
- 两者退化程度之差 −0.32 pp（SE 0.25，z=−1.28，不显著）。

**更正记录**：本报告 02:18 那次汇报里「长流掉 4.1pp」来自 `--limit 24` 的前 24 条（恰好 4 首较难的歌），
是样本选择偏差；全量视图的真实退化只有 0.2~0.6pp。教训：任何视图级结论都必须先确认样本是全体而非前缀。

## 3c. 次要指标（新增，基线给出后才补上，不算事后改口——它只是把机制说清楚）
1. **长流退化量**：同一存档上「长流 − 短条目」的逐歌配对差。上一臂（均匀训练）反而退化更多，
   所以本臂若成立，应当看到这个量**变小甚至转正**；
2. 结构指标（零长度率、最长同一时刻块）；
3. 误差随流内已进行时间的漂移曲线（`drift_profile`，5 s 一桶）。

判定仍以 §3 的主指标为准（相对 old-r2-750 的逐歌配对 z≥2 且为正）。


## 3d. 拼接对齐修复后的基线（权威版，取代 §3b）
发现并修掉一个自身构造缺陷：标签平移按 `round(offset/0.08)` 取整，而音频按标称 0.4 s 间隙拼接，
两者最多差半格（40 ms）⇒ 第一段之后几乎所有字符都被判成"差一格 80 ms"。现在 collator 按记录的
`part_shift_bins` 精确放置每一段，音频与标签**逐位一致**（实测误差 0.00 ms）。

全量长流视图（418 条 / 15,204 字符 / 29 首歌，fixed/raw/raw+修复）：

| 存档 | fixed | raw | raw+修复 | 可用率(fixed) | MAE(fixed) |
|---|---|---|---|---|---|
| old-r2-750 | 0.9608 | 0.9670 | 0.9669 | 0.9911 | 55 ms |
| uniform-12000 | 0.9646 | 0.9696 | 0.9695 | 0.9922 | 53 ms |

- 修复效果：MAE 64/63 ms → **55/53 ms**（伪影消失）；
- **漂移曲线是平的**（uniform-12000，按流内已进行时间）：0-5s 0ms/2.1%，5-10s 0ms/2.9%，10-15s 0ms/3.1%，15-20s 0ms/3.1%，20-25s 0ms/2.8%
  ⇒ 20 s 尺度上模型的时间跟踪没有问题，先前"80 ms 台阶"完全是我的构造伪影；
- 同 29 首歌上「长流 − 短条目」：old-r2-750 **−0.43 pp**（z=−2.18）、uniform-12000 **−0.53 pp**（z=−2.29），
  两者之差 −0.10 pp（z=−0.35，无差别）；
- 长流水平配对：uniform-12000 − old-r2-750 = **+0.38 pp**（SE 0.20，z=+1.87，13/29 首更好）。

**推论（改变本臂的预期）**：20 s 视图上的可改进空间只有 ~0.5 pp，所以真正暴露产品问题的尺度必须更长；
已另跑 60 s 视图基线（`long60_baseline.json`）。若 60 s 上退化明显更大，则本臂的 `target_sec` 应在下一轮
提高到 60 s；本轮（20 s）仍按预注册判定，作为"加长上下文是否有增益"的下界证据。


## 3e. 机制检查项（A/B 双臂必须一起报告，不能只看指标涨跌）
诊断已给出机制：**时长回归到常见值**（≥2s 失败字的区间长度比 0.709、中点偏早 −328ms；
短字符失败反而被拉长到 2.5 倍）。因此上采样臂 B 若真的起效，除了主指标还须看到：
1. **失败子集的长度比向 1 收敛**（≥2s 桶从 0.71 上升）；
2. ≥2s 桶超差率下降（基线 11.06%，配对 SE 见 `error_vs_duration`）；
3. 短字符桶不被恶化（0-0.25s 的长度比不应进一步偏离 1）。
若 1 不成立而 2 成立，说明提升来自别处（例如整体收敛），机制解释需要重写。
测量工具：`scripts/evaluation/duration_ratio_profile.py`（同一 dump 格式即可）。

## 4. 次要指标（只作解释，不作选点）
- 短条目验证集（与旧臂同口径）：预期**不升甚至略降**（分布偏移）；若明显上升是额外收获；
- 结构指标：零长度率、最长同一时刻块（拼接训练应当降低它们，因为模型见过长流且解码不再依赖窗口边缘）；
- 长字符子集（≥1.0 s / ≥2.0 s）超容差率。

## 5. 停止规则与风险
- 训练进程异常退出 ⇒ 记一次 stderr，不自动重试第三次，转人工；
- 磁盘 < 22 G ⇒ 自动降级为仅权重（`disk_floor_gb: 22`），不删任何旧内容；
- 若 06:00 前未跑完 ⇒ 用已有存档照常评估（每 100 步都有完整状态存档）；
- 已知风险：拼接引入的"假边界"（句间突变）可能让模型学到错误的段间跳变。控制手段：句间真静音 0.4 s、
  标签单调性由构造保证、且主指标用同样的拼接视图评分（训练/评测分布一致）。

## 6. 执行
```bash
bash scripts/training/launch_qwen_fa_concat20_20260914.sh   # 已启动（02:04），日志与哨兵在 runs/_launch_logs/
# 完成后：用 report_long_note_mechanism.py / run_funnel_topup.py 出主指标与选点
```
预计 3.36 s/步 × 3600 ≈ 3.4 h + 漏斗评估 ≈ **05:45–06:00 完成**。

## 6. 执行清单（臂跑完后照此执行，判决由代码给、不靠临场读数）
```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
export HF_HUB_CACHE=/home/hyan/Data/lyricalign/models/hf_cache HF_HUB_OFFLINE=1 PYTHONPATH=src
D=/home/hyan/Data/lyricalign/runs
R=$D/20260914_qwen_fa_r2_concat20c_seed20260724          # 拼接臂
A=$D/20260914_qwen_fa_r2_warmstart_control_seed20260724   # A 对照
B=$D/20260914_qwen_fa_r2_warmstart_oversample_seed20260724 # B 上采样

# 1) 长上下文视图（主指标）：一次把基线与两臂放同一个文件里，保证同一视图同一协议
python scripts/evaluation/eval_long_context_view.py --run-dir $A \
  --checkpoint "warmstart-control=$A/checkpoints/step-000600" \
  --checkpoint "warmstart-oversample=$B/checkpoints/step-000600" \
  --batch-size 4 --out results/by_run/20260914_long_context_view/ab_arms.json

# 2) 机制检查（CPU，同一条 300 条长音符富集样本，与已有基线同种子）
python scripts/evaluation/measure_predicted_boundary_acoustics.py --checkpoint $A/checkpoints/step-000600 \
  --limit 300 --context-sec 0.06 --batch-size 4 --device cpu --out results/by_run/20260914_mech_control/metrics.json
python scripts/evaluation/measure_predicted_boundary_acoustics.py --checkpoint $B/checkpoints/step-000600 \
  --limit 300 --context-sec 0.06 --batch-size 4 --device cpu --out results/by_run/20260914_mech_treatment/metrics.json
python scripts/evaluation/duration_ratio_profile.py --dump results/by_run/20260914_mech_control/per_character.jsonl \
  --out results/by_run/20260914_mech_control/duration_ratio.json
python scripts/evaluation/duration_ratio_profile.py --dump results/by_run/20260914_mech_treatment/per_character.jsonl \
  --out results/by_run/20260914_mech_treatment/duration_ratio.json

# 3) 判决（纯读 JSON，不重跑推理）
python scripts/evaluation/warmstart_ab_verdict.py \
  --view results/by_run/20260914_long_context_view/baseline_aligned.summary.json \
  --view results/by_run/20260914_long_context_view/ab_arms.json \
  --duration "warmstart-control=results/by_run/20260914_mech_control/duration_ratio.json" \
  --duration "warmstart-oversample=results/by_run/20260914_mech_treatment/duration_ratio.json" \
  --out results/by_run/20260914_warmstart_ab
```
判决规则（预注册，写在代码里）：**净效应 = 逐歌配对 B vs A**，z≥2 且为正 ⇒ 时长上采样有效；
|z|<2 ⇒ 写"无净效应"的负结果；机制项（失败子集时长比是否向 1 收敛）只解释成因、不参与判决。
