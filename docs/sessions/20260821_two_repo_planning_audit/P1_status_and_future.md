# P1 — 主线状态与未来（status_and_future）

标签：`[事实]` = 文档原文/命令输出/磁盘状态；`[推断]` = 判断（附置信度）；`[建议]` = 行动建议。
证据格式：`路径:行号`（LA 相对 `/home/hyan/LyricAlignment`，AST 相对 `/home/hyan/AST`；
仓库外产物用绝对路径）。

---

# 第一部分：核对"已知现状"（任务书给的 4+3 条假设）

**这是本阶段最重要的产出：其中 1 条被证伪，2 条需重要修正。**

## LA

| # | 假设 | 裁决 | 证据 |
|---|---|---|---|
| L1 | 主线 = Unit Realign Recovery + Visualization | **契约层成立，实际已漂移** | 见 §1.1 |
| L2 | shadow-only（`actual_writeback=0`） | **成立**（强证据链） | 见 §1.2 |
| L3 | GPU 目标 ≤10h 硬 ≤12h | **成立，但不是当前瓶颈** | 见 §1.3 |
| L4 | git ahead 124 且有未提交改动 | **成立**（124 / 93 项） | 见 §1.4 |

## AST

| # | 假设 | 裁决 | 证据 |
|---|---|---|---|
| A1 | run1 已完成、结果解读待 review | **半数成立**：run1 完成✓；但"待 review"已过期 | 见 §1.5 |
| A2 | select 阶段未跑（`selection.json` 均为 8-06 旧值） | **❌ 证伪** | 见 §1.6 |
| A3 | conda 环境路由见 AGENTS.md | **成立** | 见 §1.7 |

### 1.1 [L1] 主线：契约声明 vs 实际重心 —— 已漂移

[事实] 契约层三处一致指向 2026-08-14 session：
- `AGENTS.md:82` "## Current mainline: Unit Realign Recovery + Visualization（下一轮）"
- `AGENTS.md:15-16` "当前 active override 指向 `docs/sessions/20260814_realign_recovery_visualization_overnight/`"
- `AI_SESSION_ENTRY.md:3` "## 2026-08-14 Unit Realign Recovery + Visualization — Active Override"

[事实] 但实际最新重心在别处，三条独立证据：
1. `docs/sessions/SESSION_INDEX.md:11` 已把 `20260816_lyric_align_dataset_acquisition_evaluation_strategy/`
   标为 **hot**，描述为数据获取 + no-training evaluation-v1 方向。
2. `AI_SESSION_ENTRY.md` **完全没有 2026-08-16 条目**（最新条目即 :3 的 08-14）。
3. 最新 commit `0356d3f`（2026-08-15）主题是 slot builder 窗口化修复，
   而 0814 session 的 `00_SESSION_DISCUSSION_RECORD.md` mtime 为 **2026-08-16 05:52**
   （被持续追写），其 `:1064-1074`、`:1243-1253` 讨论已转向"窗口输入/装配层架构 + A/B/C 组对比"。

**仲裁（按任务书规则：active override 优先，仍冲突则日期新者优先并记录）**：
- `AI_SESSION_ENTRY.md` 是被 `AGENTS.md:15` 指定的深度上下文入口，其 active override = 08-14。
- 但 08-16 的 session 目录、SESSION_INDEX 条目、progress 报告日期均更新。
- → [事实] **两者冲突且 override 未更新**。按"日期新者优先"，**当前真实主线应认定为
  08-16 的 evaluation-v1 / 产品化线**，而 08-14 的 realign-recovery 已进入"结论已出、
  证据待收尾"状态。

[推断 0.9] 漂移原因：08-14 那轮的核心科学假设**被自己的数据否定**（见 §1.2 与 §2.1 的
`recovered 0%`），于是工作重心自然转向"先把评测/数据/产品化底座搭好"。
这不是管理失误，而是**负结果驱动的合理转向**；缺陷只在于 override 未回写。

[建议] 这是 P4 的第一优先修复项：在 `AI_SESSION_ENTRY.md` 顶部补 2026-08-16 override 条目，
并同步 `AGENTS.md:15-16`、`:82-89`。

### 1.2 [L2] shadow-only：成立，证据链完整

[事实] 五层证据，口径一致：

| 层 | 证据 |
|---|---|
| 项目契约 | `AGENTS.md:157` "Realign 默认 **shadow-only**：`actual_writeback` 必须保持 `0`" |
| session override 硬要求 | `AI_SESSION_ENTRY.md:36` "`actual_writeback=0`" |
| 本轮 run 计划 | `docs/sessions/20260814_.../06_PLANNED_RUNS.yaml:5` `actual_writeback: 0` |
| 实验配置（5 份） | `configs/experiments/unit_realign_gpu_smoke_20260813.json:17`、`unit_realign_formal_20260813.json:17`、`unit_realign_test_demo_formal_20260813.json:16`、`unit_realign_confirmation_no_gt_20260813.json:17`、`unit_realign_heldout_expansion_20260813.json:17` |
| 代码默认值 | `scripts/demo/run_inline_realign_experiment.py:1415`、`:1624`、`:2155` 均 `"actual_writeback": False`；`:1630` `"eligible_for_actual_writeback": False` |
| 老配置 YAML | `configs/research_fullslot_serial_detector/b4_60_silence_official_shadow_v1.yaml:44` `actual_writeback_enabled: false`、`:47` `actual_writeback_count_equals: 0` |

[事实] 无任何 run 开启过 writeback（SA-1 在 0814 全簇 12 文件搜索 `actual_writeback|writeback|shadow|dry_run`，
全部命中 0/shadow-only）。
[事实] 且科学上明确"不足以支持自动写回"：`01_CURRENT_EXPERIMENT_RESULTS_AND_CONCLUSIONS.md:81`、`:85`
（R-U 是 coarse proposal，非无门控终态写回）、`:187`（小 context 位移只是**必要**安全条件）。

[事实] **重要观察**：2026-08-16 簇中 `actual_writeback` 一词**完全未出现**
（SA-2 在 20 份文件中搜索确认 NOT FOUND），只有 `reports/behavior_registry.json:176,185-186`
的 `safety.no_gt_gate` 条目提及 writeback 门控假设。
[推断 0.85] 0816 那轮全是 evaluation 批次（写新输出目录），根本不涉及写回阶段，
所以 shadow-only 约束在新主线下**暂时不适用**而非被违反。

### 1.3 [L3] GPU 预算：数字成立，但远未成为瓶颈

