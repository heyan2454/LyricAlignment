# P3 — 一月路线图（plan_1m_roadmap）

**口径声明**：本文以 P2 的一周 demo 计划为第 1 周，规划第 2–4 周。
资源预算按 P1 §1.3 的结论标注 —— **GPU 不是瓶颈**（实测 E1 200 forwards = 54 s，
E4 = 20 s，而预算是 ≤10h/≤12h），真实约束是
**① 有 GT 的样本量 ② 数据授权 ③ 收尾与文档工时**。因此预算主列"人力工时"，GPU 只在必要处标注。

标签：`[事实]` / `[推断（置信度）]` / `[建议]`。

---

## 0. 与一周计划（P2）的关系

| P2 产出 | 在 P3 中的角色 |
|---|---|
| Day1 提交 + 契约回写 | **主题 A 的第一步**。P3 全部主题都依赖"仓库可复现"这一前提 |
| Day2–4 LA 可视化 demo | **主题 E 的对外出口**；同时验证主题 C 的展示通道 |
| Day5 AST provisional 报告 | **主题 F 的草稿**；F 的目标是把它从 provisional 升级为可定稿 |
| Day6 gate 附录（诚实呈现为开放问题） | **主题 C 的问题陈述**，C 负责真正解决 `:206` 的开放问题 |
| Day7 打包 + 文档回写 | 建立 P3 每周复用的收尾节奏 |

[推断 0.9] **P2 与 P3 不是"演示 vs 研发"的割裂**：P2 刻意选了两个零科学风险的交付物，
其真实作用是**在不消耗科学预算的前提下，先把工程与文档地基补齐**，
使 P3 的五个主题都能在可复现的仓库上启动。

---

## 1. 主题分组总览（10 个主题，按仓库分两组）

| # | 主题 | 仓库 | 优先级 | 预估工时 | 是否需 GPU |
|---|---|---|---|---:|---|
| **A** | 证据完整性与契约治理 | 两仓 | **P0** | 10–14 h | 否 |
| **B** | evaluation-v1 冻结与 sealed 通路 | LA | **P0** | 16–22 h | 少量 |
| **C** | 对齐质量提升：raw decoder + overlap 修复 | LA | **P1** | 20–28 h | 中等 |
| **D** | 多语言定量扩展（日/英） | LA | **P1** | 18–24 h | 中等 |
| **E** | realign-recovery 收尾归档（负结果成文） | LA | **P2** | 8–12 h | 否 |
| **F** | run1 定稿（补证据链） | AST | **P0** | 12–16 h | 少量 |
| **G** | 新冻结 final/OOD split | AST | **P0** | 8–12 h | 少量 |
| **H** | 纯声学路线（能否不用 PESTO） | AST | **P1** | 10–14 h | 中等 |
| **I** | 外部模型对比收口 | AST | **P2** | 8–12 h | 否 |
| **J** | 主线合回 main + Windows GUI 复活 | AST | **P2** | 6–20 h | 否 |

**合计 116–174 h**。[推断 0.85] 按每周 25–30 h 有效工时、剩余 3 周计 75–90 h
→ **必须裁剪**。裁剪方案见 §4。

---

## 2. LA 主题详述

### 主题 A｜证据完整性与契约治理（P0）

**目标**：让两个仓库从"成果只存在于工作树"回到"成果可从 commit 复现"，
并消除主动误导性文档。

**动作**（= P2 Day1 + P4 的 T0/T1-1/T1-5/T1-7）
1. LA 分 3 批提交 93 项 + 推送 124 commit；AST 提交 27 项。
2. 在 clean tree 上**重做 baseline identity freeze**（解决 `.dsh/review5_evaluation_v1.md:38`
   "冻结记录在 dirty tree 上"）。
3. P4 的 T0-1…T0-12（12 条契约修复，其中 T0-5 的 superseded 头部收益最高）。

