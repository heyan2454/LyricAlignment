# Experiment Protocol

## 1. 主任务

```text
audio + known Mandarin lyrics -> character timestamps
```

- 当前只做中文 character-level；
- 不设置 line-level 实验或指标；
- 英文 word-level 是未来独立副线，不与当前结果混合。

## 2. 阶段

1. raw forced-aligner baseline；
2. 数据转换、治理与 split 冻结；
3. projector + timestamp head 过拟合 smoke；
4. projector + timestamp head 正式训练；
5. audio-tower LoRA 层级实验；
6. held-out evaluation。

language-model LoRA 当前不是必要阶段。

## 3. 公平比较

raw 与训练后模型必须保持：

- 相同数据 split；
- 相同音频版本和时长裁剪；
- 相同歌词规范化和字符映射；
- 相同长音频切片与 overlap；
- 相同后处理；
- 相同 metric schema 和容忍度；
- 相同 GT 版本。

若比较 MIR-1K vocal 与 mix，应作为两个独立输入条件，不与模型改动同时变化。

## 4. 数据清洗比较

只有在清洗实质改变数据时才执行正式训练消融：

- `raw-all`：仅做模型所需的最小合法化；
- `clean-all`：应用冻结的数据治理规则；
- `raw-size-matched`：当样本量差异明显时，从 raw 分层抽取与 clean 相同规模。

主比较固定训练 steps、有效 batch、随机种子、validation 和 checkpoint 规则。

## 5. 运行记录

每次 run 保存：

- run id、stage 和 parent run；
- manifest 与 split hash；
- config snapshot；
- model source、revision、adapter 和 checkpoint hash；
- 可训练模块清单与参数量；
- 命令、环境、随机种子；
- input audio type；
- logs、failed items；
- 外部原始响应、预测和 checkpoint 路径；
- attempted / succeeded / failed 数量。

## 6. 产物位置

```text
runs/<stage>/<run_id>/
  run.yaml
  config_snapshot.yaml
  environment.txt
  logs/
  artifact_index.json
  failed_items.csv

results/by_run/<run_id>/
  per_token_metrics.csv
  per_item_metrics.csv
  summary_metrics.json
  metrics_long.csv
```

大型逐样本预测和 checkpoint 位于外部数据盘，由 `artifact_index.json` 引用。

## 7. 覆盖、恢复与 checkpoint

- 默认不覆盖已有 run；
- resume 必须记录原 checkpoint、global step、optimizer 和 scheduler 状态；
- 单样本失败不应中断批量数据治理或推理；
- checkpoint 默认保留 best、last 和少量 milestone；
- 失败后优先修复根因，不通过更换评测口径掩盖问题。