[事实] 数字三处一致：`AI_SESSION_ENTRY.md:42` "target GPU <=10h, hard cap <=12h"；
`06_PLANNED_RUNS.yaml:6-8` `target_hours: 10` / `hard_cap_hours: 12`；
`AGENTS.md:166` "formal 预算目标 ≤10h、硬上限 ≤12h"；
另 `04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md:32-36` 规定超硬顶后转 CPU 分析。

[事实] **实际消耗与预算相差 2–3 个数量级**：
- `07_CODEX_IMPLEMENTATION_PLAN.md:218-221` 估算 500–1000 forwards ≈ **5–10 分钟** warm GPU。
- 实测：E1 200 forwards **54 秒**、E4 **20 秒**（`docs/sessions/20260814_.../RUN_STATE.md:27`；
  `09_GPU_REAL_RUN_REVIEW.md:13`、`:27`）。
- `08_SESSION_FINAL_REPORT.md:122` 记录该阶段 GPU forward = **0**（当时 GPU 不可访问）。

[推断 0.9] **GPU 预算不是当前约束**。真实约束是：① 有 GT 的评测数据量；
② 人工/agent 的分析与收尾工时；③ 磁盘（0816 簇用 `cleanup_report.md` 管理，见 §2.2）。
[建议] P2/P3 的资源预算不应围绕 GPU 小时数设计，而应围绕"有 GT 的样本数"和"收尾工时"。

### 1.4 [L4] git 状态：成立，且是**最高风险项**

[事实]（在 `/home/hyan/LyricAlignment`）：
```bash
git rev-list --left-right --count origin/main...HEAD   # -> 0  124   即 ahead 124
git status --porcelain | wc -l                          # -> 93
git branch --show-current                               # -> main
```
[事实] 93 项未提交按目录：`scripts/evaluation/` 30 个全新文件（??）、
`scripts/realign_recovery/visualization/` 20 个新 + 4 个改、`results/comparisons/` 12 个新 JSON、
`reports/progress/` 7 个新报告、`src/lyricalign/demo/` 4 个改
（`karaoke.py`、`media_render.py`、`visual_diagnostics.py`、`window_planning.py`）、
`AGENTS.md` 改、`docs/sessions/SESSION_INDEX.md` 改、
`docs/sessions/20260816_*` 整目录未跟踪。

[推断 0.95] **0816 那一整轮工作（数据获取 + evaluation-v1 + 产品化）100% 未提交**：
30 个 `scripts/evaluation/*` 脚本、12 份 `results/comparisons/*.json` 指标、
7 份进度报告、整个 session 目录都只存在于工作树。
叠加 ahead 124 未推送 → **单点故障**：一次误操作/磁盘故障会丢失约两周的成果。

[事实] 该风险已被 review 独立发现并升级：
`.dsh/review5_evaluation_v1.md:38` 指出 **baseline identity freeze 记录的是一棵 dirty tree**，
"必须先整理或记录 diff hash 再做正式冻结"。
[推断 0.85] 这使"冻结基线"在科学上**不可复现**——无法从任何 clean commit 重建被冻结的基线。
这是 0816 簇最实质的缺陷（SA-2 独立给出同一判断，置信 0.85）。

### 1.5 [A1] AST run1：完成✓，但"待 Codex review"已过期

[事实] run1 五遍 resume 完成全部 stage，run root
`/root/autodl-tmp/AST_storage/Data/ast_runs_formal/pesto_causal_12h_run1_20260806/`（36 GB），
数据 mirst500 shared-split train302/val34/eval45
（`docs/sessions/explore/20260806_pesto_causal_12h_program/RUN1_RESULTS.md:8-12`）。

[事实] eval45 @100ms/50cent（`RUN1_RESULTS.md:21-25`）：
triangle_direct **67.14/51.88（最优）**、direct_pyramid 64.16/50.32、direct 64.19/48.68、
oaf_direct 62.05/46.29、coarse_to_fine 61.60/42.11。
Eventizer（`RUN1_RESULTS.md:33-38`）：fv2_acoustic **54.82/40.23（最优，+1.85）**、
fv2_posterior 53.78/38.23、causal_fv2_h4 baseline 53.18/38.38、residual 52.14/36.84、
fv2_latent 49.21/34.97、fv2_all 49.13/34.49。

[事实] **矛盾**：`RUN1_RESULTS.md:96` "Codex review 已完成"，
而 `docs/status/project_current.md:28` 与 `docs/status/next_execution_plan.md:18`
仍写"结果解读待 Codex review 复核"（两者 `as_of: 2026-08-06`）。
→ 按日期新者优先：**review 已完成**，status 文档过期。

[事实] 但**正式结论确实仍被阻塞**，且原因与"待 review"不同：
`RUN1_REVIEW.md:9-14` 判定"当前不宜定稿为正式架构比较或正式 winner"，
状态标签 "RUN1 screening complete；结果解释 provisional；正式结论 blocked by
selection repair and missing evidence"；`EXPERIMENT_REPORT.md:3` 状态 `provisional_internal_screening`。
阻塞项见 §3.2。

### 1.6 [A2] AST select 阶段 —— **假设被证伪**

**文档主张 [事实]**：`HANDOFF_20260814_selection_status.md:9-10` 明写
"**convergence 之后的真正 select 一次都没有执行过**"、
"`joint_eval/*/selection.json` 全部仍是 08-06 的 run1 旧结果……已完全失效"；
`:85` 甚至警告"别读 `joint_eval/*/selection.json` 当权威"。

**磁盘实况 [事实]**（我亲自 `stat` 验证）：5 个 joint head 的 selection.json 全部存在且为 **08-14 新写**：

| head | mtime | 大小 |
|---|---|---:|
| `joint_eval/direct/selection.json` | 2026-08-14 13:55 | 19573 B |
| `joint_eval/direct_pyramid/selection.json` | 2026-08-14 14:29 | 16877 B |
| `joint_eval/oaf_direct/selection.json` | 2026-08-14 14:49 | 9802 B |
| `joint_eval/triangle_direct/selection.json` | 2026-08-14 15:23 | 16920 B |
| `joint_eval/coarse_to_fine/selection.json` | 2026-08-14 15:46 | 9909 B |

（根 = `/home/hyan/Data/ast_runs_formal/pesto_causal_12h_run1_20260806/`）

