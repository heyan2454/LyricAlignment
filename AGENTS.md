# LyricAlignment

中英日多语言歌声的已知歌词强制对齐（Qwen Forced Aligner + realign）研究项目。
仓库根固定为 `LyricAlignment/`；日期后缀只用于 archive/run/report，不进入包名。

## Project
- 目标：将已知歌词与歌声音频对齐，输出字符级 timeline；中文优先，扩展英/日。
- 语言/栈：Python ≥3.10；依赖 numpy、PyYAML、matplotlib、pypinyin（见 `pyproject.toml`），
  可选：huggingface_hub + soundfile（qwen-smoke）、nagisa（demo-multilingual）、demucs（demo-demucs）、pytest（test）。
- 入口：核心实现 `src/lyricalign/`；命令入口全部在 `scripts/`（多为 Python，`.sh` 为批次封装）。
- 运行环境：**必须**用 conda 环境 `lyricalign-qwen`（`source /root/miniconda3/etc/profile.d/conda.sh`
  后 `conda activate lyricalign-qwen`；env 实际位于 `/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen`，
  含 transformers 5.15.0.dev0、torch、nagisa、soundfile、numpy、pytest 等全部相关依赖）。
  项目包尚未 `pip install -e .`，当前以 `PYTHONPATH=src` 运行即可（`src/` 为 setuptools package root）。
- 深度上下文从 `AI_SESSION_ENTRY.md` 进入：当前 stage override 指向
  `docs/research_v7_align_behavior/` 的 `README` / `18` Detector V2 冻结计划 / `19` 执行合同 / `22` 2026-08-06 结果复审（completed=false, partial_exploratory=true，Phase A-D 返工）/
  `20` 实现蓝图 / `21` 旧结果纠偏；`17` 及更早文档仅作上一轮实现追溯。

## Commands
```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
# 若需安装项目包：pip install -e .（在 src/ 内）
PYTHONPATH=src python -m pytest -q              # 全量测试（tests/）
PYTHONPATH=src python -m pytest -q tests/research_v7   # 当前主线
python -m compileall -q src scripts             # 语法编译检查
python scripts/environment/capture_environment.py --out <run>/environment_full.json  # 记录运行环境

# 通用 demo（R2 + vocal + windowed），同名媒体文件和同名 TXT
bash scripts/demo/run_qwen_fa_batch.sh /path/to/media_or_folder

# 后续所有命令均在该 conda 环境下执行；demo 类还需 PYTHONPATH=src

# Inline Realign v4（现行版本），先 smoke 再 formal
bash scripts/demo/verify_inline_realign_v4.sh
RENDER_MODE=skip bash scripts/demo/run_inline_realign_smoke.sh
bash scripts/demo/run_inline_realign_render_only.sh smoke <OUT_ROOT>
RENDER_MODE=skip bash scripts/demo/run_inline_realign_formal.sh
bash scripts/demo/run_inline_realign_render_only.sh formal <OUT_ROOT>
```

## Agent 运行约定（多子 agent 并发 / review / 步数限制）

- **多用子 agent 并尽量并行**：主 agent 需要等待所有子 agent 结束后才能继续，因此派发任务时
  一次启动尽可能多的独立子 agent（每任务一个 git worktree 隔离，避免文件冲突）；不同 phase
  或相互独立的模块可并发开发。子 agent 完成任务后返回结构化报告（改动/测试/产物/下一步），
  由主 agent 合并与验收。
- **每阶段/每批完成后启用 review 子 agent**（通常 2 个并行：一个查代码正确性与契约、一个查
  数据一致性与跨模块接线/文档对照）。**review 只关注 P0/P1（CRITICAL/MAJOR）问题**：bug、
  口径不一致、契约违反、会污染结论的数据问题；不纠结信任/防伪类问题（manifest、登记、SHA
  可被有写权限者篡改等），保持"可追溯"即可。MINOR 记 backlog 不阻塞。
