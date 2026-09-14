# 成品异常审计（生成，勿手改）

> 三个阶段都数一遍：**模型原始** → **上游修补后** → **用户看到的成品**。按变体分开统计。

## 批：`20260814_ktv_current_silence`（33 首不同的歌 × 1 个变体 = 33 份文件）

**交付形态 `r2/vocal/windowed`**（33 份文件 / 33 首不同的歌）

| 阶段 | 字数 | 零时长 | 零时长占比 | 负时长 | 字间重叠 | 开始时间倒退 | 最长连续坍缩 | ≥2s 长音 |
|---|---|---|---|---|---|---|---|---|
| 模型原始 | 13735 | 613 | 4.5% | 870 | 1560 | 903 | 19 | 649 |
| 上游修补后 | 13735 | 2236 | 16.3% | 0 | 14 | 9 | 251 | 127 |
| **成品** | 13735 | 2240 | 16.3% | 0 | 0 | 0 | 251 | 125 |

- 被流水线挪动 ≥0.2 秒的字数：**2085**，其中 **2056** 个模型自己就是低把握 ⇒ 挪动多发生在该复核的地方；
- **自检漏检**：33 / 33 份文件「有警告但结构错误记 0」⇒ 只看 status 的下游会以为一切正常。

最严重的文件（按成品零时长字数）：

| 歌 | 变体 | 字数 | 成品零时长 | 最长连续坍缩 | ≥2s 长音：原始→成品 | 自检 |
|---|---|---|---|---|---|---|
| 初音未来的消失 | r2/vocal/windowed | 561 | 429 | 251 | 126 → 5 | `warning`（结构错误 0、警告 7） |
| I See Fire | r2/vocal/windowed | 311 | 274 | 199 | 69 → 7 | `warning`（结构错误 0、警告 8） |
| 画下灯塔水母 | r2/vocal/windowed | 532 | 207 | 135 | 41 → 3 | `warning`（结构错误 0、警告 7） |
| 冬之花 | r2/vocal/windowed | 222 | 139 | 113 | 35 → 3 | `warning`（结构错误 0、警告 8） |
| 炉心融解 | r2/vocal/windowed | 326 | 138 | 41 | 52 → 5 | `warning`（结构错误 0、警告 7） |
| 皱鳃鲨 | r2/vocal/windowed | 261 | 113 | 38 | 43 → 3 | `warning`（结构错误 0、警告 8） |
| 红日 | r2/vocal/windowed | 534 | 86 | 5 | 5 → 2 | `warning`（结构错误 0、警告 5） |
| 月半小夜曲 | r2/vocal/windowed | 388 | 85 | 11 | 22 → 5 | `warning`（结构错误 0、警告 8） |

## 批：`20260814_ktv_B4`（25 首不同的歌 × 12 个变体 = 300 份文件）

⚠️ 这是研究矩阵（变体：r0/mix/full, r0/mix/windowed, r0/vocal/full, r0/vocal/windowed, r1/mix/full, r1/mix/windowed, r1/vocal/full, r1/vocal/windowed, r2/mix/full, r2/mix/windowed, r2/vocal/full, r2/vocal/windowed），**不是一批不同的歌**；把文件当歌数会把同一首算好几遍（2026-09-14 19:40 我就差点把两条不同管道读成结论一致）。下面只按**交付形态**读，合并数仅作参考。

**交付形态 `r2/vocal/windowed`**（25 份文件 / 25 首不同的歌）

| 阶段 | 字数 | 零时长 | 零时长占比 | 负时长 | 字间重叠 | 开始时间倒退 | 最长连续坍缩 | ≥2s 长音 |
|---|---|---|---|---|---|---|---|---|
| 模型原始 | 10909 | 509 | 4.7% | 718 | 1328 | 775 | 12 | 559 |
| 上游修补后 | 10909 | 1869 | 17.1% | 0 | 10 | 7 | 251 | 105 |
| **成品** | 10909 | 1871 | 17.2% | 0 | 0 | 0 | 251 | 103 |