**内容级证据 [事实]**：新文件含旧文件没有的键：
```json
"selection_procedure": "two-stage: stage1 chooses the best checkpoint under a single shared
  fixed decode config ... stage2 sweeps the decode threshold grid only on that winner ...",
"stage1_checkpoint_select_thresholds": {onset 0.5, offset 0.5, active 0.5,
  release_frames 2, minimum_duration_sec 0.05}
```
旧 8-06 版本无此二键，且已被备份到
`joint_eval_backup_run1_20260814_052648/`（mtime 08-14 05:26，5 份，2368–2442 B）。
`cmp` 验证新旧全部 **DIFFERENT**（体积差 4–8 倍，对应候选数 6→48）。

**同簇文档自证 [事实]**：`HANDOFF_20260814_select_twostage.md:56`
"✅ **select×5 全部完成**（串行总墙钟 13:16→15:47 ≈2h31min；全部 rc=0）"，
时间线与磁盘 mtime（13:55–15:46）**精确吻合**。
选参结果 `:59-64`：direct ep25/63.99、pyramid ep30/66.63、oaf ep17/64.01、
**triangle ep30/68.26（最优）**、coarse ep8/59.37（COnOffP@150ms/100cent），
阈值统一 onset 0.5 / offset 0.65 / active 0.55 / release 2。

**裁决**：假设 A2 **错误**。根因 [推断 0.9]：
`HANDOFF_20260814_selection_status.md` 文件 mtime 为 08-14 22:34，
但其 §1–§2 的状态快照采集于**当日凌晨**（select 尚未开跑），写入时未刷新，
形成一份"晚出生却记录更早状态"的文档，且它自身还禁止读取真实产物。
→ 这是**文档主动误导下一轮 agent** 的典型案例，比单纯过期更危险。

[建议] P4 中列为 AST 最高优先修复项：给该文件加显式 superseded 头部，指向 `select_twostage.md`。

**顺带修正 A2 的一个前提 [事实]**：仓库内 `find . -name 'selection*.json'` 返回空是**正常的**，
因为 `.gitignore:77-78` 忽略 `runs/**/*`，真实 run 根在仓库外
（`AGENTS.md:47`），仓库 `runs/` 只有 `.gitkeep`。不能据此推断"未跑"。

### 1.7 [A3] conda 路由：成立

[事实] `AGENTS.md:33-38` 定义按路线分环境（根 `/root/autodl-tmp/AST_storage/conda/envs/<name>`）：
`pesto`(py311, torch2.5+cu121) 负责 PESTO 导出/训练/`evaluate_route_manifest.py`/全部测试；
`ast-oaf`(py39, TF2.10/magenta2.1.4) 负责正式 Magenta O&F fusion/post 与 Basic Pitch SavedModel；
`ast-highres`(py310) 负责高精度 fusion；
`basicpitch310`/`crepe310`/`fcpe310`/`rosvot`/`vocano` 各自模型。
[事实] `AGENTS.md:14` base 环境缺 pandas，pytest collection 直接失败。
[事实] 两种调用式并存：`conda run -n pesto python -m pytest -q`（`AGENTS.md:15`）
与绝对路径解释器 `PY=/root/autodl-tmp/AST_storage/conda/envs/pesto/bin/python`
+ `export PYTHONPATH=/home/hyan/AST/src`（`HANDOFF_20260814_selection_status.md:49-50`）。
[事实] 磁盘实存 12 个 env，文档未提及的有 `demucs`、`spleeter`、`spleeter38`、`lyricalign-qwen`
（后者是 LA 项目的环境，说明两项目共享同一 conda 根）。

---

# 第二部分：LA 主线状态

## 2.1 已完成（挂产物级证据）

### A. 0814 轮：11 个 work package 全部完成

[事实] `docs/sessions/20260814_.../RUN_STATE.md:11-22` 状态表显示 WP1–WP11 全部 `completed`，
每项附 commit。汇总：**36 个新 commit、387 个单元测试通过、28–29 份 provenance note**
（`08_SESSION_FINAL_REPORT.md:45`；`provenance_notes/` 实际 29 文件，mtime 08-14 06:19–15:22）。

| WP | 内容 | 验收标准（证据） |
|---|---|---|
| WP1 | E0 baseline 冻结 + identity | `CURRENT_BASELINE_RESOLVED.json` + `B4_BASELINE_RESOLVED.json` + 4 个新 identity key + Gate G0（`07_CODEX_IMPLEMENTATION_PLAN.md:236-240`；commit 94fa0bf，测试 243→351） |
| WP2 | 可视化 adapter + 三路 smoke | 10 项 smoke 含 rerender-no-forward（`07:248`） |
| WP3 | E1 multi-realign 筛查 | 40–60 区域 ×3 链 ×iter{1,2,3,5}（`07:252-255`） |
| WP4 | E2 细粒度 split | 02 的 E2 全 8 指标（`07:259`） |
| WP5 | E3 k1/k3 + audio recrop | 无 P0/P1（`RUN_STATE.md:16`） |
| WP6 | E4 coarse→fine + 第 4 路 | 02 的 E4 全 7 指标 + `--fourth-family R-CF`（`07:268-269`） |
| WP7 | E5 no-GT selector/safety | 11 个测试（`RUN_STATE.md:18`） |
| WP8 | P6 自适应扩展 | 仅 top1/2 机制，≥200 区域 + 歌曲 held-out（`07:277`） |
| WP9 | E6 atlas + E7 串行压力 | `RUN_STATE.md:20` |
| WP10 | E8/E9 Test-Demo 可视化批次 | `RUN_STATE.md:21` |
| WP11 | 收尾 + 自由探索 | 满足 `04` §10（`08:43`） |

### B. 0814 轮的真实 GPU 实验结果（RTX 4080 SUPER，Qwen 0.6B，torch 2.8.0）

[事实] `09_GPU_REAL_RUN_REVIEW.md:7-9` 记录环境；模型
`Qwen/Qwen3-ForcedAligner-0.6B-hf@c07281df` + R2 `step-000750`。
- E1 multi-realign R-U：40 区域 ×10 歌 ×5 iter = 200 forwards，54 秒；
  目标位移 ≤200ms 者 32/40；**固定上下文位移中位 320ms、最大 4920ms**；
  39/40 被标振荡，主因是整窗平移伪影（−20ms/iter）（`09:13-16`）。
- E2 细分：`recovered_unit_fraction = 1.0`，但 `context_preservation = False`（`09:19-21`）；
  方向矩阵 40 例：independent = L2R = R2L 完全一致（rec 0.748，26/40 全恢复）（`09:81-83`）。
