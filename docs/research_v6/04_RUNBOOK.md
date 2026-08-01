# Alignment Research v6 运行手册

## 1. 解压与环境

```bash
cd /home/hyan/LyricAlignment
$PYTHON_BIN -m pip install -e ".[test,qwen-smoke,demo-multilingual]"
```

`pypinyin` 是基础依赖；日文 test demo 还需要 optional dependency `nagisa`。默认路径集中在：

```bash
scripts/research/research_v6_env.sh
```

模型快照必须至少包含 `model.safetensors`、`config.json`、`tokenizer_config.json`，并且 `processor_config.json` / `preprocessor_config.json` 至少存在一个。

可用环境变量覆盖路径：

```bash
export DEMO_ROOT=/home/hyan/Data/lyricalign/test
export M4_SPLITS=train,validation,test
export OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal
```

## 2. 单 Demo smoke

已知 item ID：

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/alignment_research_v6_one \
  scripts/research/run_research_v6_smoke.sh --item-id demo_Chinese_xxx
```

不传 `--item-id` 时，Smoke 按现有选择器取一个 Demo item；这是有意保留的快速链路检查，不承诺每数据集覆盖。数据集覆盖与正式结论由 pilot/formal 完成。

## 3. 全量一条龙

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal \
  scripts/research/run_research_v6_formal.sh --resume
```

Formal 默认执行 manifest 中全部 item，以及每个 item 的全部 eligible local windows、完整 96-unit groups 和 Detector risk spans：

```text
formal local windows/item       = all (0)
formal 96-unit groups/item      = all (0)
formal realign spans/item       = all (0)
```

这里的 `0` 表示不设上限。只有在服务器 pilot 已证明全穷举不可接受、且运行目的明确是受控诊断而非正式完整结论时，才显式设置正整数上限，例如：

```bash
scripts/research/run_research_v6_formal.sh --resume \
  --formal-cases-per-item 2 \
  --formal-max-chunk-groups-per-item 1 \
  --formal-max-realign-cases-per-item 2
```

任何非零上限都必须写入报告并标记为 case-level subsampling；它不删除 manifest item，但不能与默认完整 formal 混称。M4 train/validation/test、MIR selection role 和 training exposure 会分开汇报。


## 4. Pilot 冻结与降级策略

Pilot 的作用是：在 formal/held-out 之前固定 Detector 模型、risk/repairable/safe-boundary 阈值、decoder 和 E8 候选选择规则，避免根据正式结果反向调参。它不是“必须全部成功才允许继续”的 gate。

Pilot 选择器会排除 `split=test/heldout`、`selection_role=heldout/m4_test` 和 test-derived synthetic-long。若显式 `--item-id` 指向这些 item，pilot 会报错；请使用 development/train/validation 或无正式 GT 角色的 Demo 做 smoke。

冻结器按以下顺序处理：

1. 使用 pilot 中成功 item 的 source-song train/calibration 证据；
2. 某一曲线或模型缺失时，使用预先写死的 fallback；
3. 仍生成 `frozen_parameters.json`，并写入 `selection_effectiveness.level`：`normal_pilot_freeze`、`degraded_best_effort_freeze` 或 `default_fallback_freeze`；
4. `formal_run_is_allowed` 保持为 true，formal 继续执行；正式报告必须同时呈现 warnings 和证据量。

因此，小规模或部分失败 pilot 仍能得到最终结果，但参数选择可信度较低，不能与正常 pilot 冻结混为同等证据。

## 5. 分离终端运行

```bash
cd /home/hyan/LyricAlignment
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal \
SESSION=lyricalign-rv6-formal \
  scripts/research/start_research_v6_detached.sh formal --resume
```

进入：

```bash
tmux attach -t lyricalign-rv6-formal
```

退出而不中断：`Ctrl-b`，再按 `d`。

状态：

```bash
scripts/research/watch_research_v6.sh \
  /home/hyan/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal
```

## 6. Resume 与失败恢复

流水线阶段写入 `state/<stage>.json`。E2–E9 还各自写 phase JSON；`item_summary.json` 只有在包含本次请求的全部 phases 时才整体跳过。

```bash
scripts/research/run_research_v6_formal.sh --resume
```

修改算法语义后应使用新 `OUT_ROOT`，避免不同版本产物混合。单 phase 失败会保留已完成 phase 与 `failure.json`。

## 7. 输出

```text
manifest/                    清单、split/role/training exposure 与审计
baseline/                    B4 raw/top-K/official 统一证据
pilot/                       source-song train/calibration 参数试探
frozen_parameters.json       best-effort 冻结结果、效力等级、warning、Detector/阈值/decoder
formal/                      E0–E9 item 与项目级汇总
formal/items/*/frozen_decoder_baseline/  非 official 冻结 decoder 的真实串行 baseline
formal_report.md             E0–E9 实际指标报告
visuals/visual_index.md       可视化导航
evidence/*_full.tar.gz        全量证据
evidence/*_light3m.tar.gz     <=3MiB 轻量证据
logs/                         阶段日志
```

## 8. 数据完整性核查

```bash
python - <<'PY'
import json, collections
from pathlib import Path
p=Path('/home/hyan/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal/manifest/experiment_manifest.jsonl')
rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
print('items', len(rows))
print('dataset', collections.Counter(r['dataset'] for r in rows))
print('dataset/split', collections.Counter((r['dataset'], r.get('split')) for r in rows))
print('role', collections.Counter((r['dataset'], r.get('selection_role')) for r in rows))
print('training exposure', collections.Counter(bool(r.get('training_exposure')) for r in rows))
PY
```

正式报告必须同时给出 `manifest_item_count`、`selected_item_count`、`completed_item_count`、`failed_item_count` 和失败清单。
