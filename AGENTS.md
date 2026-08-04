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
  `docs/research_v7_align_behavior/` 的 `README` / `13` 冻结计划 / `14` 执行合同 / `17` 实现复审。

## Commands
```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
# 若需安装项目包：pip install -e .（在 src/ 内）
PYTHONPATH=src python -m pytest -q              # 全量测试（tests/，409 项）
PYTHONPATH=src python -m pytest -q tests/research_v7   # 当前主线（121 项）
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

## 当前主线：research_v7 long-slot / region assessor（从 `docs/research_v7_align_behavior/` 进入）

实现主体在 `src/lyricalign/research_v7/`（timeline / slot_planning / sparse_slots / canonical_mapping /
c3_text_adapter / mutations / features / region_metrics / region_assessor / requests / attempt /
real_executor / evaluation_guard），入口在 `scripts/research_v7/`。当前**只有 smoke/draft 级产物，
正式 gate 未批准**：以 `17_IMPLEMENTATION_REVIEW_20260805.md` 为准，P0（真实 runner/identity-evidence/
canonical 闭环等）未全部关闭前，只允许产出标 `draft=true` 的校准与 smoke artifact，不得声称
real smoke/pilot/formal。相关命令：

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