- E3 音频视图（仅 3 区域）：no-GT selector 3/3 选 `base`，`wider` 无增益（`09:24-26`）。
- E4 coarse→fine R-CF：stage-A 可构造 27/40（13 例 `invalid_unit_target_span`），
  stage-B 精修 15/27，**`fixed_context_displacement_ms = 0.0` 达 15/15**；
  `target_recovered_200` 10/15、`_500` 12/15、`_1000` 13/15；灾难性回归 8/40
  （5 例误标 + 3 例真失败）（`09:27-31`、`:55-60`、`:85-86`）。

### C. 【关键负结果】大规模验证推翻了乐观结论

[事实] **B 组 884 区域 ×3 家族、18 批次、0 失败**（`00_SESSION_DISCUSSION_RECORD.md:1294-1300`）：

| 家族 | ok 率 | collateral | catastrophic | **recovered** |
|---|---:|---:|---:|---:|
| R-U | 87.9% | **100%** | 0.1% | **0%** |
| R-S | 51.2% | 0% | — | **0%** |
| R-CF | 83.0% | **100%** | 6.8% | **0%** |

[事实] 0813 formal（有 GT，78 区域）：region 级有益 25.6%，
**catastrophic_harmful 65.4%** → 短窗 realign 在 M4Singer 困难区**净有害**；
"812ms 改善"只是均值（`00:1167-1176`）。
[事实] `00:1174-1176`（08-16 追写）显式纠正早前"slot 效果很好"的说法。

[推断 0.9] **这是 LA 当前最重要的科学事实**：realign-recovery 这条路在
大样本、有 GT 的严格口径下**没有可复现的恢复效果**，且伴随 100% collateral。
[事实] 但 `09:58-59` 仍写"核心假设成立"（基于 stage-B 15 个区域的 0ms 固定上下文位移 + 10/15 恢复）。
[推断 0.8] 两者不是数值冲突而是**分母与 GT 可得性不同**（15 vs 884），
但 `09` 的乐观表述在 `09` 内部未被调和 → 读者极易误读。
[建议] P4 需给 `09` 加一条指向 `00:1294-1300` 的口径说明。

### D. 【关键伪结论纠正】"Current 比 B4 差"是音源伪影

[事实] 早期观察"Current 比 B4 差"被证伪：根因是 Current 在 **mix** 上对齐而 B4 在 **vocal** 上，
零时长率被抬高到 30%/15%/13%/4.9%；改为同源 vocal 后，Current 在 4 首歌上
**全部 ≤ B4**（21.3/6.4/4.3/1.7%）（`RUN_STATE.md:65-66`；`09:73-75`）。
[推断 0.95] 这是一条高价值方法论教训（**比较必须同音源**），
应提升为 `AGENTS.md` 级纪律，目前只躺在 session 文件里。

### E. 可视化能力：已具备可交付水平

[事实] 设计与验收：两个独立交付物 ——
**V1** B4-legacy-pre-slot vs Current-full-slot 双轨（无 realign）
（`03_VISUALIZATION_DESIGN_AND_ACCEPTANCE.md:11-26`）；
**V2** 四轨消融 `Current / R-U / R-S / R-U-coarse→bounded-sparse-refinement`，
并明令禁止用 R-A/R-B 或重复 R-U 充当第 4 轨（`03:114-125`）。
[事实] 画面规格：约 `3840×1080`、默认真实时间 `30s/页`、超宽全曲静态时间线、共享全局时标
（`03:142-145`）；匀速播放头仅沿时间轴、跨页连续、末页不补白（`03:148-154`）；
原始/mix 音轨 + 两行 KTV 字幕（`03:157-161`）；
零时长聚合形如 `零时长 [120-124, 130, 132-134] 我-他，的，给-热`（`03:182-190`）；
字体 `Noto Sans CJK SC` 且需 font preflight（`03:214`）。
[事实] 管线顺序冻结：`科学前向 → evaluator+summary → 证据收集 → analysis_complete →
静态可视化 → 视频分页 → MP4 编码`，禁止 `visualization -> collection` 逆序（`03:224-238`）。
[事实] **10 项 smoke 验收清单**在 `03:297-306`。
[事实] 产物布局 `03:325-342`；脚本清单 `08_SESSION_FINAL_REPORT.md:153-156`
（`visualization_controller.py`、`render_b4_vs_current.py`、`render_current_4way.py`、
`render_comparison_batch.py`、`render_rerender_only.py`、`run_test_demo_viz.py`、
`transcode_media_to_wav.py`），后续新增 `render_full_song.py`、`batch_v2_overlay.py`、
`render_slot_variants.py`、`render_bgroup_summary.py`（`RUN_STATE.md:39`、`:72`、`00:1308-1311`）。

[事实] **产物已大量存在**（我直接统计磁盘）：
`/home/hyan/Data/lyricalign/runs/` 下 **686 个 mp4**、172 个 run 目录；
6 个交付目录：`20260816_agroup_v2_DELIVER`、`20260816_agroup_BC_DELIVER`、
`20260815_slot_vs_b4_DELIVER`、`20260815_slot_v2_DELIVER`、`20260814_viz_DELIVER`、
`20260814_viz_deliver`。
其中 `20260816_agroup_BC_DELIVER/` 含 **99 个 mp4 + 1305 png + 430 json + 165 ass**，
顶层有 `BGROUP_SUMMARY.json`(20977 B)、`render.log`、`render_cgroup.log`。
[事实] A 组 `20260816_agroup_v2_legal`：33 首 ×3 方案（fix60/soft/strict），
coverage 1.0、0 失败（`00:1256-1258`）。
[事实] git log 佐证：`814a2ee`(08-15) "viz: render B4-vs-Slot ... static + timeline mp4 + KTV dual-panel"、
`fa13451`(08-15) "viz: slot_vs_b4 batch — all 33 songs (incl Japanese), Plan A runner"。

[推断 0.9] **可视化是 LA 当前最成熟、最接近"可演示"的能力**，
这直接决定 P2 的 demo 选择。

⚠️ [事实] **命名陷阱**：`Side_by_Side.wav` / `demo_Chinese_Side_by_Side_272b9100`
是**中文歌曲名"Side by Side"**，不是"并排对比布局"。
`03:285` 与 `06_PLANNED_RUNS.yaml:25` 把它指定为 smoke 媒体
（`/root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/Side by Side.mp4`）。
读文档时极易把两者混为一谈 → 已在此显式隔离。

