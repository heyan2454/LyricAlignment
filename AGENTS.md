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
- 深度上下文从 `AI_SESSION_ENTRY.md` 进入，active override 以其中最新段为准（当前最新段为
  2026-08-16，指路 `docs/sessions/20260816_lyric_align_dataset_acquisition_evaluation_strategy/`；
  其与 2026-08-14 段的关系不作裁定，请自行核实）。上一覆盖层
  `docs/sessions/20260814_realign_recovery_visualization_overnight/`：实现前依次阅读 `00`–`06`；
  Codex 先按 `05_CODEX_HANDOFF.md` 核实当前代码/证据并生成 `07_CODEX_IMPLEMENTATION_PLAN.md`，
  再交 OpenCode/agent 分批实现。与旧 session 冲突时，本 session 的实验/可视化/执行合同优先。
  上游 `20260813_unit_level_realign_overnight`、`20260812_realign_recovery_research`、
  `research_transition_recovery_detector`、`research_fullslot_serial_detector` 与
  `research_v7_align_behavior` 只作实现和证据追溯。

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

- **语言约定**：思考与回复统一使用中文（代码、标识符、命令、专有名词除外）。
- **多用子 agent 并尽量并行**：主 agent 只负责调度、派发与合并验收，具体开发/review/探索
  交由子 agent 执行。注意：`task` 工具是**同步阻塞**的——同一消息内多个 task 并行启动，但
  主 agent 必须等全部返回后才能继续；这是 opencode 平台机制，不是可配置策略，等待期间主
  agent 不产生新思考。因此真正要控制的是两个成本：① 子 agent 结果注入导致的主上下文膨胀；
  ② 同步等待的墙钟时间。手段：一次派发尽可能多的独立子 agent（每任务一个 git worktree
  隔离，避免文件冲突），不同 phase 或相互独立的模块并发开发；子 agent 只返回结构化短报告
  （改动/测试/产物/下一步），由主 agent 合并与验收。
- **每阶段/每批完成后启用 review 子 agent**（通常 2 个并行：一个查代码正确性与契约、一个查
  数据一致性与跨模块接线/文档对照）。**review 只关注 P0/P1（CRITICAL/MAJOR）问题**：bug、
  口径不一致、契约违反、会污染结论的数据问题；不纠结信任/防伪类问题（manifest、登记、SHA
  可被有写权限者篡改等），保持"可追溯"即可。MINOR 记 backlog 不阻塞。
- **子 agent 限制步数**：opencode 配置层已设 `agent.general/explore.steps=8`（见 `opencode.json`），
  达到 8 次工具调用后强制转 text-only。派发 prompt 中同时写明 `STEP BUDGET=8`，并要求到步数
  后整理输出：已完成/未完成与原因/关键产物路径/上下文摘要/下一步建议，不得无限循环重试。
- **任务 prompt 硬性约定**（派发子 agent 时必须写入 prompt，主 agent 自己也遵守）：
  - 未全部完成禁止收尾：所有子步骤完成前不得输出总结/最终报告；
  - 精简回复：大段代码/长结果写文件，回复只放路径+摘要（避免单步输出截断）；
  - 单次操作要小：一个工具调用里不塞超长命令/大循环，拆多次小操作（避免单请求超时）；
  - 步数精打细算：先读最小必要上下文，禁止重复探索/重复读文件，浪费步数视为未完成。
- **子 agent 失败自动重启**：子 agent 返回 blocked/空转/异常/步数耗尽但未完成时，默认
  **自动重启**（优先 `task_id` resume 续跑，其次拆小任务重派），同一任务最多重试 2 次；
  仅当失败明确不可重试（依赖/数据/环境缺失、任务不可能）才记录 blocked 并降级为
  `not_executed_dependency` 或简化方案。每次重启前读上一次的总结，避免重复探索。
- **网络/超时兜底**：provider 级 `timeout=300s`/`chunkTimeout=60s`/`headerTimeout=15s`
  （`opencode.json`）使子 agent 请求快速失败；主会话断线由 `.opencode/plugins/auto-reconnect.ts`
  自动重连（10 分钟间隔、1 小时窗口内 6 次上限），无需人工重发。主 agent 收到子 agent
  失败后不阻塞其他任务，继续派发/完成 CPU 工作。
- **测试分层**（避免每次都跑全量）：
  - L1 快速层 `tests/research_v7/test_detector_v2_*.py`：每个子 agent 必跑（秒级）；
  - L2 模块层 `tests/research_v7`：跨模块改动时跑（约 1 分钟）；
  - L3 全量 `tests/`：仅 merge agent 与阶段收尾跑。
  子 agent 验收默认 L1 + `compileall -q src scripts` + `git diff --check`。

