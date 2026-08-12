# Runs

仓库内 `runs/` 只保留轻量登记（README.md 与 `.gitkeep`）；**具体 run 数据严禁放在工作目录**，
统一存放于数据目录 `/home/hyan/Data/lyricalign/runs/`（参考 AST 的 runs 管理模式）。

Git 只跟踪 `runs/README.md` 与 `runs/**/.gitkeep`（见 `.gitignore`）；run 的轻量 manifest/结论由
数据目录内的对应 run 保存，不进入仓库。

## 数据目录中的 run 列表

数据根：`/home/hyan/Data/lyricalign/runs/`

- `realign_recovery_20260812_20260811T202813Z/`：Realign Recovery 主 run（oracle/e3–e8/closed_loop）。
- `research_v7_align_behavior/`：research_v7 长 slot/region 行为（含 smoke 产物，2026-08-12 合并入数据目录）。
- `research_transition_recovery_detector_20260807/`：transition detector 20260807。
- `research_transition_recovery_detector_20260808_corrected/`：20260808 corrected。
- `research_transition_recovery_detector_20260809_second_supplement/`：20260809 second supplement。
- `research_transition_recovery_detector_20260809_signal_completion/`：20260809 signal completion。
- `research_transition_recovery_detector_20260810_realgt_expansion_handoff/`：20260810 realgt expansion handoff。
- `data_preparation/`：数据集预处理 run 摘要（20260721–20260723）。
- `evaluation/`：评估 run 摘要（20260722–20260724）。
- `smoke/`：旧 smoke 摘要（20260719–20260721）。

## 约定

- 新 run 一律写入数据目录，工作目录不产生 run 数据；如需登记，在数据目录内生成 `run_summary.json`/README。
- 代码/脚本引用 run 时使用数据目录绝对路径（`/home/hyan/Data/lyricalign/runs/...`）。