各变体的**成品零时长占比**（形态差别可能比批次差别还大）：

| 变体 | 文件数 | 模型原始 | 成品 | 成品最长连续坍缩 | ≥2s 长音：原始→成品 |
|---|---|---|---|---|---|
| r0/mix/full | 25 | 16.2% | **42.9%** | 271 | 1841 → 167 |
| r0/mix/windowed | 25 | 16.1% | **37.1%** | 316 | 860 → 149 |
| r0/vocal/full | 25 | 12.9% | **34.8%** | 218 | 1456 → 123 |
| r0/vocal/windowed | 25 | 11.2% | **27.2%** | 310 | 626 → 69 |
| r1/mix/full | 25 | 13.3% | **40.0%** | 183 | 1929 → 172 |
| r1/mix/windowed | 25 | 14.5% | **33.1%** | 316 | 999 → 161 |
| r1/vocal/full | 25 | 11.0% | **33.5%** | 213 | 1478 → 141 |
| r1/vocal/windowed | 25 | 9.9% | **26.3%** | 313 | 675 → 90 |
| r2/mix/full | 25 | 10.6% | **34.8%** | 194 | 1622 → 161 |
| r2/mix/windowed | 25 | 10.3% | **24.8%** | 331 | 684 → 116 |
| r2/vocal/full | 25 | 5.5% | **25.4%** | 147 | 1241 → 112 |
| r2/vocal/windowed | 25 | 4.7% | **17.2%** | 251 | 559 → 103 |

- 被流水线挪动 ≥0.2 秒的字数：**1761**，其中 **1738** 个模型自己就是低把握 ⇒ 挪动多发生在该复核的地方；
- **自检漏检**：25 / 25 份文件「有警告但结构错误记 0」⇒ 只看 status 的下游会以为一切正常。

最严重的文件（按成品零时长字数）：

| 歌 | 变体 | 字数 | 成品零时长 | 最长连续坍缩 | ≥2s 长音：原始→成品 | 自检 |
|---|---|---|---|---|---|---|
| 初音未来的消失 | r2/mix/windowed | 561 | 559 | 331 | 121 → 1 | `warning`（结构错误 0、警告 8） |
| 初音未来的消失 | r0/mix/windowed | 561 | 553 | 312 | 146 → 5 | `warning`（结构错误 0、警告 7） |
| 初音未来的消失 | r1/mix/windowed | 561 | 535 | 316 | 152 → 3 | `warning`（结构错误 0、警告 8） |
| 初音未来的消失 | r0/vocal/windowed | 561 | 509 | 300 | 144 → 6 | `warning`（结构错误 0、警告 8） |
| 初音未来的消失 | r1/mix/full | 561 | 508 | 127 | 201 → 14 | `warning`（结构错误 0、警告 5） |
| 初音未来的消失 | r0/mix/full | 561 | 502 | 106 | 210 → 10 | `warning`（结构错误 0、警告 5） |
| 初音未来的消失 | r1/vocal/windowed | 561 | 494 | 298 | 112 → 6 | `warning`（结构错误 0、警告 8） |
| 难念的经 | r2/mix/full | 680 | 485 | 193 | 202 → 8 | `warning`（结构错误 0、警告 5） |

## 批：`20260816_evaluation_v1_gtsinger_regression_official_all`（84 首不同的歌 × 12 个变体 = 1008 份文件）

⚠️ 这是研究矩阵（变体：r0/mix/full, r0/mix/windowed, r0/vocal/full, r0/vocal/windowed, r1/mix/full, r1/mix/windowed, r1/vocal/full, r1/vocal/windowed, r2/mix/full, r2/mix/windowed, r2/vocal/full, r2/vocal/windowed），**不是一批不同的歌**；把文件当歌数会把同一首算好几遍（2026-09-14 19:40 我就差点把两条不同管道读成结论一致）。下面只按**交付形态**读，合并数仅作参考。

**交付形态 `r2/vocal/windowed`**（84 份文件 / 84 首不同的歌）