## Current mainline: Unit Realign Recovery + Visualization（下一轮）

> 2026-08-16 起另有更新 focus（数据获取 + 无训练评测/产品化），入口见 `AI_SESSION_ENTRY.md` 最新段；
> 本段保留为 2026-08-14 主线说明，是否仍为当前主线请自行核实判断。

当前规划入口为 `docs/sessions/20260814_realign_recovery_visualization_overnight/README.md`。
本轮重点研究困难区 multi-realign dynamics、细粒度 split、audio recrop/multi-view、
`R-U coarse proposal -> bounded sparse/fixed refinement`，并把 B4-vs-Current 与 Current 四路诊断视频
作为正式实验。所有 realign 继续 shadow-only；真实 writeback 不启用。实现前必须冻结 Current/B4 exact
resolved baseline、request/cache identity、GT firewall、evaluator schema、visualization adapter、CPU/small-GPU
smoke 和 GPU 预算。旧 realign_recovery/research_v7/demo 模块优先通过 adapter 复用，避免复制 runner。

## Upstream implemented baseline: research_v7 Detector V2

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
- **runs 管理（参考 AST 模式）**：工作目录 `runs/` 只登记轻量 README.md 与 `.gitkeep`
  （`.gitignore` 对 `runs/**/*` 全 ignore + 白名单），**具体 run 数据严禁放在工作目录**，
  统一存放于数据目录 `/home/hyan/Data/lyricalign/runs/`。代码/脚本/文档中的 run 路径一律用
  该数据目录绝对路径；新 run 也写入数据目录。
- **results/reports 管理（参考 AST 模式）**：`results/` 保存从 run 抽取的轻量结构化
  指标与比较表（by_run/comparisons/recomputed），是 canonical metric source，全部进 git；
  大型 per-item/checkpoint/cache 外置数据目录。`reports/` 保存人类可读 md/json 源文件
  （进 git），生成资产（`.pdf/.pptx/.docx`）与大型 evidence pack 不进 git，外置到
  数据目录对应 run 下；reports 只登记路径与索引，不反向成为 canonical metric source。
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

---

# 迁移的全局纪律（原 `~/.dsh/AGENTS.md`，2026-08-17 迁入，对本项目会话生效）

# DSH 用户级全局工作纪律
本文件原为 DSH 用户级全局工作纪律（`~/.dsh/AGENTS.md`），2026-08-17 迁入本项目，对**本项目会话及其子 agent 生效**。项目纪律更具体、优先级更高；本文件聚焦通用科研与多 agent 编排纪律。

## 语言约定(对所有会话生效)
- **用中文思考,并用中文回答**。代码、标识符、命令、专有名词、路径、变量名、引用的字段名除外。
- 面向用户的状态、说明、结论、计划、建议一律中文;即使底层倾向用英文,也强制切换到中文。
- 代码内注释可用中文或英文(随项目习惯),但对用户的回复必须中文。

## 多 agent 编排纪律(跨项目通用 playbook)
适用于一切"长时间、多模块、多子 agent、需断线存活"的科研/技术工作。

### 调度与并行
- 任务级并行:相互独立的子 agent 一次尽量多派,各自隔离工作区/模块,避免文件冲突。dsh 的 subagent 默认后台运行,应按需派发。
- 主 agent 只调度、派发、合并验收,不重复实现了代工作。子 agent 返回结构化短报告(改动/测试/产物/下一步),长代码与结果写文件。
- 阶段级并行:开发/审查/测试/运行是独立且并发的阶段,不串成严苛流水线;不同阶段交给不同 agent。
- 批次流水线重叠:批次 N 产物一产生就交审查,主 agent 同时派发批次 N+1;P0/P1 以增量补丁回流,不阻塞新批次。

### 子 agent 约束
- 给每个子 agent 显式步数预算;到预算后转"已完成/未完成+原因/产物/上下文摘要/下一步",绝不无限循环。
- 不无限重试:失败自动重启(优先续跑,其次拆小重派),同一任务最多 2 次;重启前读上一次总结避免返工。
- 任务 prompt 硬要求:子步骤全完成前不写收尾总结;一次工具调用小而可控;步数精打细算,先读最小必要上下文,禁止重复探索。

### 验收与审查
- 分层测试:快速层(秒级,每个子 agent 必跑)→ 模块层(跨模块 ~分钟)→ 全量(仅 merge/阶段收尾)。失败只阻塞受影响部分。附语法编译检查与 `git diff --check`。
- 每批后两个独立审查并行:代码正确性/契约、数据一致性/跨模块接线;**只关注 P0/P1**,MINOR 进 backlog 不阻塞;审查与下一批开发重叠。