- **子 agent 限制步数**：opencode 配置层已设 `agent.general/explore.steps=8`（见 `opencode.json`），
  达到 8 次工具调用后强制转 text-only。派发 prompt 中同时写明 `STEP BUDGET=8`，并要求到步数
  后整理输出：已完成/未完成与原因/关键产物路径/上下文摘要/下一步建议，不得无限循环重试。
- **测试分层**（避免每次都跑全量）：
  - L1 快速层 `tests/research_v7/test_detector_v2_*.py`：每个子 agent 必跑（秒级）；
  - L2 模块层 `tests/research_v7`：跨模块改动时跑（约 1 分钟）；
  - L3 全量 `tests/`：仅 merge agent 与阶段收尾跑。
  子 agent 验收默认 L1 + `compileall -q src scripts` + `git diff --check`。

## Current mainline: research_v7 Detector V2 (enter via `docs/research_v7_align_behavior/`)

实现主体在 `src/lyricalign/research_v7/`。Detector V2 当前已冻结三态区间合同、产品指标和 coverage
gate 骨架，后续实现与实验必须从 `18_DETECTOR_V2_EXPERIMENT_PLAN.md`、
`19_DETECTOR_V2_AGENT_CONTRACT.md`、`20_DETECTOR_V2_IMPLEMENTATION_BLUEPRINT.md` 进入。上一轮
long-slot / region assessor 已跑通真实 formal，但其旧指标边界须按
`21_PREVIOUS_DETECTOR_RESULT_CORRECTIONS.md` 解读。现有 research_v7 命令包括：

```bash
# preflight（只读核对，产出 PRECHECK.json；纯 CPU）
PYTHONPATH=src python scripts/research_v7/preflight_long_slot_region.py --out <run>/preflight/PRECHECK.json

# 纯 CPU 端到端 smoke（合成 >=180s timeline + 60s windows + slots + missing/replace），输出 <run>/smoke/
PYTHONPATH=src python scripts/research_v7/run_long_slot_smoke.py --out-root <run>

# draft 汇总报告（formal_approved 需真实 formal/RUN_MANIFEST.json + 冻结 manifest sha256 才为 true，否则一律 draft）
PYTHONPATH=src python scripts/research_v7/report_long_slot_region.py --run-root <run>

# 弱人声校准（C3，未正式接线前只供试听）
PYTHONPATH=src python scripts/research_v7/export_silence_polluted_weak.py --item-list <jsonl> --out-root <out> [--text-units ...]

# 唯一 evidence collection（review9-6）：train/eval 只消费它，不能直接读原始 items
PYTHONPATH=src python scripts/research_v7/collect_trainable_evidence.py --run-manifest <RUN_MANIFEST.json> --out <collection.json>

# 真实长数据 manifest builder（M4/MIR）+ formal 运行 + GT 评价 + 跨域/质量分析
PYTHONPATH=src python scripts/research_v7/build_long_timeline_manifest.py --m4-manifest <meta.jsonl> --out-root <out> [--missing-ratios 0.10,0.25,0.50]
PYTHONPATH=src python scripts/research_v7/build_mir1k_long_manifest.py --labels <labels.jsonl> --out-root <out>
PYTHONPATH=src python scripts/research_v7/run_behavior_suite.py --manifest <REQUESTS.jsonl> --out-root <run> --real --model-dir <snapshot> --revision main --checkpoint-path <ckpt>
PYTHONPATH=src python scripts/research_v7/evaluate_long_slot_gt.py --run-root <run> --timeline-manifest <tl.jsonl> [--domain mir1k] [--out <GT_EVAL.json>]
PYTHONPATH=src python scripts/research_v7/analyze_long_slot_baseline_quality.py --gt-eval <GT_EVAL.json> [--mir-gt-eval <MIR_GT_EVAL.json>] --out <dir>
PYTHONPATH=src python scripts/research_v7/evaluate_cross_domain_assessor.py --m4-assessor <ASSESSOR.json> --mir1k-collection <collection.json> --out <dir>
PYTHONPATH=src python scripts/research_v7/label_evidence_gt_eval.py --requests <REQUESTS.jsonl> --evidence-dir <run>/evidence [--backup]
PYTHONPATH=src python scripts/research_v7/report_long_slot_region.py --run-root <run> [--cross-domain-eval <...>] [--baseline-quality <...>] [--missing-ratio-curve <...>]
```