### F. 0816 轮：数据获取（全部有 SHA 校验）

[事实] `01_DATA_ACQUISITION_RESULT.md` + `00_SESSION_DISCUSSION_RECORD.md`：

| 数据集 | 规模（精确数） | 许可 | 状态 |
|---|---|---|---|
| MIR-MLPop | cmn 20 WAV ≈ **5515.646 s**（请求 30）；yue 3 文件 ≈ **735.670 s**；标注 240223 三语齐全 | 学术非商业 | 部分缺失（cmn 缺 7,8,9,10,12,14,26,27,28,30；yue 缺 21,25），原因 takedown/geo/HTTP 403（`00:72-77`） |
| AMLL TTML DB | **3160 TTML**，XML 全部可解析，**无音频** | 上游声称 CC0，第三方词/译权未决 | 仅内部研究 silver 池（`00:83-84`） |
| PJS v1.1 | 100 唱 + 100 说；唱 ≈ **1611.444 s**、说 ≈ **542.620 s**；48kHz mono 24bit；+100 人工重标音素 | **CC BY-SA 4.0** | 可用（`00:89-92`） |
| JamendoLyrics MultiLang en/test | **20 MP3、5693 词区间、868 行区间**，≈ **4333.845 s** | 6 种 per-song 许可 | **仅原混音**，未做人声派生前不构成有效 operational benchmark（`00:96-100`） |
| GTSinger 中文 mini | 5 song root、2 歌手、5 种技法；**850/850 文件 = 231 WAV + 231 TextGrid + 231 JSON + 157 MusicXML**，≈ **1578.503 s** | CC BY-NC-SA 4.0 **+ 未澄清的赔偿/雇主接受条款 + 异常提及 "authors of M4Singer"** | 可用但许可有疑（`00:104-107`） |
| iKala | 无主音频 | Zenodo Restricted | `blocked_pending_access`（`00:111`；`01:12`） |

[事实] 合计新增外部资产 **~2.3 GB**、**4186 个 SHA-256** 全部校验通过（`00:117-118`；`01:21`）。
大数据不入 git，派生物到 `/home/hyan/Data/lyricalign/derived/`（`01:25-26`）。

### G. 0816 轮：evaluation-v1 真实 GT 指标（**LA 目前最硬的产品级数字**）

[事实] GTSinger diagnostic **75 段 / 1226 个非 AP 字符**，vocal + windowed
（`20260816_gtsinger_first_metrics.md:61-63`；`20260816_productization_validation_report.md:28-30`）：

| 模型 | both_100ms | both_200ms | both_500ms |
|---|---:|---:|---:|
| R0（base） | 74.8% | 81.4% | 95.6% |
| R1 | 87.6% | 92.8% | 97.7% |
| **R2** | **90.1%** | **95.5%** | **98.1%** |

[事实] review6 独立复算确认这些数字来自真实 alignment + GT JSON，非手抄
（`.dsh/review6_productization_round.md:15,18,19`）。
[事实] first-light（8 段，105–117 单元）是 smoke 级：R0 72.4% / R1 96.6% / R2 97.4%
（`20260816_gtsinger_first_metrics.md:51-55`），文档已自标"非完整评测"。

[事实] **raw decoder 消融（同一真实 GT）一致更优**：
- diagnostic 75 段：**90.05% → 91.84%**（+1.79pp；20 改善 / 2 回退 / 53 不变）
  （`20260816_productization_validation_report.md:134,137`）
- hard18（309 字符）：**78.32% → 84.47%**（14/0/4）（`:124,126`）
- regression_selection 84 段 / 1189 单元：official **87.47%** vs raw **89.49%**（22/1/61）（`:171-173`）
  ——注意 both_500ms 上 raw 略差（98.32 < 98.40）（`:171-172`）

[事实] 质量门实测：严格门（任何 overlap 即 fail）在 75 段上 **33 通过 / 42 失败**
（overlap 38、零时长 10、回归 1）（`:192-193`）；
regression 门：official 53/31 vs raw 45/39（`:197-198`）。
**混合门无效**：增益全部落在 raw 门失败子集（39 项，official 82.52% vs raw 86.44%），
门通过子集两者同为 92.72%（`:203-205`）。
[推断 0.85] 即"用最终 overlap 门去挑 raw/official"这条产品化捷径**被自己的数据否决**，
需要另找选择信号（`:206` 已把该问题显式列为开放设计问题）。

## 2.2 挂起项（LA）

[事实] 按证据分三档：

**H1｜0816 轮明确未完成**（`20260816_productization_milestones.md:7,25,31,36,39,40`）：
split 冻结/review、R-U/R-S/R-CF recovery 消融、PJS 音素级 GT、vocal-only 正式评测、
sealed 端到端 + sealed 报告。
[事实] `05_NEXT_ACTIONS.md` 五条优先级：① PJS 音素 GT 量化日语 raw decoder（`:3-6`）；
② MIR/Jamendo 用 demucs 做人声派生并记分离器 identity/hash（`:7-10`）；
③ 在 GTSinger 困难例上做 R-U/R-S/R-CF 消融、测与 raw decoder 的互补性（`:12-14`）；
④ sealed 里程碑评测（`guarded_run.py --allow-sealed`）（`:16-18`）；
⑤ 产品化门实现（零时长/overlap/时间戳回归 + speech-like 单独阈值）（`:20-22`）。
[事实] `06_ROUND_LOG.md:47` 最后一轮 = **Round 41**「Runbook 增加 MIR 分离命令；MIR rawdec vocal smoke 完成」。
[事实] Jamendo **从未运行**（`20260816_productization_validation_report.md:12`）。

**H2｜0814 轮未闭合**：
`01_CURRENT_EXPERIMENT_RESULTS_AND_CONCLUSIONS.md:245-253` 列 9 项未闭合；
`RUN_STATE.md:14` 待 formal 补齐 5 项（真实 B4 对齐替换 raw stand-in、
`<out>/scientific/` 纳入 rerender hash、第 4 路、WP3 真实 wall_time、WP4 串行链 identity 脆弱性）；
`08_SESSION_FINAL_REPORT.md:173-179` 5 项 pre-formal 必做（含接真实 `detector_p_bad`/posterior）；
`09:64-67` 扩 E2/E3 到 40 区域、用真实 collection 做 formal 四路渲染、灾难性归因、自适应 recrop。
[事实] **3M 证据包仍未完成**（`00:1284`、`00:1313`）。
[事实] `RUN_STATE.md:83` 遗留：WP8 自适应真实化、E6 atlas 证据匹配、E2 剩余方向。