**阶段 gate**
```bash
# G-A1：两仓工作树干净且已推送
cd /home/hyan/LyricAlignment && test $(git status --porcelain | wc -l) -eq 0 && test $(git rev-list --count @{u}..HEAD) -eq 0
cd /home/hyan/AST && test $(git status --porcelain | wc -l) -eq 0
# G-A2：契约层已回写
grep -q "2026-08-16" /home/hyan/LyricAlignment/AI_SESSION_ENTRY.md
grep -qi "superseded" /home/hyan/AST/docs/sessions/explore/20260806_pesto_causal_12h_program/HANDOFF_20260814_selection_status.md
# G-A3：identity freeze 可复现（记录了 commit 而非 dirty diff）
grep -rn "commit\|git_sha" <baseline_identity 产物路径> | head
```
**资源预算**：10–14 h 人力；0 GPU；无数据依赖。
**风险**：① 分批提交时误把大资产入库 → 用
`git status --porcelain | grep -Ei '\.(mp4|wav|pdf|zip)$'` 拦截（`AGENTS.md:152-153`）；
② AST 合回 main 产生冲突（ahead 60）→ 本主题只提交**不**合并，合并归主题 J。

---

### 主题 B｜evaluation-v1 冻结与 sealed 通路（P0）

**目标**：把 LA 的评测底座从"draft"推到"可出正式结论"。这是 0816 轮**唯一未闭合的主干**。

**[事实] 当前缺口**（`20260816_productization_milestones.md:7,25,31,36,39,40`）：
split 冻结/review 未做、vocal-only 正式评测未做、sealed 端到端未做、sealed 报告未出。
draft manifest SHA = `f04e0b9b959907a87965c581a615dd1d74b03dbd88dce837e2cc97927602ed8f`
（`03_PRODUCTIZATION_EVALUATION_V1_NEXT_STEPS.md:20-21`）；
draft 分配 MIR cmn 4/10/6、yue 1/1/1、Jamendo 4/10/6、PJS 20/50/30、GTSinger 1/2/2（`:46-50`）。

**动作**
1. **review 并冻结 split**：逐条核对 `02_EVALUATION_V1_NO_TRAINING_PLAN.md:17-23` 的 6 项约束
   （按 song/song-root 分组、保持 MIR 官方 Train/Test 边界、PJS 同 ID 三件套同组、
   记录算法+seed+revision+manifest SHA、sealed 需 `--allow-sealed`）。
2. 解决 GTSinger 技法混淆的**声明**（每技法仅 1 song root，无法归因 → 写入限制而非硬修，`00:155`）。
3. **vocal-only 正式评测**：先做 MIR/Jamendo 的人声派生（demucs），记录分离器
   identity/config/IO hash（`05_NEXT_ACTIONS.md:7-10`）。
4. sealed 通路端到端演练：`guarded_run.py --allow-sealed`，并**先制定访问控制/频次/报告可见性策略**
   （`README.md:44` 明确该策略未实现）。
5. sealed 只跑**一次**，出 sealed 报告。

**阶段 gate**
```bash
# G-B1：split 冻结（SHA 记录 + 拒绝越权访问）
python scripts/evaluation/check_split_access.py --help                    # 脚本已存在
PYTHONPATH=src python scripts/evaluation/guarded_run.py --manifest <full> -- echo should_not_run
echo "expect exit code 2"; # 依据 04_PRODUCTIZATION_RUNBOOK.md:69-71
# G-B2：泄漏审计通过（无 group 跨 tier、item_id 唯一）
ls <split_root>/evaluation_v1_leakage_audit.json && python3 -c "import json;d=json.load(open('<...>'));print(d)"
# G-B3：vocal 派生有 provenance
python3 -c "import json;d=json.load(open('<vocal_plan>.json'));assert d.get('separator') and d.get('config_hash');print('OK')"
# G-B4：sealed 仅运行一次（可审计）
grep -c "allow-sealed" <sealed run log>    # 期望 1
```
**资源预算**：16–22 h 人力；demucs 分离需 GPU（[推断 0.7] 20 首 MP3 + 20 首 MIR ≈ 1–2 h GPU）；
磁盘：派生物入 `/home/hyan/Data/lyricalign/derived/`（`01_DATA_ACQUISITION_RESULT.md:25-26`），
按 0816 惯例每批出 `cleanup_report.md`。
**风险**：⚠️ **sealed 一旦跑过就不再"未触碰"** → 必须先把策略写死再跑，
否则重演 AST 的 eval45 困境（P1 §3.3-AR4）。**[建议] 本主题的 gate 必须由人工签署，不可由 agent 自行放行。**

