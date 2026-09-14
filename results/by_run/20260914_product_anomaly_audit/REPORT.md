# 成品异常审计（生成，勿手改）

> 三个阶段都数一遍：**模型原始**（raw）→ **上游修补后**（official_fixed）→ **用户看到的成品**（shipped）。

## 批：`20260816_evaluation_v1_gtsinger_regression_official_all`（120 首歌）

| 阶段 | 字数 | 零时长 | 负时长 | 与上一字重叠 | 开始时间倒退 | 超出音频范围 | 最长连续坍缩 | ≥2s 长音 |
|---|---|---|---|---|---|---|---|---|
| 模型原始 | 2220 | 8 | 4 | 40 | 0 | 4 | 1 | 16 |
| 上游修补后 | 2220 | 36 | 0 | 0 | 0 | 4 | 1 | 16 |
| **成品** | 2220 | 36 | 0 | 0 | 0 | 0 | 1 | 16 |

最严重的几首歌（按成品里的零时长字数排序）：

| 歌 | 字数 | 成品零时长 | 成品最长连续坍缩 | ≥2s 长音：模型原始→成品 | 自检状态 |
|---|---|---|---|---|---|
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 3 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 3 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 3 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 3 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 4 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 4 项） |

- 成品里被流水线挪动 ≥0.2 秒的字：**8** 个（其中 8 个模型自己就是低把握 ⇒ 挪动多发生在该复核的地方）；
- **成品自检的漏检情况**：36 / 120 首歌「有警告但结构错误记为 0」⇒ 严重问题落在 warnings 里，而看 status/structural_errors 的人会以为没问题。

## 批：`20260816_evaluation_v1_gtsinger_regression_rawdec_all`（120 首歌）

| 阶段 | 字数 | 零时长 | 负时长 | 与上一字重叠 | 开始时间倒退 | 超出音频范围 | 最长连续坍缩 | ≥2s 长音 |
|---|---|---|---|---|---|---|---|---|
| 模型原始 | 2220 | 8 | 4 | 40 | 0 | 4 | 1 | 16 |
| 上游修补后 | 2220 | 36 | 0 | 0 | 0 | 4 | 1 | 16 |
| **成品** | 2220 | 36 | 0 | 0 | 0 | 0 | 1 | 16 |

最严重的几首歌（按成品里的零时长字数排序）：

| 歌 | 字数 | 成品零时长 | 成品最长连续坍缩 | ≥2s 长音：模型原始→成品 | 自检状态 |
|---|---|---|---|---|---|
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 4 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 5 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 4 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 5 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 5 项） |
| gtsinger_ZH-Alto-1__Mixed_Voice_and_Falsetto__一次就好__Control_Group__0002 | 17 | 1 | 1 | 0 → 0 | `warning`（结构错误 0 项、警告 6 项） |

- 成品里被流水线挪动 ≥0.2 秒的字：**4** 个（其中 4 个模型自己就是低把握 ⇒ 挪动多发生在该复核的地方）；
- **成品自检的漏检情况**：36 / 120 首歌「有警告但结构错误记为 0」⇒ 严重问题落在 warnings 里，而看 status/structural_errors 的人会以为没问题。
