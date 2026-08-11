# OpenCode 实现总入口：Realign Recovery

**状态：** 可执行 handoff。先完成本文件的 preflight，再按 08--11 分批读取和实现；不要把全部上下文一次塞入一个 Agent 回合。

## 1. 目标与边界

唯一新增研究能力是：在冻结的 Raw serial baseline 上，完成 `detect -> propose -> realign -> judge -> selective writeback -> continue`，并用 real GT 仅在离线阶段评价。

不实现或重开：模型训练、Raw/Official 大矩阵、slot/non-slot、transition、silence planner、decoder 或 detector 特征的大规模比较。D1--D3 仅作为 CPU 小修，不阻塞 E1。

## 2. 阅读与执行批次

| 批次 | 读取 | 允许动作 | 完成门槛 |
|---|---|---|---|
| A | `00`--`08` | 只读盘点、resolved config、GT firewall 测试 | Phase-0 artifacts 全部存在 |
| B | `09` | 实现数据契约、cache、no-GT runner、候选/评价接口 | CPU contract tests 通过 |
| C | `10` 的 E1--E4 | 先 CPU/small-GPU smoke，再 E1/E3/E4 | 有有效 episode 与 candidate bank manifest |
| D | `10` 的 E5--E10 | proposal、quality、writeback、closed loop | GPU cap 内的 formal/diagnostic results |
| E | `11` + `05` | 报告、negative results、free exploration | 完整 freeze/report 或 bounded-insufficient 记录 |

每批完成后写 `implementation_log/PHASE_<name>.md`：命令、输入 SHA、git HEAD/dirty diff、产物、测试、未决项。每批只让一个实现 Agent 持有写权限；review 可只读。

## 3. 首次命令与新运行根

```bash
cd /home/hyan/LyricAlignment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export PYTHONPATH=src
SESSION_ROOT=runs/realign_recovery_20260812_<utc-or-run-id>
```

不得复用或覆盖既有 `runs/research_transition_*` evidence。创建 `SESSION_ROOT` 后立刻写 `00_meta/REPO_STATE_START.json`、环境、dirty diff、引用的 00--11 文件 SHA 与初始 TODO。

## 4. 目录建议（经 Phase 0 mapping 后可最小调整）

```text
src/lyricalign/realign_recovery/       # 纯函数：identity、proposal、candidate、judge、writeback、metrics
scripts/realign_recovery/              # CLI：preflight、run、evaluate、report；不得把逻辑堆进 CLI
tests/realign_recovery/                # 无模型 CPU 合同/回归测试
runs/realign_recovery_.../             # session evidence，不进 Git
```

可以复用 `research_transition_recovery_detector` 的 real-GT、Raw detector、serial state 与已有 retry 封装，但必须通过 adapter 明确版本/输入，不得隐式复制旧的 synthetic-GT routing。

## 5. 全局停止条件

在以下情形停止新 GPU forward，先修复或记录 `blocked`：GT firewall 失败、baseline/config identity 不可解析、cache key 缺 source audio/text/model identity、任何 A/B split 或标签污染、单一 case 造成全队列终止。GPU 达到 12 h 时停止 forward，但继续 11 与 05 所规定的 CPU 工作。