---

### 主题 C｜对齐质量提升：raw decoder + overlap 修复（P1）

**目标**：把 P2 Day6 附录里的开放问题真正解决 —— 拿到 raw decoder 的收益，
同时不引入 overlap 退化。

**[事实] 问题定义**（全部来自实测）：
- raw 一致更优：diagnostic 90.05→**91.84**（+1.79pp，20 改善/2 回退/53 不变）
  （`20260816_productization_validation_report.md:134,137`）；
  hard18 78.32→**84.47**（14/0/4）（`:124,126`）；
  regression 87.47→**89.49**（22/1/61）（`:171-173`）。
- 但 raw 把最终零时长从 44→9 的同时**新增 selected/跨窗 overlap**（`:178,180`）。
- 严格门 33/75 通过；raw 在 regression 门上 45/39 反而比 official 53/31 差（`:192-193,197-198`）。
- **混合门无效**：增益全在 raw 门失败子集（39 项，82.52% vs 86.44%），
  门通过子集两者同为 92.72%（`:203-205`）→ `:206` 显式提出"需要 raw + overlap 修复，
  或不同于最终 overlap 门的选择信号"。

**动作**
1. 实现 **overlap 后处理修复**（而非用门筛掉）：对 raw 输出做单调化/去重叠约束，
   目标是"保住 +1.79pp 同时把 overlap 降到 official 水平"。
2. 若后处理不足，再找**前置选择信号**（`:206` 的第二条路）：候选信号可从
   `scripts/evaluation/extract_unit_gate_features.py`（LA `scripts/unit_realign/` 内同名工具）
   与 `reports/behavior_registry.json` 的 `safety.no_gt_gate` 假设出发
   （gate = "regression_selection only after diagnostic signal study"，`:185-186`）。
3. **可复用主题 E 的机制性副产品**：R-CF 的 `fixed_context_displacement_ms = 0.0`（15/15，
   `09_GPU_REAL_RUN_REVIEW.md:29-31`）证明"有界精修不污染上下文"，
   这个**工程性质**可直接用于 overlap 修复的安全约束。

**阶段 gate**
```bash
# G-C1：修复后在 diagnostic 75 段上不低于 raw 且 overlap 不高于 official
# 数字必须由脚本从 JSON 复算（AGENTS.md:220 禁止手抄）
python3 - <<'EOF'
import json
a=json.load(open('results/comparisons/20260816_gtsinger_regression_official_vs_rawdec.json'))
# 新增 fixed 版本后对比三元组：both_100ms 提升 & overlap_count 不升
EOF
# G-C2：paired 检验有改善/回退计数（口径同 02_EVALUATION_V1_NO_TRAINING_PLAN.md:99）
# G-C3：不得依赖 GT 做选择（no-GT 约束，AI_SESSION_ENTRY.md:37 "GT is evaluator-only"）
grep -rn "gt\|ground_truth" <新选择器源码> | grep -v test | head   # 人工确认无 GT 读取
```
**资源预算**：20–28 h 人力；GPU 少量（复用已有 alignment，尽量 cache-only）；
数据：GTSinger 75 段 + hard18（已有）。
**风险**：① [推断 0.6] overlap 与精度可能存在**真实 trade-off**，后处理未必两全 →
gate 允许"部分达成"并如实记录为 bounded-insufficient（`AGENTS.md:219` 的状态语义）；
② 禁止用 test/OOD 调阈值（`AGENTS.md:154`"checkpoint 只许 validation 选择"）。

---

### 主题 D｜多语言定量扩展（P1）

**目标**：把日语与英文从"仅结构性结论"推到"有定量 GT"。
[事实] 现状：只有中文 GTSinger 有真实定量 GT；PJS 无音素级 GT 映射 → 日语结论仅结构性
（`.dsh/review8_productization_status.md:19`）；yue n=3 仅探索性（`00:156`）；
Jamendo **从未运行**（`..._validation_report.md:12`）。

**动作**
1. **日语**（优先，`05_NEXT_ACTIONS.md:3-6` 的第 1 优先）：PJS 音素级 GT 映射
   → 量化日语 raw decoder。PJS 有 100 份人工重标音素文件 + CC BY-SA 4.0 授权（`00:89-92`）→
   **授权与素材都最干净**。
