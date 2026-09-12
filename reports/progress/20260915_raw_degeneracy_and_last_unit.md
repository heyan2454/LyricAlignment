# raw 负时长取证 + 末字分层的真值验证（2026-09-12 第 15 轮）

> 数字由 `runs/20260912_raw_degeneracy/RAW_DEGENERACY.json` 与 `runs/20260912_last_unit_validation/LAST_UNIT.json` 生成。纯 CPU、零新增前向。

## 1. raw 阶段的负时长是什么

批次 `20260814_ktv_current_silence`：13,735 单元 / 33 首；**负时长 870（6.33%）**、零长 613。

| 语言 | 单元 | 负时长 | 比率 | 幅度中位 | 最坏 | 受影响歌数 | 其中后来被钉锚点 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chinese | 7,206 | 79 | 1.1% | 2.16s | -67.12s | 10 | 29.1% |
| Cantonese | 2,439 | 183 | 7.5% | 1.04s | -68.8s | 5 | 0.0% |
| English | 2,108 | 173 | 8.2% | 2.96s | -71.76s | 6 | 43.4% |
| Japanese | 1,982 | 435 | 21.9% | 5.2s | -105.52s | 6 | 33.8% |

- **普通话最干净（1.1%）**，日文词单元最差（22.6%），英文 word 8.2%、中文字符 3.0%。
- **不是量化格点的抖动**：幅度 >1s 的占 70.6%、中位 2.48s、p90 65.52s、最长 105.52s；只有 2.8% 在 0.08s 格点内。
- **也不是接缝局部现象**：按在窗口中的位置分组，负时长率 window 1st unit 5.9%、2nd-3rd 4.3%、4th-6th 2.9%、later 6.5%（平坦）。

### 机制拆分（含对我自己上一版假设的否证）

- 我先前猜"起点与终点来自不同窗口"能解释大头：实测**只解释 23.1%**（201/870 的 raw 起点与终点落在不同 core 区间）⇒ 多数负时长是**同窗口内的起止倒序**（中位 2.5s），少数是跨窗口错配（最大 105.5s，`初音未来的消失`）。
- 结论：**两个子群要分开治理**——①同窗口小幅倒序（约束解码/单调性即可消除）；②跨窗口起止混配（是窗口→全局组装时的索引 bug，量级到分钟级，必须代码修）。

### 它是后续塌陷的前兆吗（这是能否省下重解码算力的关键）

- 是，且很强：raw 退化单元后来被钉到窗口锚点的比例 34.9% vs raw 干净单元 3.5% ⇒ **lift 10.075×**；到 fixed 阶段变为退化的比例 75.8% vs 9.1% ⇒ **lift 8.347×**。
- 且**方向在每首歌内都成立**：25/25 首歌里 raw 退化单元的塌陷率都高于其干净单元（符号检验，无跨歌混杂）。
- 反向覆盖：最终塌陷的 2,236 单元里 50.3% 在 raw 阶段就已经退化 ⇒ **用 raw 自检（起止顺序）就能提前拦下一半塌陷**，不需要真值也不需要额外前向。

## 2. 联合求解对"每项最后一个单元"是帮忙还是帮倒忙（GTSinger 人工真值）

30,600 单元 / 2016 条序列（序列键含 run；漏掉 run 会把不同 run 的同名单元混进一条序列，让单调约束互相打乱——本轮第一版就踩了这个，报出的 joint 结果因此偏低，已修正）。

| 系统 | 全部 hit@100 | 首单元 hit@100 | 中间 hit@100 | 末单元 hit@100 | 末单元·长音 hit@100 |
|---|---:|---:|---:|---:|---:|
| `raw_none` | 82.1% | 64.1% | 84.0% | 74.8% | 55.9% |
| `shipped_official` | 80.4% | 64.1% | 82.0% | 74.6% | 55.9% |
| `joint_solve_alpha0` | 82.4% | 66.9% | 84.1% | 74.8% | 55.9% |