**H3｜制度性挂起**：`06_PLANNED_RUNS.yaml:2` 状态字段仍为
`implementation_complete_formal_gpu_pending`，而 `09`（22:36）已有真实非 smoke 前向结果、
`00:1256` 已有 33 首 A 组完成 → [推断 0.9] 状态字段过期，
尽管 `07:334` 明文要求 `planned→done` 同步。

## 2.3 风险（LA）

| # | 风险 | 严重度 | 证据 | 缓解建议 |
|---|---|---|---|---|
| **R1** | 两周成果未提交未推送（124 ahead + 93 未提交），且冻结基线记录在 dirty tree 上 → 不可复现 + 单点丢失 | **P0** | §1.4；`.dsh/review5_evaluation_v1.md:38` | 先分批 commit（脚本/结果/文档三批），再重做 identity freeze；本任务不执行 |
| **R2** | 契约层 override 未更新到 0816，新 agent 按 `AI_SESSION_ENTRY.md:232-233` 会先读 7-28 过期快照 | **P0** | §1.1、P0 §4.1 | 补 override 条目 + 重排必读顺序 |
| **R3** | 核心科学结论方向相反且未调和：`09:58-59`"核心假设成立" vs `00:1294-1300` recovered 0% | **P1** | §2.1-C | 给 `09` 加口径注解，或在 README 写统一裁决 |
| **R4** | 混合门无效使"raw decoder 产品化"缺少选择信号 | **P1** | `..._validation_report.md:203-206` | 按 `:206` 找新信号；不要把 raw 直接设默认 |
| **R5** | 许可风险：GTSinger 附加赔偿条款未澄清、AMLL 第三方权未决、iKala 未授权 | **P1** | `00:104-107,83-84,111` | 对外 demo 只用 PJS(CC BY-SA)/自有数据；GTSinger 仅内部 |
| **R6** | 日语/粤语结论仅结构性（PJS 无音素 GT、yue n=3） | **P2** | `review8:19`；`00:156` | 报告中显式标注适用边界 |
| **R7** | 反引号 `runs/` 路径失效率 11.4%，违反 `AGENTS.md:147` | **P2** | P0 §5.2 | P4 批量改写前缀 |

## 2.4 开放问题（LA，文档中已明写的）

[事实] ① split manifest 未 review/冻结，per-dataset song-ID 分配未定
（`README.md:41-42`；`milestones:7`）——draft SHA `f04e0b9b959907a87965c581a615dd1d74b03dbd88dce837e2cc97927602ed8f`
（`03_PRODUCTIZATION_EVALUATION_V1_NEXT_STEPS.md:20-21`），
draft 分配 MIR cmn 4/10/6、yue 1/1/1、Jamendo 4/10/6、PJS 20/50/30、GTSinger 1/2/2（`:46-50`）。
② sealed runner 的访问控制/频次/报告可见性策略未实现，sealed 从未运行（`README.md:44`；`final:40`）。
③ 老模型在新数据上的 baseline、behavior registry 单因素消融、sealed 里程碑协议均未做（`00:189-191`）。
④ GTSinger 技法混淆：每技法仅 1 个 song root，无法把技法效应归因到 split（`00:155`）。
⑤ 需要"raw + overlap 修复"还是另找不同于最终 overlap 门的选择信号（`..._validation_report.md:206`）。
⑥ `AI_SESSION_ENTRY.md:293-306` 的 12 项 "Current unknowns"（30s vs 60s、静音感知边界是否有益、
shared raw planning 对 official 退化的贡献等）——[推断 0.7] 这批问题成文于 8-14 前，
部分已被 0813/0814 数据回答，但未回写。

## 2.5 未来可能性（LA）

### 文档中已记录的
[事实] ① `AI_SESSION_ENTRY.md:20-32` 的 8 步 stage 路线（冻结基线 → 可视化 adapter →
multi-realign/细分/recrop 研究 → R-U coarse→bounded refinement 试点 → 仅扩展有严格恢复证据的机制 →
无 GT 候选/安全信号 → recovery-basin atlas 与串行累积误差压力测试 → B4-vs-Current 与四路诊断视频）。
[事实] ② `03_PRODUCTIZATION_EVALUATION_V1_NEXT_STEPS.md:67` 的研究登记表含
"安全/恢复 | shadow writeback、no-GT gate、multi-iteration、recrop/split" 一行，
配套 `reports/behavior_registry.json:176,185-186` 的 `safety.no_gt_gate` 假设
（gate = "regression_selection only after diagnostic signal study"）。
[事实] ③ `05_NEXT_ACTIONS.md` 五条（见 H1）。
[事实] ④ `04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md:151` 与 `06_PLANNED_RUNS.yaml:55`
定义了**会自我再生的递归自由探索 todo 循环**。

### [推断] 我的判断（附置信度）
- **F1 [推断 0.85]｜realign-recovery 应降级为"已充分探索的负结果"**，
  不再投入大规模 GPU。依据：884 区域 recovered 0% + 65.4% catastrophic（§2.1-C）。
  可保留的是**机制性副产品**：R-CF 的 0ms 固定上下文位移（15/15）说明"有界精修不污染上下文"
  这一工程性质是可靠的，可用于**安全约束**而非**质量提升**。
- **F2 [推断 0.9]｜真正的产品线是 "R2 + vocal + windowed + raw decoder" 的对齐服务**，
  因为它是唯一有真实 GT 支撑的数字（90.1%→91.84% both_100ms）。
  下一步价值最高的是把 overlap 修复做成后处理，而不是继续 realign。
- **F3 [推断 0.8]｜可视化可以独立成为对外交付物**（686 mp4 已存在），
  且它不依赖任何未决的科学结论——这使它成为最低风险的 demo（见 P2）。
- **F4 [推断 0.6]｜多语言扩展受数据许可与 GT 缺失双重限制**，
  日语（PJS 有音素标注但未映射 GT）是最近的一步；粤语 n=3 短期无望。
- **F5 [推断 0.5，证据不足]｜训练/微调新模型**：0816 全线"no training"，
  且 `AI_SESSION_ENTRY.md` 无新训练计划。读过 0816 全簇 + status 未找到新训练路线，
  故不能断言这是既定方向；仅列为可能性。

---

# 第三部分：AST 主线状态

## 3.1 已完成（挂证据）