## Architecture
- `src/lyricalign/demo/` — 主要工作区：inline_realign、run_state、window_planning、
  media_render、karaoke、visual_diagnostics、alignment_artifacts、gpu_boundary_decoder、batch。
- `src/lyricalign/research_v6/` — detector/repair（E0–E5）与 windowing/decoders/metrics。
- `src/lyricalign/research_v7/` — 当前主线：long-slot timeline、slot/sparse_slots、canonical_mapping、
  c3_text_adapter、mutations、features、region_metrics、region_assessor、requests、attempt、real_executor、
  evaluation_guard。
- `src/lyricalign/inference/` — Qwen Forced Aligner 薄封装与统一输出 schema。
- `src/lyricalign/metrics/` — 字符指标（canonical `character_interval_metrics_v3_tolerant`）。
- `src/lyricalign/datasets/`、`training/` — M4Singer/MIR-1K 预处理、split、LoRA 训练（qwen_fa_*）。
- `scripts/demo/` — `run_inline_realign_*` 系列可复现入口 + 各种 collect/render/verify 配套脚本。
- `scripts/research_v7/` — 当前主线入口：manifest builders、collect/evaluate、preflight/smoke/report、
  C3 弱人声校准、collect_trainable_evidence。
- `configs/` 模型/训练/数据/metric 配置；`tests/` 回归与执行合同测试（`tests/research_v7/` 为当前主线）。
- 文档按状态分层：`docs/research_v7_align_behavior/` 当前主线（13/14/15/17 为冻结计划/合同/蓝图/复审），
  `docs/status/`、`docs/manual/`、`docs/sessions/`、`docs/archive/` 分列状态/manual/会话/归档。

## Conventions
- 命令入口只在 `scripts/`；核心逻辑进 `src/lyricalign/`。
- 强约束：checkpoint 只许 validation 选择；不得依据 test/OOD 改 checkpoint；
  不静默覆盖原始 aggregate JSON；metric 修正必须从逐字符 reference/prediction 重算。
- `rule_validated` 是 weak supervision，不等于人工 GT。
- Realign 默认 **shadow-only**：`actual_writeback` 必须保持 `0`。
- checkpoint、模型缓存、音频、大型 prediction 文件不进入 Git/archive。
- 普通中断不清理目录；用相同 `OUT_ROOT` + `RESUME=1` 重跑可续。
- 日文解析后词单元直接进 forced-aligner prompt，不二次分词；中英混杂保留连续拉丁词。
- research_v7 主线的缓存/evidence 是**内容寻址**：attempt identity 必须并入模型/checkpoint/音频 SHA/
  代码/环境/mapping schema，输入变化不得复用旧 evidence；train/eval 只能消费
  `collect_trainable_evidence.py` 的 collection，不能直接读原始 items。
- research_v7 正式口径：长数据 = ≥90s、主体 ≥180s；主模型请求 fixed 60s；禁止人工静音凑长数据；
  missing 用 virtual gap 评价，replace 同时评价 wrong-output 与 omitted-original；
  formal 预算目标 ≤10h、硬上限 ≤12h；禁止全笛卡尔积。

## Notes
- 模型路径由 `scripts/demo/inline_realign_env.sh` 定义：默认 `MODEL_REVISION=c07281df...`、R2 checkpoint
  指向 `/home/hyan/Data/lyricalign/runs/.../step-000750`；demo 运行前先跑 `verify_inline_realign_v4.sh` 校验。
- Git：remote `git@github.com:heyan2454/LyricAlignment.git`（见 `docs/manual/git_workflow.md`）；
  只提交代码/配置/轻量 manifest 与摘要，禁止音频/checkpoint/大预测文件。
- `reasonix` 是本机同构工具；其同类项目指令文件见 `/home/hyan/AST/REASONIX.md`（不同仓库，仅风格参考，
  不适用于本仓库路径/命令）。