2. **英文**：Jamendo 人声派生后首次运行（20 MP3、5693 词区间、868 行区间，`00:96-97`）。
   注意 `00:99-100` 明确：**未做人声派生前不构成有效 operational benchmark**。
3. 报告分语言、分粒度，**严禁跨 word/char/phoneme 汇总**
   （`02_EVALUATION_V1_NO_TRAINING_PLAN.md:92-99`）。

**阶段 gate**
```bash
# G-D1：日语有定量数字（非 warning-only）
# 现状对照：PJS 5-seg 批次 113 个日语词单元，R2 仅 2 passed/3 warning（..._validation_report.md:82-83）
# G-D2：Jamendo 首次产出 word-level 指标且记录 6 种 per-song 许可
python3 -c "import json;d=json.load(open('<jamendo_summary>.json'));print(d['n_items'], d['metric_granularity'])"
# 期望 metric_granularity == 'word'，且不与 char 结果合并
```
**资源预算**：18–24 h；GPU 中等（Jamendo 20 首 + PJS 100 首的对齐前向）。
**风险**：⚠️ **许可**（P1 §2.3-R5）：Jamendo 6 种 per-song 许可需逐首核对；
对外展示优先 PJS（CC BY-SA 4.0）。GTSinger 附加赔偿条款未澄清 → 仅内部。

---

### 主题 E｜realign-recovery 收尾归档（P2）

**目标**：把一条**负结果**做成高质量科研资产，然后正式关闭这条线。
[推断 0.85] 这是本路线图里最容易被忽略但学术价值最高的一项 ——
884 区域 ×3 家族的 `recovered 0%` 是一个**干净的、大样本的否证**。

**动作**
1. 补完 **3M 证据包**（`00_SESSION_DISCUSSION_RECORD.md:1284`、`:1313` 仍未完成）。
2. 写一份《realign recovery 负结果报告》，把三组数字并列：
   - B 组 884 区域：R-U ok 87.9% / collateral 100% / recovered **0%**；
     R-S ok 51.2% / recovered **0%**；R-CF ok 83.0% / catastrophic 6.8% / recovered **0%**（`00:1294-1300`）
   - 0813 formal 78 区域（有 GT）：beneficial 25.6% / catastrophic_harmful **65.4%**（`00:1167-1176`）
   - 对照 E4 stage-B 15 区域的乐观数（`09:55-60`）并解释**分母差异**
3. 保留机制性正结论：R-CF 的 0ms 固定上下文位移（15/15）→ 移交主题 C 作安全约束。
4. 执行 P4 的 T0-11（给 `09:58-59` 加口径注解）。
5. 关闭 `RUN_STATE.md:83` 的三项遗留（WP8 自适应真实化、E6 atlas 证据匹配、E2 剩余方向），
   每项显式标 `completed` / `bounded-insufficient` / `abandoned-with-reason`
   （`AGENTS.md:219` 要求每项都有显式状态才允许结论）。

**阶段 gate**
```bash
# G-E1：三个分母的数字同页并列且都可溯源
grep -c "1294\|1167\|09:5" <负结果报告>       # 每个数字都带证据行号
# G-E2：证据包存在且不入 git（AGENTS.md:152-153）
du -sh <3M evidence pack 路径>
cd /home/hyan/LyricAlignment && git status --porcelain | grep -c 'evidence_pack' # 期望 0
# G-E3：遗留项状态齐全
grep -cE "completed|bounded-insufficient|abandoned-with-reason" <RUN_STATE 或收尾报告>  # 期望 >= 3
```
**资源预算**：8–12 h；0 GPU（纯 CPU 分析与写作）。
**风险**：低。[建议] 这是**性价比最高**的主题之一 —— 无算力、无授权、无依赖，
纯写作即可把一条已死的线转成可引用资产。

---

## 3. AST 主题详述

### 主题 F｜run1 定稿（P0）

**目标**：把 `provisional_internal_screening`（`EXPERIMENT_REPORT.md:3`）升级为可定稿结论。