[事实] ① P0/P1 全修复 + 回归测试补齐（3 轮 review 循环通过），全量 **247 passed**
（`AI_SESSION_ENTRY.md:33`）。
[事实] ② run1 全 stage 完成：pca、joint_cache×3、joint_train×5、joint_select×5、
causal E3 baseline 重训（新 LayerNorm 基线）、E1–E5 训练+eval、全路线 deep audit
（`AI_SESSION_ENTRY.md:33`；`RUN1_RESULTS.md:8-12`）。指标见 §1.5。
[事实] ③ **两步式 select 改造完成并跑通**：动因是耦合网格对每候选扫 36 组合且与设计文档
L.155"validation 只选共同参数"相悖（`HANDOFF_20260814_select_twostage.md:7-9`）；
计算量 `候选数×36 → 1×36`（`:21`）；实测 5 头串行 **2h31min** 全部 rc=0（`:56`）。
[事实] ④ 顺带修掉一个 OOM 缺陷：原 stage1 把每候选完整验证推理缓存进 `val_cached_by_path`
（≈2.6 GB/候选 → 48 候选 ≈125 GB > cgroup 90 GB），实测 33 候选=86 GB 后被 OOM-kill；
改为逐候选 `del + gc.collect()`，stage2 对 winner 重新推理一次（+~40 s），科学结果不变（`:51-53`）。
[事实] ⑤ eventizer 5 模式续训推进：history.csv 从 6 行长到 25/20/27/61/34 行
（baseline/posterior/latent/all/acoustic），`best.pt` + `selection.json` 均 08-14 18:00–18:11；
另有 `eventizer/fv2_acoustic_only/selection.json`（**08-15 00:00**）。
[事实] ⑥ 外部模型复现：ROSVOT 官方 ckpt 重跑（最优 `thr0995_on075_off000`，与 round3 的 61.50 吻合）、
VOCANO 45 首重跑、Basic Pitch `eval_unified/`；
根因结论：差距来自 thr(0.8→0.995)+shift(75ms)，非代码错误；
且 round3 用 Hungarian 最大权匹配、20260801 统一管线用最大基数匹配（`HANDOFF_20260814.md:60-63`）。
[事实] ⑦ Windows GUI 成体系存在：源码 `src/apps/feat6_gui/{__init__,app,audio_worker,backend_interface,model_worker}.py`，
入口 `python -m apps.feat6_gui.app`（`Start_AST_Demo.bat:23`）；
辅助 `scripts/windows/{verify_checkpoints,verify_environment,check_default_output_dir}.py`
+ `build_feat6_gui_exe.ps1`；打包 `packaging/pyinstaller/feat6_gui.spec`；
文档 `docs/manual/PESTO_FEAT6_WINDOWS_GUI.md`(204 行)、
`docs/manual/demo/windows_portable_release.md`(109 行)、`demo_v1_freeze.md`(166 行)。

## 3.2 挂起项与阻塞（AST）

[事实] **真正未闭合的阻塞**（`RUN1_REVIEW.md:13`；`RUN1_RESULTS.md:46,54,97-98`；
`project_current.md:34`；`select_twostage.md:153-156,196-199`）：
1. **runtime/RTF/实际总延迟 artifact 缺失**，deep audit 仍 `partial_with_not_available`
   → 正式 winner 无法定稿。（posterior drift 已补：KL 0.0016–0.0037、pitch argmax 一致率 99.36–99.56%）
2. **新的冻结 final/OOD split 缺失**：eval45 已多轮访问，不可再作论文级 test。
3. latent/all 的负结果被降级为"未标准化 PCA32 + 短训练"，
   train-only scaling + PCA32/64 复验**未执行**。
4. 存量测试失败 `test_stage_runner_partial_never_reused_as_done`，
   经 git stash 验证与本轮改动无关，记 backlog。
5. §7.4/§8.4 待办：纯声学 `fv2_acoustic_only` 60 epoch 完成后读 selection、
   用 `EVED_HEAD_KEEP=0` 重跑 eval45、回答"能否不用 pesto"
   —— 其 selection.json 已于 08-15 00:00 落盘，进程已退出。
6. [推断 0.7] `rerun_eventizer_selection.py` 的 eval45 冻结环节**可能尚未按纪律执行**：
   `eventizer/*/selection.json` 是 08-14 18:00–18:11 新值，
   但 `eventizer_eval/*` 目录 mtime 仍为 08-06 15:17–17:40（旧）；
   08-14 的产物疑由 `decoder_cf/eval45_final/`（08-14 20:06）另一路径产生。
   **这是收尾链上最可能被漏掉的一环**，建议下一轮优先核对口径归属。

[事实] **硬禁令**：不要整跑 `launch_causal_convergence_continuation.sh`（会 resume 重进训练）；
residual 在 `$RUN/eventizer/residual/` 而非 `$RUN/residual/`（`selection_status.md:84,86`）。
[事实] 当前**无任何相关进程在跑**（`ps aux | grep -E "train_e_series|select_evaluate|rerun_eventizer|train_eventizer"` 为空）。
[事实] `evidence_pack.zip`（08-06 20:12）是续训前 6-epoch 快照，**不得当最终证据**（`HANDOFF_20260814.md:71`）。

## 3.3 风险（AST）

| # | 风险 | 严重度 | 证据 |
|---|---|---|---|
| **AR1** | `HANDOFF_20260814_selection_status.md:9-10,85` 主动误导：断言 select 未跑、禁止读真实产物，而产物是新的 | **P0** | §1.6 |
| **AR2** | 主线不在 `main` 上：当前分支 `codex/merge-stage1overnight-fast-validation-20260721` 相对 `main` **ahead 60**；27 项未提交（含两步式 select 改造与全部交接文档） | **P0** | `git rev-list --count main..HEAD`=60；`git status --porcelain` 27 项 |
| **AR3** | 汇报口径双轨未写入契约：150ms/100cent 汇报口径只在 `select_twostage.md:68`，AGENTS.md/AI_SESSION_ENTRY.md 均无 → triangle 51.88@100/50 与 68.26@150/100 极易被当同口径比较 | **P1** | `select_twostage.md:68` |
| **AR4** | eval45 已多轮访问，无冻结 final split → 任何"正式结论"都有过拟合嫌疑 | **P1** | `RUN1_RESULTS.md:98`；`project_current.md:34` |
| **AR5** | 三代 Eventizer 数字混比：old fv2_h4 60.98/41.95、prefix-safe E3 59.50/43.42、causal baseline 53.18/38.38 是不同模型，"严格流式回落"是错误表述（真因是训练时长 5 vs 160 epoch） | **P1** | `HANDOFF_20260814.md:68` |
| **AR6** | status 文档滞后 8–9 天，三份 handoff 都把"更新 status"列为最后待办且未执行 | **P2** | `selection_status.md:80`；`select_twostage.md:77` |
| **AR7** | `tools/baidu_netdisk_aggregate/` 与主线无关且是仓库最新改动、未跟踪 | **P2** | P0 §4.4 |

