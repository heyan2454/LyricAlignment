# 阶段 B 进展 —— align_behavior 框架与真实 executor 打通

**日期：2026-08-03 · 计划：docs/research_v7_align_behavior/**

## 已完成
- **契约/mutation 核心**（`src/lyricalign/research_v7/`）：
  - `requests.py`：v7 `AlignmentRequest`（audio/text/slot/mutation/model/checkpoint/lineage）
  - `mutations.py`：extra/missing/replace/no_match 百分比扰动 + DonorSpec/MutationCatalog（固定 seed）
  - `attempt.py`：`AlignmentAttempt`/`EvidencePack` + `run_request` 可穿行骨架
- **manifest 生成**（`scripts/research_v7/build_behavior_manifest.py`）：从 M4_LABELS 真实歌词生成
  合法 baseline + 各百分比 mutation 的行为 manifest（extra/missing/replace/no_match），
  供批量行为实验。
- **批量 run 骨架**（`scripts/research_v7/run_behavior_suite.py`）：消费 manifest → 批量构造
  v7 request → 注入 executor → 写 evidence（含 sparse-slot 骨架）。
- **真实 executor**（`src/lyricalign/research_v7/real_executor.py`）：importlib 复用
  `align_qwen_fa_serial_demo` 的 `load_model`(r2 LoRA+projector) + `infer_slice`/`full_alignment`，
  只吃 numpy 音频 + 文本字符列表 → 逐字符 fixed 起止几何，不依赖 SERIAL/Demucs。
- **测试**：`tests/research_v7/` 12 passed（契约/ mutation / manifest / suite smoke）。

## 真实对齐 smoke（已验证）
- 用 r2（`step-000750`）对 M4Singer `Bass-2#DEAR JOHN#0001`（"将心情化妆成初恋"，8 字）
  跑 `infer_slice`，得到逐字符 fixed 几何：
  - `将` fixed 0.24–0.48s（raw/official 同）… `恋` fixed end 2.72s
  - 模型加载+推理 elapsed ≈ 7.6s；evidence 已存
    `evidence/research_v7_stageA/real_smoke.json`（la_data, commit 64681c2）。
- 结论：**real executor 链路打通**，阶段 B 具备真实验证不合法输入行为的能力基座。

## 待办（资源相关，留 pilot/后续）
- 真实全量行为采集（formal GT behaviour）：对完整 mutation 曲线 + strict-serial P1 +
  sparse-slot S 跑真实模型（需 GPU 批量、冻结 pilot 比例/donor manifest）。
- collect_alignment_behavior / analyze_alignment_behavior / verify_research_v7_outputs
  （聚合、failure taxonomy 统计、校验）。
- 更新 09 报告完成门槛（阶段 B 的 P1/S/百分比等标记进行中/待跑）。

## 状态小结
- 阶段 A（历史结论修复）已全量完成并归档。
- 阶段 B 已建立 契约/扰动/manifest/run/real-executor 全骨架 且真实单 case 验证通过；
  核心行为数据采集（真机批量）pending，属资源密集型，建议按 pilot 流程冻结后执行。