**[事实] 唯一阻塞是证据缺口**，不是科学缺口（`RUN1_REVIEW.md:13`；`RUN1_RESULTS.md:46,54,97`）：
① runtime/RTF/实际总延迟 artifact 缺失；② deep audit 仍 `partial_with_not_available`。
（posterior drift 已补齐：KL 0.0016–0.0037、pitch argmax 一致率 99.36–99.56%。）

**动作**
1. 补 runtime/RTF/latency 测量。注意严格流式契约要求总延迟 =
   PESTO 前端 lookahead + head 显式 lookahead，且 O&F 级联左历史 124 帧、
   其余 head 62 帧（`AI_SESSION_ENTRY.md:25`）→ **latency 必须按此口径报告，不能只报墙钟**。
2. 把 deep audit 从 `partial_with_not_available` 补到完整，或**显式声明哪几项不可得及原因**。
3. **核对 P1 §3.2 第 6 项的疑点**（[推断 0.7]）：
   `eventizer/*/selection.json` 是 08-14 18:00–18:11 新值，
   但 `eventizer_eval/*` 目录 mtime 仍为 08-06 15:17–17:40（旧）；
   需判定 08-14 产物是否由 `decoder_cf/eval45_final/`（08-14 20:06）另一路径产生，
   即 `rerun_eventizer_selection.py` 的 eval45 冻结环节是否真的执行过。
4. 定稿报告纳入两步式 select 结果（triangle ep30 / **68.26** @150ms-100cent，
   `HANDOFF_20260814_select_twostage.md:59-64`），双口径分栏。

**阶段 gate**
```bash
RUN=/home/hyan/Data/ast_runs_formal/pesto_causal_12h_run1_20260806
# G-F1：五头 selection 均为 two-stage 且 complete（已验证通过，作为回归基线）
python3 - <<'EOF'
import json,glob,os
ps=sorted(glob.glob(os.environ['RUN']+"/joint_eval/*/selection.json"))
assert len(ps)==5
for p in ps:
    d=json.load(open(p)); assert d['status']=='complete' and 'two-stage' in d['selection_procedure']
    print(d['head'], d['selected_epoch'], d['selected_thresholds'])
EOF
# G-F2：runtime/latency artifact 存在且含流式口径字段
find $RUN -name '*runtime*' -o -name '*latency*' -o -name '*rtf*' | head
# G-F3：deep audit 不再是 partial（或已显式声明不可得项）
grep -rn "partial_with_not_available" $RUN | head
# G-F4：eventizer eval45 口径归属已判定并成文
ls $RUN/decoder_cf/eval45_final/final_summary.json
# G-F5：全量测试通过（AGENTS.md:15）
conda run -n pesto python -m pytest -q 2>&1 | tail -3     # 基线 247 passed
```
**资源预算**：12–16 h；GPU 少量（latency 测量需真实推理，但短）。
**风险**：① 已知存量测试失败 `test_stage_runner_partial_never_reused_as_done`
（经 git stash 验证与本轮改动无关，记 backlog，`select_twostage.md:153-156`）→ 不阻塞定稿但需登记；
② **硬禁令**：不要整跑 `launch_causal_convergence_continuation.sh`（会 resume 重进训练，
`selection_status.md:84`）。

---

### 主题 G｜新冻结 final/OOD split（P0）

**目标**：解决"eval45 已多轮访问，不可作论文级 test"（`RUN1_RESULTS.md:98`；`project_current.md:34`）。
[事实] selection.json 内建自认：`"eval45_policy": "internal repeatedly visited evaluation;
not untouched final test"`（我直接读取该键验证）。

**动作**
1. 定义并冻结一个**从未访问**的 final/OOD split；记录算法+seed+manifest SHA。
2. 建立访问闸门（类比 LA 的 `guarded_run.py --allow-sealed`），使误用需显式授权。
3. `next_execution_plan.md:5` 已有 `final_test_selection: forbidden` → **保持该禁令**，
   本主题只建立"未来某次可用一次"的资产，不在本月消费它。