| 系统（MAE(end)） | 全部 | 首单元 | 中间 | 末单元 | 末单元·长音 |
|---|---:|---:|---:|---:|---:|
| `raw_none` | 77.60ms | 119.90ms | 66.80ms | 177.70ms | 372.20ms |
| `shipped_official` | 72.20ms | 74.60ms | 64.10ms | 175.50ms | 371.80ms |
| `joint_solve_alpha0` | 68.30ms | 59.40ms | 61.00ms | 173.40ms | 371.40ms |

- 联合求解**不伤末单元**：74.8% vs raw 74.8%（持平），并且改善首单元 64.1%→66.9%（+2.78pp）与总 MAE 77.60ms→68.30ms。
- **末单元·长音（n=708）三个系统完全同分**（55.9% / 55.9% / 55.9%，MAE 372.20ms）⇒ 与第 11 轮声学锚点实验一致：**这一层不是后处理能修的**，必须换解码信息（右上下文/长音 offset 训练信号）。
- 对上线的含义：联合求解作为**结构 gate 的实现**是安全的（不牺牲末单元，改善首单元与全局 MAE），但别指望它提升长音尾边界精度。

## 3. 与前几轮的接续（本轮把三条独立证据串成一个诊断链）

- 第 6/13/14 轮：退化在 raw 与 fixed 两处产生 ⇒ 本轮给出 raw 侧的**性质**（不是格点抖动、不是接缝、两个子群）与**可用的早期信号**（raw 起止倒序 ⇒ 塌陷 lift 8–10×、覆盖一半塌陷）。
- 第 4/5/11 轮：末字/长音尾边界失效 ⇒ 本轮在人工真值上确认**后处理无法修这一层**（三系统同分），并同时排除了"联合求解会伤末字"的顾虑。
- 可立即执行的两件事（都不需要 GPU）：
  1. 交付前对 timeline 做 **raw 起止顺序自检**（lift 8.3× 且覆盖一半塌陷，等于免费的召回器）；
  2. 把跨窗口起止混配（最大 105s）作为独立 bug 立项修：它不是解码问题而是窗口→全局组装的索引问题。

## 3b. 根因落地：倒序被**预钳位**转成零长，两个现有计数器都看不见

- `src/lyricalign/demo/karaoke.py` 的 `append_strict_core_commits` 在进入重叠压缩之前先做`original_end = min(max(fixed_end, original_start), duration)` ⇒ **end 不可能小于 start**：下游 selected/final 的负时长实测都是 0/0。
- 于是 870 个 raw 倒序里 **595（68.4%）变成了零长单元**，另有 1,112 个零长来自原本干净的单元（钉锚点/压缩路径）。这解释了第 13 轮的 `net_added_by_fixed=+807` 中约 73.7% 的来源。
- **为什么一直是静默的**：钳位使 `original_duration` 变为 0，而`overlap_compression_collapsed_to_zero` 的定义要求 `original_duration > 0`；若该行的起点已在上一单元尾端之后，连 `overlap_compressed` 也不会置位 ⇒ **两个计数器同时漏计**（第 14 轮的 per-stage 观测 + 本轮 `start_after_end_at_*` 警告补上了这个洞，复现用例见 `tests/test_inversion_clamp_observability.py`）。

| 语言 | raw 倒序 | 被钳成零长 |
|---|---:|---:|
| Japanese | 435 | 315 |
| Cantonese | 183 | 98 |
| English | 173 | 127 |
| Chinese | 79 | 55 |

- **建议的策略决定**（不改行为，先让人看到）：对 raw 倒序单元不要静默钳成零长，而是（a）交换 start/end 或按下一单元起点重排，(b) 标记为 `needs_redecode` 交给触发器（第 15 轮已证明这批单元后来塌陷率 lift 8–10×），并至少 (c) 计入 summary 的 `start_after_end_units`。

## 4. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_raw_degeneracy_forensics.py
PYTHONPATH=src python scripts/evaluation/run_last_unit_validation.py
PYTHONPATH=src python scripts/evaluation/report_raw_degeneracy.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_raw_degeneracy_forensics.py
```

