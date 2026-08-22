# Review 5 — Evaluation V1 产品化准备代码审查

审查范围：
- `scripts/evaluation/build_evaluation_v1_split_manifest.py`
- `scripts/evaluation/audit_new_datasets.py`
- `scripts/evaluation/check_split_access.py`
- `scripts/evaluation/filter_manifest.py`
- `scripts/evaluation/freeze_baseline_identity.py`
- `scripts/evaluation/summarize_evaluation_v1_manifest.py`
- `tests/evaluation/test_evaluation_v1_split.py`

方法：静态读码 + `py_compile` + 单元测试 + 实际 CPU run（未跑模型）。

## 结论

无 P0/P1。所有脚本均为 CPU-only，输出只写外部数据目录，且每个批次带 `cleanup_report.md`。
split manifest 的 leakage audit 通过（group/song 不跨 tier，item_id 唯一）。

## 已验证

- `build_evaluation_v1_split_manifest.py`：
  - MIR-MLPop cmn 官方 Test 全部 sealed，Train 14 首按固定 seed 分 4/10；
  - MIR-MLPop yue 1/1/1 探针；
  - Jamendo 20 首按 hard-case tags 分层 4/10/6；
  - PJS 100 个 song ID 整体 20/50/30，song/speech/manual lab 同组；
  - GTSinger 5 个 song root 整体 1/2/2；
  - manifest SHA-256 稳定。
- `check_split_access.py`：默认拒绝 sealed，`--allow-sealed` 才放行。
- `audit_new_datasets.py`：只统计 operational payload，不把 provenance snapshot 重复计入。
- `freeze_baseline_identity.py`：记录 git commit、模型/checkpoint 默认路径、Python 环境。
- 单元测试：`tests/evaluation/test_evaluation_v1_split.py` 5 passed；相关 `tests/test_split.py` 通过。

## MINOR（不阻塞）

1. `build_evaluation_v1_split_manifest.py` 的 `--no-audio-check` 用 global 替换 `wave_duration_sec`，
   若在同一个 Python 进程内多次调用 main 会保持 no-op；当前 CLI 单次运行无影响。
2. `cleanup_report.md` 由多个脚本追加，格式上“Note”之后出现补充文件列表；可读性可后续统一。
3. `freeze_baseline_identity.py` 的 git status 包含大量未提交历史改动，正式冻结前应先整理工作树或记录 diff hash。
4. `audit_new_datasets.py` 中 iKala 缺少 `checksums.sha256`，属于上游 blocked 状态的合理结果。

## 建议

- 在正式运行前，把 split manifest 的 seed/算法/source revision 写入 manifest 并冻结；
- Jamendo/MIR-MLPop vocal 派生前，不把 raw mixture 当作 operational input；
- sealed runner 必须统一经过 `check_split_access.py --allow-sealed` 才能读取 sealed。