| 阶段 | 字数 | 零时长 | 零时长占比 | 负时长 | 字间重叠 | 开始时间倒退 | 最长连续坍缩 | ≥2s 长音 |
|---|---|---|---|---|---|---|---|---|
| 模型原始 | 1189 | 6 | 0.5% | 3 | 47 | 1 | 1 | 4 |
| 上游修补后 | 1189 | 44 | 3.7% | 0 | 0 | 0 | 2 | 4 |
| **成品** | 1189 | 44 | 3.7% | 0 | 0 | 0 | 2 | 4 |

各变体的**成品零时长占比**（形态差别可能比批次差别还大）：

| 变体 | 文件数 | 模型原始 | 成品 | 成品最长连续坍缩 | ≥2s 长音：原始→成品 |
|---|---|---|---|---|---|
| r0/mix/full | 84 | 2.0% | **6.6%** | 2 | 1 → 1 |
| r0/mix/windowed | 84 | 2.0% | **6.6%** | 2 | 1 → 1 |
| r0/vocal/full | 84 | 2.0% | **6.6%** | 2 | 1 → 1 |
| r0/vocal/windowed | 84 | 2.0% | **6.6%** | 2 | 1 → 1 |
| r1/mix/full | 84 | 0.5% | **4.3%** | 3 | 5 → 5 |
| r1/mix/windowed | 84 | 0.5% | **4.3%** | 3 | 5 → 5 |
| r1/vocal/full | 84 | 0.5% | **4.3%** | 3 | 5 → 5 |
| r1/vocal/windowed | 84 | 0.5% | **4.3%** | 3 | 5 → 5 |
| r2/mix/full | 84 | 0.5% | **3.7%** | 2 | 4 → 4 |
| r2/mix/windowed | 84 | 0.5% | **3.7%** | 2 | 4 → 4 |
| r2/vocal/full | 84 | 0.5% | **3.7%** | 2 | 4 → 4 |
| r2/vocal/windowed | 84 | 0.5% | **3.7%** | 2 | 4 → 4 |

- 被流水线挪动 ≥0.2 秒的字数：**14**，其中 **6** 个模型自己就是低把握 ⇒ 挪动多发生在该复核的地方；
- **自检漏检**：39 / 84 份文件「有警告但结构错误记 0」⇒ 只看 status 的下游会以为一切正常。

最严重的文件（按成品零时长字数）：

| 歌 | 变体 | 字数 | 成品零时长 | 最长连续坍缩 | ≥2s 长音：原始→成品 | 自检 |
|---|---|---|---|---|---|---|
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0000 | r1/mix/full | 18 | 4 | 1 | 0 → 0 | `warning`（结构错误 0、警告 3） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0000 | r1/mix/windowed | 18 | 4 | 1 | 0 → 0 | `warning`（结构错误 0、警告 3） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0000 | r1/vocal/full | 18 | 4 | 1 | 0 → 0 | `warning`（结构错误 0、警告 3） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0000 | r1/vocal/windowed | 18 | 4 | 1 | 0 → 0 | `warning`（结构错误 0、警告 3） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0005 | r0/mix/full | 25 | 4 | 2 | 0 → 0 | `warning`（结构错误 0、警告 4） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0005 | r0/mix/windowed | 25 | 4 | 2 | 0 → 0 | `warning`（结构错误 0、警告 4） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0005 | r0/vocal/full | 25 | 4 | 2 | 0 → 0 | `warning`（结构错误 0、警告 4） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0005 | r0/vocal/windowed | 25 | 4 | 2 | 0 → 0 | `warning`（结构错误 0、警告 4） |

## 批：`20260816_evaluation_v1_gtsinger_regression_rawdec_all`（84 首不同的歌 × 12 个变体 = 1008 份文件）