**阶段 gate**
```bash
# G-G1：split manifest 冻结且有 SHA
sha256sum <final_split_manifest>; grep -n "seed\|revision" <manifest 或其 meta>
# G-G2：默认拒绝访问
<guarded runner> --manifest <final_split> -- echo should_not_run   # 期望非零退出
# G-G3：契约层登记禁令仍在
grep -n "final_test_selection" /home/hyan/AST/docs/status/next_execution_plan.md
```
**资源预算**：8–12 h；GPU 少量（仅 manifest 构建与校验）。
**风险**：⚠️ [推断 0.8] **最大风险是"建好就想用"**。
[建议] gate 由人工签署；本月**不**在 final split 上产出任何数字。

---

### 主题 H｜纯声学路线：能否不用 PESTO（P1）

**目标**：回答一个有真正科学新意的问题。
[事实] 依据：`fv2_acoustic` 已是 Eventizer 最优（**54.82/40.23**，比 baseline +1.85，
`RUN1_RESULTS.md:33-38`）；`fv2_acoustic_only` 的 selection.json 已于 **08-15 00:00** 落盘；
待办为"60 epoch 完成后读 selection、用 `EVED_HEAD_KEEP=0` 重跑 eval45、
回答能否不用 pesto"（`select_twostage.md:196-199`）。

**动作**
1. 读取 `fv2_acoustic_only` selection，确认 60 epoch 已完成。
2. 用 `EVED_HEAD_KEEP=0` 重跑 eval45，得到纯声学路线指标。
3. 顺带处理 latent/all 的负结果复验：当前被降级为"未标准化 PCA32 + 短训练"，
   **train-only scaling + PCA32/64 复验未执行**（`RUN1_RESULTS.md:61`）。
4. 结论必须避免 P1 §3.3-AR5 的三代混比陷阱：
   old fv2_h4 60.98/41.95、prefix-safe E3 59.50/43.42、causal baseline 53.18/38.38
   **是不同模型**，差异主因是训练时长 5 vs 160 epoch，"严格流式回落"是错误表述（`HANDOFF_20260814.md:68`）。

**阶段 gate**
```bash
RUN=/home/hyan/Data/ast_runs_formal/pesto_causal_12h_run1_20260806
# G-H1：纯声学 selection 已就绪
python3 -c "import json;d=json.load(open('$RUN/eventizer/fv2_acoustic_only/selection.json'));print(d['status'], d.get('best_epoch'), d.get('selected_decoder'))"
# G-H2：eval45 重跑产出且与 pesto 版同口径可比（同 split、同 identity）
# G-H3：报告显式标注三代模型不可混比
grep -c "训练时长\|epoch 5 vs 160\|不可混比" <报告>   # 期望 >= 1
```
**资源预算**：10–14 h；GPU 中等（eval45 重跑 + 可能的 PCA 复验重训）。
**风险**：[推断 0.6] 若纯声学接近或超过含 PESTO 版本，会**动摇整条 PESTO 前端叙事** →
这是好结果但需要更强的证据门槛（同 split/identity、可复现），
不可用单次结果下结论（`AGENTS.md:220`"比较同标准"）。

---

### 主题 I｜外部模型对比收口（P2）

**目标**：把"3×2 矩阵"落成一份口径清晰的报告，且**不夸大**。

**[事实] 已完成**：ROSVOT 官方 ckpt 重跑（最优 `thr0995_on075_off000`，与 round3 的 61.50 吻合）、
VOCANO 45 首重跑、Basic Pitch `eval_unified/`；根因 = thr(0.8→0.995)+shift(75ms) 而非代码错误；
匹配算法差异（round3 Hungarian 最大权 vs 20260801 统一管线最大基数）（`HANDOFF_20260814.md:60-63`）。
**[事实] 未完成**：FCPE 未复现（用户指示跳过；论文模型 DDSP-200K ≠ 仓库 `fcpe_c_v001`）；
VOCANO 未复现论文口径（官方指标为音符级编辑距离，范式不同，CMedia/ISMIR2014 demo 数据缺失）。

**动作**
1. **先与 owner 确认"2"的定义**：`grep` 证实 "3×2 矩阵"一词仅见于
   `HANDOFF_20260814.md:9` 与 `:59`，在 `reports/research/20260806_external_model_reproduction.md`
   中 **NOT FOUND** → 我按数字反推为"两档容差口径（100ms/50c 与 150ms/100c）"，置信 0.9，需确认。