### 状态跟踪
- 维护单一状态文件,每单元完成原子更新;记录每部分状态/已用预算/resume 命令,主 agent 据此调度。

## 长期任务执行纪律
- 阶段分层:小规模 pre-flight(结果可改设计)→ 冻结设计 → smoke 只验可执行性(含 resume)→ 正式长跑;三层语义不同。
- 断线存活:长跑必须挺过终端断开——用后台/nohup/进程管理器?会话,输出重定向日志并记录 PID;任何"随会话死亡"的方式都不合格。
- resume 语义:中间产物按 identity 哈希缓存(同输入跳过);组件从各自 checkpoint 续;禁止两个 controller 并发写同一输出根。
- 禁止全笛卡尔积:绝大多数维度一开始固定,仅少数维度分级 escalate;新增实验走偏差日志(为何不足、回答什么、额外成本、替换哪个低优先项)。
- 小样本安全:按子集分层抽样,每子集保留代表;数据不足显式回退并记录,不静默启用。
- 冻结参数纪律:正式阶段前冻结所有超参;正式期只修 bug 及会致结果失效的 schema/identity bug,修后使受影响结果失效并只重跑受影响 identity;不做临场调参。
- 长任务挂 watchdog(监视持续追加的 log,勿监视"跑完才写"的终态产物以免健康运行时误报)+完成哨兵(等产物 mtime 新鲜写 _done.flag,主进程只在 flag 出现时处理);事件触发之外加定时巡检兜底,防卡死无人知;哨兵/编排等待窗口给足(≥ 任务最坏时长),勿比任务先超时。
- 长任务按核数分片并行:启动前确认 CLI 支持分组(--items/--max-items),没有就加上再跑;多进程写各自独立输出后合并(防竞态);启动后确认进程存活再离开。
- 杀进程用精确 pid(先 ps -ef 列出),禁 pkill 长命令行子串(会匹配到自身 shell 自杀);长任务 setsid 隔离启动。

## 完成/科学/报告纪律
- 不得过早整体终止:单项失败/无收益/item 失败不是整体终止理由——写权威失败/负结果产物(状态/真实分母/原因),继续不依赖它的阶段。仅全局阻塞(依赖/数据/环境缺失、磁盘不可写、会污染全部结果的严重 identity/split 错误)可终止,且写完整阻塞文档(已完成阶段/最后成功产物/失败命令日志/可粘贴 resume 命令)。
- 运行完备才算完成:每项都有显式状态(completed / bounded-insufficient / blocked / abandoned-with-reason)才允许结论。
- 科学边界:指标口径先定义并冻结,中途不改;报告数字由结构化数据(JSON)生成,绝不手抄;比较同标准(同 split/identity),不跨不兼容指标合并;不凭 training loss 宣称更优。
- 主线后受控探索:主线每阶段结束自动进入(不等用户指示)——读最新结果→更新结论/分支状态→对候选方向评分(headroom/evidence/paper 价值/成本)→打开最高信息价值项(需 hypothesis/最小实验/stop rule,可负向关闭,不做无证据大 sweep);与已关闭/父树负结果重叠方向不重复立项。stage 完成即写阶段记录到 session 文档(阶段性总结被鼓励),仅"验收条件全达成前"不写最终收尾。可推翻主结论者走升级路径(数据确认→独立反查→影响边界评估→根因追溯→最高优先 todo)。
- 注入频率自检:每轮先查有无实质完成事件(哨兵 flag/schedule/watchdog 触发/后台产物/用户新消息);无新事件则本轮零调用结束,不逐轮小查进度;连续 ≥3 轮零实质产出即停当前自动段(complete),不硬扛高频注入。

## DSH 机制速记
- 用户级全局指令 = `~/.dsh/AGENTS.md`(已于 2026-08-17 删除,内容迁入本项目);项目级指令 = `<项目根>/AGENTS.md`(更具体,优先);本文件即迁移后的纪律。
- 需要"按需加载"的工具类知识(非常驻纪律)放 dsh skill:用户级 `~/.dsh/skills/`,项目级 `<项目根>/.dsh/skills/`,agent 按需通过 `skill` 工具加载。
- 语言、方法论这类"希望自动常驻"的内容放 AGENTS.md,而非 skill。
- goal 只承载"当前有界自动执行段";长期目标/纪律/后台清单放各 run root 的权威状态文件(命名不定,以 session/合同指明为准),重建靠读文件不靠记忆;goal 在自动轮无法 pause/resume(机制限制)→高频注入或需长等待用 complete 收掉(后台任务照跑),需时再按需重建。