⚠️ 这是研究矩阵（变体：r0/mix/full, r0/mix/windowed, r0/vocal/full, r0/vocal/windowed, r1/mix/full, r1/mix/windowed, r1/vocal/full, r1/vocal/windowed, r2/mix/full, r2/mix/windowed, r2/vocal/full, r2/vocal/windowed），**不是一批不同的歌**；把文件当歌数会把同一首算好几遍（2026-09-14 19:40 我就差点把两条不同管道读成结论一致）。下面只按**交付形态**读，合并数仅作参考。

**交付形态 `r2/vocal/windowed`**（84 份文件 / 84 首不同的歌）

| 阶段 | 字数 | 零时长 | 零时长占比 | 负时长 | 字间重叠 | 开始时间倒退 | 最长连续坍缩 | ≥2s 长音 |
|---|---|---|---|---|---|---|---|---|
| 模型原始 | 1189 | 6 | 0.5% | 3 | 47 | 1 | 1 | 4 |
| 上游修补后 | 1189 | 44 | 3.7% | 0 | 0 | 0 | 2 | 4 |
| **成品** | 1189 | 56 | 4.7% | 0 | 0 | 0 | 3 | 4 |

各变体的**成品零时长占比**（形态差别可能比批次差别还大）：

| 变体 | 文件数 | 模型原始 | 成品 | 成品最长连续坍缩 | ≥2s 长音：原始→成品 |
|---|---|---|---|---|---|
| r0/mix/full | 84 | 2.0% | **8.7%** | 5 | 1 → 1 |
| r0/mix/windowed | 84 | 2.0% | **8.7%** | 5 | 1 → 1 |
| r0/vocal/full | 84 | 2.0% | **8.7%** | 5 | 1 → 1 |
| r0/vocal/windowed | 84 | 2.0% | **8.7%** | 5 | 1 → 1 |
| r1/mix/full | 84 | 0.5% | **5.8%** | 4 | 5 → 5 |
| r1/mix/windowed | 84 | 0.5% | **5.8%** | 4 | 5 → 5 |
| r1/vocal/full | 84 | 0.5% | **5.8%** | 4 | 5 → 5 |
| r1/vocal/windowed | 84 | 0.5% | **5.8%** | 4 | 5 → 5 |
| r2/mix/full | 84 | 0.5% | **4.7%** | 3 | 4 → 4 |
| r2/mix/windowed | 84 | 0.5% | **4.7%** | 3 | 4 → 4 |
| r2/vocal/full | 84 | 0.5% | **4.7%** | 3 | 4 → 4 |
| r2/vocal/windowed | 84 | 0.5% | **4.7%** | 3 | 4 → 4 |

- 被流水线挪动 ≥0.2 秒的字数：**10**，其中 **4** 个模型自己就是低把握 ⇒ 挪动多发生在该复核的地方；
- **自检漏检**：39 / 84 份文件「有警告但结构错误记 0」⇒ 只看 status 的下游会以为一切正常。

最严重的文件（按成品零时长字数）：

| 歌 | 变体 | 字数 | 成品零时长 | 最长连续坍缩 | ≥2s 长音：原始→成品 | 自检 |
|---|---|---|---|---|---|---|
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0005 | r0/mix/full | 25 | 6 | 4 | 0 → 0 | `warning`（结构错误 0、警告 5） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0005 | r0/mix/windowed | 25 | 6 | 4 | 0 → 0 | `warning`（结构错误 0、警告 6） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0005 | r0/vocal/full | 25 | 6 | 4 | 0 → 0 | `warning`（结构错误 0、警告 5） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0005 | r0/vocal/windowed | 25 | 6 | 4 | 0 → 0 | `warning`（结构错误 0、警告 6） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0006 | r1/mix/full | 29 | 6 | 2 | 0 → 0 | `warning`（结构错误 0、警告 5） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0006 | r1/mix/windowed | 29 | 6 | 2 | 0 → 0 | `warning`（结构错误 0、警告 6） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0006 | r1/vocal/full | 29 | 6 | 2 | 0 → 0 | `warning`（结构错误 0、警告 5） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Paired_Speech_Group__0006 | r1/vocal/windowed | 29 | 6 | 2 | 0 → 0 | `warning`（结构错误 0、警告 6） |