2. 报告核心结论如实写为：**"四个模型的论文数字与本仓库数字全部不可直接对比；
   且 ROSVOT 官方代码与论文自身不一致（代码更宽）"**
   （`20260806_external_model_implementation_compare.md:4`）。
3. 把 FCPE/VOCANO 的未复现如实标为 `abandoned-with-reason` / `bounded-insufficient`。

**阶段 gate**
```bash
# G-I1：每个数字标注(模型, 容差口径, 匹配算法, 数据) 四元组，缺一不可
# G-I2：未复现项有显式状态
grep -cE "abandoned-with-reason|bounded-insufficient|未复现" <报告>   # 期望 >= 2
```
**资源预算**：8–12 h；0 GPU（复用已有 `external_repro_20260806/` 产物）。
**风险**：[推断 0.75] 对外易被误读为"我们实现有问题" → 摘要第一句必须先说明
差异根因已定位（thr+shift+匹配算法），再给数字。

---

### 主题 J｜主线合回 main + Windows GUI（P2）

**目标**：① 消除"主线不在 main 上"的结构性风险；② 评估 GUI 是否复活。

**[事实] J-1 分支**：当前分支 `codex/merge-stage1overnight-fast-validation-20260721`
相对 `main` **ahead 60**、behind 0；`main` 停在 `f4dec07`；
`AGENTS.md:73` 约定"工作分支通常为 `codex/<topic-date>`，最终合回 `main`"。
**[事实] J-2 GUI**：源码与文档齐全（`src/apps/feat6_gui/*`、`packaging/pyinstaller/feat6_gui.spec`、
`docs/manual/PESTO_FEAT6_WINDOWS_GUI.md` 204 行、`docs/manual/demo/windows_portable_release.md` 109 行），
但三个 `.bat` 与 `requirements_windows_gui.txt` mtime 均为 **2026-07-14 06:46**，
且 AGENTS.md/AI_SESSION_ENTRY/status 三处均未提 GUI → 已脱离主线。

**动作**
1. J-1：在主题 A 完成提交后，将 60 个 commit 合回 `main`（`AGENTS.md:52` 约定
   "Codex：真实 Git 语义合并、测试、commit/push"）。
2. J-2：**先做可行性判定**（1 h）：是否有 Windows 机器？若无 → 本月不做，仅在
   `docs/owner/demo_future_roadmap.md`（已 6 周未更新）登记；
   若有 → 按 `windows_portable_release.md` 走 5 项前置（`runtime_env\.venv`、
   `checkpoints\feat6\best.pt`、`models\pesto_upstream`、麦克风、`verify_checkpoints.py` 通过）。

**阶段 gate**
```bash
# G-J1：main 已包含主线
cd /home/hyan/AST && git rev-list --count main..HEAD    # 期望 0
conda run -n pesto python -m pytest -q 2>&1 | tail -3   # 合并后回归仍通过
# G-J2：GUI 判定成文（无论做或不做）
grep -n "windows\|GUI" /home/hyan/AST/docs/owner/demo_future_roadmap.md | head
```
**资源预算**：J-1 6–8 h；J-2 判定 1 h（若执行 +12 h）；0 GPU。
**风险**：合并 60 commit 可能有冲突 → 先 `git bundle` 冷备份（P4 §3.0），**禁用 `--force`**。

---

## 4. 四周日程与裁剪方案

**[事实] 容量约束**：主题合计 116–174 h，剩余 3 周按 25–30 h/周 = 75–90 h → **必须裁剪**。

### 建议方案（保 P0 + 高性价比 P1，推迟 P2）

| 周 | 主题 | 工时 | 交付物 |
|---|---|---:|---|
| **W1** | P2 的一周 demo 计划（含主题 A 的第一步） | 24–33 h | LA 可视化 demo + AST provisional 报告 + 两仓已提交 |
| **W2** | **A**（剩余契约治理）+ **F**（run1 定稿）+ **G**（新冻结 split） | 26–34 h | 契约层自洽；AST run1 可定稿；final split 冻结未消费 |
| **W3** | **B**（split 冻结 + sealed 通路） + **E**（负结果归档） | 24–34 h | LA evaluation-v1 冻结 + sealed 报告；realign 负结果报告 + 3M 证据包 |
| **W4** | **C**（overlap 修复）+ 缓冲 + 月度收尾 | 20–28 h | raw decoder 可用化（或如实记为 bounded-insufficient） |
| **推迟** | **D**（多语言）、**H**（纯声学）、**I**（外部模型）、**J**（合并+GUI） | — | 入下月 backlog；其中 **J-1 合回 main 若 W2 有余量应插入** |

