# Patch Notes — Detector Production Audit & Realign Gate Session

本 patch 只新增/更新研究文档，不修改实验实现代码。

## 新增

`docs/sessions/20260812_detector_production_realign_gate/`

- `README.md`
- `00_SESSION_DISCUSSION_RECORD.md`
- `01_REVIEWED_RESULTS_AND_CORRECTIONS.md`
- `02_NEXT_ROUND_EXPERIMENT_PLAN.md`
- `03_CODEX_HANDOFF.md`
- `04_OPENCODE_IMPLEMENTATION_PLAN.md`：OpenCode 实现方案（review 后修订：时间对齐配对 fallback、Demo 脚本正确路径、历史比较 metric bridge、测试覆盖补充）。

## 更新

- `docs/sessions/SESSION_INDEX.md`：加入本 session 入口。

## 合并方式

从 LyricAlignment 仓库根目录解压/复制本 patch 的相对路径即可。

## 重要边界

- 本 patch 不抢先实现下一轮代码；
- Codex 合并后先核实 detector identity、数据 inventory、Test Demo inventory、metric semantics；
- 再给出具体实现计划交给 OpenCode；
- 下一轮范围是 detector production audit + realign behavior/gate，不重新打开旧大消融。