## 3.4 未来可能性（AST）

### 文档中已记录的
[事实] ① `next_execution_plan.md:5` `primary_next: review_run1_results_and_finalize_conclusions`，
`final_test_selection: forbidden`。
[事实] ② 收尾链（`selection_status.md:75-80`；`select_twostage.md:74-77`）：
select×5 → eventizer×5（`train_e_series.py --epochs 60 --val_every 1 --decode_val_every 1
--patience 10 --min_epochs 15 --resume`）→ residual（base=`$RUN/eventizer/causal_e3_baseline/best.pt`）
→ `rerun_eventizer_selection.py --run-root $RUN --device cuda --skip-deep-audit`
→ preflight + 全量测试 + 更新 status 文档。
[事实] ③ 外部模型对比：3 = ROSVOT/VOCANO/Basic Pitch；
2 = 两档容差呈现口径（100ms/50c 与 150ms/100c）
（`HANDOFF_20260814.md:59-62`；"3×2 矩阵"一词只在 `:9`、`:59` 出现，
`reports/research/20260806_external_model_reproduction.md` 中 NOT FOUND，
故"2"的轴由数字反推，置信 0.9）。
未完成：**FCPE 未复现**（用户指示跳过；论文模型 DDSP-200K ≠ 仓库 `fcpe_c_v001`）、
**VOCANO 未复现论文口径**（官方指标为音符级编辑距离，范式不同，且 CMedia/ISMIR2014 demo 数据缺失）。
[事实] ④ `docs/owner/demo_future_roadmap.md`（2026-07-15）存在但已 6 周未更新。

### [推断] 我的判断（附置信度）
- **AF1 [推断 0.9]｜AST 距离"可定稿"只差一个 runtime/latency 证据补齐 + 一个新冻结 split**，
  科学主体已完成。这两项都不需要重训，成本远低于任何新实验。
- **AF2 [推断 0.85]｜最高性价比动作是"文档一致性修复"而非新实验**：
  select 已跑完但三份 handoff 互相矛盾（§1.6、§3.5），
  下一轮 agent 极可能重跑 2.5h 的 select 或据假前提决策。
- **AF3 [推断 0.7]｜Windows GUI 是现成的对外展示资产但当前不可用**：
  需 Windows 机器 + `runtime_env\.venv` + 冻结 feat6 checkpoint 放
  `checkpoints\feat6\best.pt` + PESTO 权重放 `models\pesto_upstream` + 麦克风；
  `verify_checkpoints.py` 失败即拒启动；当前 Linux 服务器上无法直接跑 `.bat`。
- **AF4 [推断 0.6]｜"能否不用 pesto"（纯声学路线）是最有科学新意的开放问题**，
  且 `fv2_acoustic` 已是 Eventizer 最优（54.82/40.23，+1.85），
  `fv2_acoustic_only` selection 已落盘 → 只差 `EVED_HEAD_KEEP=0` 重跑 eval45。

## 3.5 AST 文档矛盾清单（供 P4 用）

| # | 矛盾 | 双方证据 | 裁决 |
|---|---|---|---|
| 1 | select 是否跑过（三方冲突） | `HANDOFF_20260814.md:27-31`"进行中 pid 161375 已跑 2.5h+" / `selection_status.md:4,10,69`"一次都没执行过、PID 不存在" / `select_twostage.md:56`"✅ 全部完成 2h31min" | **磁盘裁决 twostage 正确**（mtime 13:55–15:46 吻合），前两者过期 |
| 2 | Codex review 是否完成 | `RUN1_RESULTS.md:96`已完成 / `project_current.md:28`+`next_execution_plan.md:18`待复核 | 日期新者优先 → 已完成 |
| 3 | select 耗时量级两次翻案 | 2.5h+/头未完成(`HANDOFF_20260814.md:30`) → "数量级错误，预估 30-60min"(`selection_status.md:68`) → 实测 40-45min/头(`select_twostage.md:48`) | 真因是内存泄漏 OOM-kill 而非算力；`selection_status.md:60`归因"CPU 单核 decode 瓶颈"不完整（[推断 0.85]） |
| 4 | 并行 vs 串行 | `selection_status.md:75-76`建议并行 5 头 / `select_twostage.md:31`"本机多路并行不可靠，改串行" | 后者为实测教训，优先 |
| 5 | 汇报口径 | 150/100c 仅在 `select_twostage.md:68`，未入契约 | 需回写（AR3） |
| 6 | status as_of | 全部 2026-08-06/07-31，实际工作到 08-15 | 过期 |

---

# 第四部分：跨仓共性结论

1. [事实] **两仓完全同构的失效模式**：契约/状态层滞后于工作树，
   最新成果全部未提交，交接文档互相矛盾且新文件可能记录更旧状态。
   LA：override 停在 08-14 / 工作到 08-16；AST：status 停在 08-06 / 工作到 08-15。
2. [事实] 两仓 `AGENTS.md` 均在 2026-08-17 02:39–02:42 被同一批操作追加全局纪律
   （LA +52 行 → 226 行；AST +52 行 → 153 行，`git diff --stat AGENTS.md`
   = `76 insertions(+), 3 deletions(-)`，相对 bak 为纯追加 `101a102,153`），
   **但都没顺手更新各自的主线指针** → 同一次机械迁移放大了 R2/AR6。
3. [推断 0.9] 两仓当前最高价值动作都不是"跑新实验"，而是
   **提交 + 回写契约 + 消除矛盾文档**。这直接决定 P2 的第 1 天安排。
4. [事实] 两仓共享同一 conda 根 `/root/autodl-tmp/AST_storage/conda/envs/`
   （LA 用 `lyricalign-qwen`，AST 用 `pesto` 等），且 LA 的 run 数据在
   `/home/hyan/Data/lyricalign/runs/`、AST 在 `/home/hyan/Data/ast_runs_formal/`
   —— 两仓都遵循"大数据外置"纪律。