### 裁剪理由
- [推断 0.9] 保 **A/F/G/B**：这四个是 P0，且都属"消除已知缺陷"，风险最低、收益确定。
- [推断 0.85] 保 **E**：8–12 h、0 GPU、纯写作，把一条已死的线转成可引用资产，性价比最高。
- [推断 0.8] 保 **C**：它是 LA 唯一"能让产品指标真变好"的主题（+1.79pp 已实测）。
- [推断 0.75] 推迟 **D/H/I**：都需要新的 GPU 运行或新数据/授权确认，
  在契约与评测底座未稳前投入容易返工。
- **J-2（GUI）本月只做 1 h 判定**：无 Windows 机器则零成本关闭。

### 若只有一半容量（约 40 h）的极简方案
只做 **A + F + E**（30–42 h）：两仓可复现 + AST 可定稿 + LA 负结果成文。
[推断 0.85] 这是"最小可辩护月度成果"——三项都不依赖新实验，且都消除现存风险。

---

## 5. 跨主题风险与月度红线

| # | 风险 | 影响主题 | 红线/缓解 |
|---|---|---|---|
| **X1** | 在 sealed / final split 上过早出数字 | B、G | **红线**：sealed 与 final split 各只允许消费 1 次，且需人工签署 gate；本月 G 不产出任何数字 |
| **X2** | 数字手抄导致报告与 JSON 不一致 | 全部 | **红线**：`AGENTS.md:220`"报告数字由结构化数据生成，绝不手抄"→ 每个 gate 都要求脚本复算 |
| **X3** | 跨口径/跨分母混比（100/50 vs 150/100；15 区域 vs 884 区域；三代 Eventizer） | C、E、F、H、I | **红线**：任何表格必须标注(口径, 分母, 数据, 匹配算法)；P1 §3.3-AR5 与 §2.1-C 是两个已发生的实例 |
| **X4** | 大资产入 git | 全部 | `AGENTS.md:152-153`、`:158`；提交前用 `git status --porcelain \| grep -Ei '\.(mp4\|wav\|pdf\|zip\|pt)$'` 拦截 |
| **X5** | 授权风险外溢到对外交付 | B、D | GTSinger 仅内部；iKala 不出现；对外优先 PJS(CC BY-SA 4.0)；Jamendo 逐首核 6 种许可 |
| **X6** | 又一次"成果不在文档里" | 全部 | 每周最后 1 h 强制回写 `docs/status/*` 的 `as_of` + `SESSION_INDEX`；这正是两仓本次的共性失效（P1 §4） |
| **X7** | 开启 `actual_writeback` | C | **红线**：`AGENTS.md:157` 硬约束 + 科学证据不足（884 区域 recovered 0%）→ 本月不解禁 |
| **X8** | 误跑 AST 续训脚本 | F、H | **红线**：不整跑 `launch_causal_convergence_continuation.sh`（`selection_status.md:84`） |

---

## 6. 月末验收（一句话标准）

> **两个仓库的每一条"当前事实"都能由一条命令从已提交的 commit + 结构化 JSON 复算出来，
> 且 `docs/status/*` 的 `as_of` 不早于月末前 3 天。**

对应可执行检查：
```bash
for R in /home/hyan/LyricAlignment /home/hyan/AST; do
  cd $R
  test $(git status --porcelain | wc -l) -eq 0 || echo "$R: 工作树不干净"
  test $(git rev-list --count @{u}..HEAD) -eq 0 || echo "$R: 未推送"
done
grep -n "Snapshot date\|as_of" /home/hyan/LyricAlignment/docs/status/project_current.md
grep -n "as_of" /home/hyan/AST/docs/status/project_current.md
# 两仓反引号引用失效率应低于 P0 基线（LA 11.4% / AST 13.8%）
```
