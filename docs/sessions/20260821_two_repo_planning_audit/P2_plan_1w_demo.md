# P2 — 一周 demo 计划（plan_1w_demo）

---

## 0. 默认选择与理由（文首声明，依任务书"demo 定义不明时按候选清单顺序取第一个"）

任务书给了**两仓各 3 个** demo 候选，但未指定选哪个、也未说明一周是给一个仓库还是两个。
按默认裁决规则：

> **默认选择**
> - **LA 主 demo = 候选①「Side-by-Side 可视化渲染视频」**
> - **AST 副 demo = 候选①「RUN1 结果解读 + 汇报报告」**

**理由（不只是"排第一"）**：
1. [事实] LA① 的产物**已经存在**：`/home/hyan/Data/lyricalign/runs/` 下 686 个 mp4，
   其中 **314 个为 3840×1080**，正好符合 `docs/sessions/20260814_.../03_VISUALIZATION_DESIGN_AND_ACCEPTANCE.md:142`
   的 `3840 × 1080` 规格；6 个交付目录已成型（`20260815_slot_vs_b4_DELIVER` 等）。
   → 一周内的工作是**审计、选片、补渲染、包装**，而非从零开发。风险最低。
2. [事实] AST① 的素材也已存在：`RUN1_RESULTS.md`、`RUN1_REVIEW.md`、`EXPERIMENT_REPORT.md`
   三份加起来已近成稿，且**两步式 select 的新结果（triangle ep30 / 68.26 @150ms-100cent）
   还没有进入任何报告**（`HANDOFF_20260814_select_twostage.md:59-64`）→ 增量价值明确。
3. [推断 0.9] 两者都**不依赖任何未决的科学结论**。这点关键：LA 的 realign-recovery 主线
   已被自身数据否定（884 区域 recovered 0%，P1 §2.1-C），任何以"恢复效果"为卖点的 demo
   都会在提问下崩塌；而"对齐质量的可视化对比"和"筛查性结果汇报"都是**诚实且站得住**的。
4. [事实] 两者的算力需求都极低（LA 可 cache-only 重渲染，禁止重复 Qwen 前向：`03:246`；
   AST 报告纯 CPU），与 P1 §1.3 的结论（GPU 不是瓶颈）一致。

**若用户本意只要一个仓库**：按 workspace 名 `LAassist` 推断 LA 为主 →
只执行 LA 轨（Day2–Day4、Day6–Day7），AST 轨（Day5）可整段删除，日程不受影响。

---

## 1. 候选评估（6 个，逐个给可行性与依赖）

### LA 候选①：Side-by-Side 可视化渲染视频 ← **默认选中**

**定义澄清 [事实]**：这里有两种可能读法，且**两者都指向已有产物**：
- 读法 A = 「B4-vs-Current 双轨并排对比视频」，即 `03:11-26` 的 V1 交付物。
- 读法 B = 「歌曲《Side by Side》的渲染视频」——`Side_by_Side.wav` 是**中文歌名**，
  被 `03:285` 与 `06_PLANNED_RUNS.yaml:25` 指定为 smoke 媒体。
本计划按**读法 A**执行（对比视频），并把《Side by Side》作为 smoke 曲目，一举覆盖两种读法。

| 项 | 内容 |
|---|---|
| **可行性** | **高**。314 个 3840×1080 视频已存在；`.identity.json` 已含每轨 `content_sha256` + label（实测样本：`"B4 · pre-slot"` / `"Slot · full-slot"` / `"Slot · textmode3"`，`layout:"three"`, `profile:"final"`, `font:"Noto Sans CJK SC"`） |
| **依赖** | ① 渲染脚本（**已存在且齐全**）：`scripts/realign_recovery/visualization/` 下 45 个文件，含 `render_b4_vs_current.py`、`render_slot_vs_b4.py`、`render_current_4way.py`、`render_rerender_only.py`、`run_slot_vs_b4_batch.py`、`visualization_controller.py`；② `ffmpeg`/`ffprobe`（实测 `/usr/bin/ffprobe` 可用）；③ 字体 `Noto Sans CJK SC` + font preflight（`03:214`）；④ conda env `lyricalign-qwen`（`AGENTS.md:11-13`）——**仅在需要补渲染时**；⑤ 验收清单 10 项（`03:297-306`） |
| **风险** | 20 个可视化脚本处于**未提交**状态（`git status` `??`）→ 演示前必须先提交，否则不可复现（见 Day1） |
| **卖点诚实性** | ✅ 高。展示"对齐质量随窗口/装配策略变化"是事实，且有 identity 溯源 |

### LA 候选②：新歌端到端 karaoke 视频

| 项 | 内容 |
|---|---|
| **可行性** | **中高**。`AGENTS.md:33-34` 提供通用入口 `bash scripts/demo/run_qwen_fa_batch.sh /path/to/media_or_folder`（同名媒体 + 同名 TXT）；`scripts/demo/render_qwen_fa_karaoke.py` 存在 |
| **依赖** | ① **一首新歌的音频 + 准确歌词 TXT**（版权可用！）；② GPU（真实 Qwen 前向，非 cache-only）；③ conda env + R2 checkpoint（`scripts/demo/inline_realign_env.sh`，`AGENTS.md:169-170`，默认 `MODEL_REVISION=c07281df...` + `step-000750`）；④ 需先跑 `verify_inline_realign_v4.sh` 校验（`AGENTS.md:39`） |
| **风险** | ⚠️ **版权**：P1 §2.3-R5 —— GTSinger 附加条款未澄清、AMLL 第三方权未决、iKala 未授权。对外 demo 用新歌须确认授权；PJS 是 CC BY-SA 4.0（可用但是日语语音库，不像"歌"） |
| **相对①的劣势** | 需要 GPU 真实前向 + 新素材授权，且产出的说服力与①重叠 |

### LA 候选③：产品化 gate 演示

| 项 | 内容 |
|---|---|
| **可行性** | **中**。基础设施已有：`scripts/evaluation/` 30 个脚本（含 `check_alignment_quality_gate.py`、`guarded_run.py`、`run_quality_checks.sh`），runbook 命令齐备（`04_PRODUCTIZATION_RUNBOOK.md:6-111`） |
| **依赖** | ① 已有真实 GT 指标（**已有**：R2 90.1/95.5/98.1%）；② 质量门阈值（**已实测但结论为负**） |
| **阻断性问题 [事实]** | **混合门无效**：增益全部落在 raw 门失败子集（39 项，official 82.52% vs raw 86.44%），门通过子集两者同为 92.72%（`20260816_productization_validation_report.md:203-205`）。严格门在 75 段上 33 通过/42 失败（`:192-193`）。`:206` 已把"需要另找选择信号"列为**开放设计问题** |
| **判定** | [推断 0.85] **一周内不宜作为主 demo**：演示一个"通过率 44%、且选择逻辑被自身数据否决"的 gate，会把开放问题暴露成产品缺陷。**建议降级为 Day6 的一页附录**（诚实呈现为"门控研究中"） |

### AST 候选①：RUN1 结果解读 + 汇报报告 ← **默认选中（副）**

| 项 | 内容 |
|---|---|
| **可行性** | **高**。素材近成稿：`RUN1_RESULTS.md`(7556 B)、`RUN1_REVIEW.md`(9572 B)、`EXPERIMENT_REPORT.md`(10816 B) |
| **增量价值 [事实]** | 两步式 select 的新结论**尚未进入任何报告**：direct ep25/63.99、pyramid ep30/66.63、oaf ep17/64.01、**triangle ep30/68.26**、coarse ep8/59.37（COnOffP@150ms/100cent），阈值统一 onset0.5/offset0.65/active0.55/release2（`HANDOFF_20260814_select_twostage.md:59-64`） |
| **依赖** | ① 磁盘 selection.json ×5（**已验证存在**，含 `selected_epoch`/`selected_thresholds`/`selection_primary`/`eval45_policy` 键）；② `pesto` env（仅跑测试用）；③ **无需 GPU、无需重训** |
| **必须写明的边界 [事实]** | `RUN1_REVIEW.md:9-14`"不宜定稿为正式架构比较或正式 winner"；`EXPERIMENT_REPORT.md:3` 状态 `provisional_internal_screening`；selection.json 内建 `"eval45_policy": "internal repeatedly visited evaluation; not untouched final test"` → 报告标题必须含"内部筛查（provisional）"字样 |
| **风险** | 汇报口径双轨（100ms/50c 选参 vs 150ms/100c 汇报，`select_twostage.md:68`）→ 同一张表混两种口径会产生假比较，必须分栏标注 |

### AST 候选②：Windows GUI demo

| 项 | 内容 |
|---|---|
| **可行性** | **低（本周内）**。代码与文档齐全：`src/apps/feat6_gui/{app,audio_worker,backend_interface,model_worker}.py`、`packaging/pyinstaller/feat6_gui.spec`、`docs/manual/PESTO_FEAT6_WINDOWS_GUI.md`(204 行)、`docs/manual/demo/windows_portable_release.md`(109 行) |
| **阻断依赖 [事实]** | ① **需要 Windows 机器**——当前环境是 Linux 服务器，`.bat` 无法直接运行；② `runtime_env\.venv`（`Start_AST_Demo.bat:5`）；③ 冻结 feat6 checkpoint 放 `checkpoints\feat6\best.pt`（`:12-13,19`）；④ PESTO 上游权重放 `models\pesto_upstream`（`:9`）；⑤ 麦克风；⑥ `verify_checkpoints.py` 失败即拒启动 |
| **判定** | [推断 0.8] 本周排除。三个根文件 mtime 均为 **2026-07-14 06:46**（一个多月未动），且 AGENTS.md / AI_SESSION_ENTRY / status 三处均未提 GUI → 已脱离主线。**列入 P3 一月路线**（需先确认是否有 Windows 机器） |

### AST 候选③：外部模型 3×2 矩阵报告

| 项 | 内容 |
|---|---|
| **可行性** | **中**。"3" = ROSVOT / VOCANO / Basic Pitch；"2" = 两档容差口径（100ms/50c 与 150ms/100c）（`HANDOFF_20260814.md:59-62`） |
| **已完成部分 [事实]** | ROSVOT 官方 ckpt 重跑（最优 `thr0995_on075_off000`，与 round3 的 61.50 吻合）、VOCANO 45 首重跑、BP `eval_unified/`；根因结论 = 差距源于 thr(0.8→0.995)+shift(75ms) 而非代码错误；round3 用 Hungarian 最大权匹配 vs 20260801 统一管线用最大基数匹配（`:60-63`） |
| **未完成部分 [事实]** | FCPE **未复现**（用户指示跳过；论文模型 DDSP-200K ≠ 仓库 `fcpe_c_v001`）；VOCANO **未复现论文口径**（官方指标是音符级编辑距离，范式不同，且 CMedia/ISMIR2014 demo 数据缺失） |
| **术语警告 [事实]** | "3×2 矩阵"一词只出现在 `HANDOFF_20260814.md:9` 与 `:59`，在 `reports/research/20260806_external_model_reproduction.md` 中 **NOT FOUND** → "2"的轴由数字反推（置信 0.9）。写报告前须与 owner 确认第二个轴的定义 |
| **判定** | [推断 0.75] 可行但**不如候选①**：核心结论是"四个模型的论文数字与本仓库数字全部不可直接对比"（`20260806_external_model_implementation_compare.md:4`），是一个**否定性方法论结论**，作为对外 demo 说服力弱、且易被误读为"我们的实现有问题" |

---

## 2. 按天拆解（7 天）

**通用前置（每天开工前）**
```bash
# LA
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen   # AGENTS.md:25-26
cd /home/hyan/LyricAlignment && export PYTHONPATH=src
# AST
PY=/root/autodl-tmp/AST_storage/conda/envs/pesto/bin/python                        # AGENTS.md:33-38
RUN=/home/hyan/Data/ast_runs_formal/pesto_causal_12h_run1_20260806
```

---

### Day 1｜保命日：提交 + 契约回写（**两仓共用，不可跳过**）

**目标**：消除 P1 §2.3-R1 / §3.3-AR2 两个 P0 风险。当前 demo 素材全部躺在未提交的工作树里，
任何演示都不可复现。

**动作**
1. LA 分 3 批 commit（**不混批**，便于回滚）：
   - 批 A：`scripts/evaluation/`(30) + `tests/evaluation/`(1)
   - 批 B：`scripts/realign_recovery/visualization/`(20 新 + 4 改) + `src/lyricalign/demo/`(4 改)
   - 批 C：`docs/sessions/20260816_*/`(8) + `reports/progress/20260816_*`(7) + `results/comparisons/`(12) + `AGENTS.md` + `SESSION_INDEX.md`
2. LA 推送 124 + 新提交（`git push origin main`）。
3. AST 提交 27 项（两步式 select 改造 + 交接文档），并**决定**是否合回 `main`
   （当前分支相对 main ahead 60，`AGENTS.md:73` 约定最终合回 main）。
4. 契约回写（3 个最小编辑）：
   - `AI_SESSION_ENTRY.md` 顶部补 **2026-08-16 active override** 条目
   - `AGENTS.md:15-16` 与 `:82-89` 主线指针同步到 0816
   - AST `HANDOFF_20260814_selection_status.md` 加 superseded 头部 → 指向 `select_twostage.md`
5. **重做 baseline identity freeze**（在 clean tree 上），解决 `.dsh/review5:38`。

**依赖**：git 写权限、远端可达。**无 GPU 需求。**

**验收命令**
```bash
cd /home/hyan/LyricAlignment
git status --porcelain | wc -l                    # 期望 0
git rev-list --count @{u}..HEAD                   # 期望 0（已推送）
git diff --check                                  # 期望无输出
PYTHONPATH=src python -m compileall -q src scripts # 期望无错误
cd /home/hyan/AST && git status --porcelain | wc -l  # 期望 0
grep -n "2026-08-16" /home/hyan/LyricAlignment/AI_SESSION_ENTRY.md | head -3  # 期望命中 override 条目
grep -ni "superseded" /home/hyan/AST/docs/sessions/explore/20260806_pesto_causal_12h_program/HANDOFF_20260814_selection_status.md | head -2
```
**时长估计**：4–6 h（其中 commit 分批 2h、契约回写 1h、identity freeze 重做 1–2h、缓冲 1h）。

---

### Day 2｜LA demo：素材审计与选片（**不渲染**）

**目标**：从 686 个 mp4 中确定最终 demo 片单，并逐项过 `03:297-306` 的 10 项验收。

**动作**
1. 建立全量清单（分辨率/时长/identity 完整性三维）。
2. 按"能讲清一个故事"选 **4–6 首**：建议覆盖中文 / 粤语 / 日语 / 英文各 1
   （`RUN_STATE.md:36-82` 的 5 首实验曲目：乙女解剖/浮夸/PastLives/此处通往天空/人造卫星 可作候选池）。
3. 对选中片子逐项核对 10 项验收清单（`03:297-306`）：3840×1080、字体、共享时标、
   窗口计划不交叉、零时长聚合、两行 KTV、播放头同步、overlay 不压字、翻页不截断、
   **重渲染不增加 Qwen 前向数**。
4. 记录哪些需要补渲染（Day3 输入）。

**依赖**：`ffprobe`（已验证可用）、Day1 的提交（保证脚本版本可追溯）。**无 GPU。**

**验收命令**
```bash
D=/home/hyan/Data/lyricalign/runs
# ① 全量分辨率直方图（期望大量 3840x1080）
find $D/2026081*_*DELIVER* -name '*.mp4' | while read f; do
  ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$f"; done \
  | sort | uniq -c | sort -rn
# ② 选中片单必须每个都有 identity 且 sha 齐全
for f in <选中的 mp4 列表>; do
  test -f "$f.identity.json" || echo "MISSING identity: $f"
  python3 -c "import json,sys;d=json.load(open('$f.identity.json'));
assert d['alignments'] and all(a.get('content_sha256') for a in d['alignments']), 'sha missing'
print('OK', d['layout'], d['profile'], d['font'], len(d['alignments']),'lanes')"
done
# ③ 产出审计表（可观察产物）
ls -la <你的审计表输出路径>/demo_shortlist.md
```
**产物**：片单表（含每片分辨率/时长/轨数/sha 校验结果/10 项验收逐项勾选）。
**时长估计**：3–4 h。

---

### Day 3｜LA demo：补渲染缺口（cache-only 优先）

**目标**：补齐 Day2 标记的缺口，**不重复 Qwen 前向**。

**动作**
1. 优先用 cache-only 重渲染：`render_rerender_only.py`（`03:246` 要求 cache-only，
   `03:297-306` 第 10 项要求"重渲染不增加前向数"）。
2. 仅当确实缺对齐产物时，才跑真实前向；此时先 `verify_inline_realign_v4.sh`（`AGENTS.md:39`）。
3. 若要 B4-vs-Current 双轨：`render_b4_vs_current.py`；四路：`render_current_4way.py --fourth-family R-CF`
   （`03:114-125` 禁止用 R-A/R-B 或重复 R-U 充第 4 轨）。
4. 批量：`run_slot_vs_b4_batch.py` / `render_comparison_batch.py`。

**依赖**：字体 preflight、`ffmpeg`；**仅在必要时**才需 GPU + R2 checkpoint。

**验收命令**
```bash
cd /home/hyan/LyricAlignment && export PYTHONPATH=src
# ① 干跑清单（先不渲染）
python scripts/realign_recovery/visualization/run_test_demo_viz.py --help | head -20
# ② 前向数不增：渲染前后比对 scientific hash（03:246、03:325-342 的产物布局）
ls <run>/scientific_hash_before.json <run>/scientific_hash_after.json
python3 -c "import json;a=json.load(open('<run>/scientific_hash_before.json'));b=json.load(open('<run>/scientific_hash_after.json'));print('IDENTICAL' if a==b else 'CHANGED -> 违反 03:246');assert a==b"
# ③ 新产物规格
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 <新mp4>  # 期望 3840,1080
```
**时长估计**：4–6 h（cache-only 路径约 1–2 h；若需真实前向 +2–3 h）。
**回退**：若渲染环境损坏 → 直接用 Day2 已通过验收的既有 mp4（**回退方案 A**，见 §3）。

---

### Day 4｜LA demo：叙事层（一页纸结论 + 边界声明）

**目标**：视频之外，给出**诚实**的一页结论。这是本 demo 与"过度承诺"的分界线。

**动作**
1. 一页纸包含三块：
   - **能力**：GTSinger 75 段/1226 字符真实 GT，R2 = **90.1 / 95.5 / 98.1%**（both_100/200/500ms）
     （`20260816_gtsinger_first_metrics.md:61-63`）
   - **改进**：raw decoder +1.79pp（90.05→91.84，20 改善/2 回退/53 不变）（`..._validation_report.md:134,137`）
   - **边界**：① 仅中文 GTSinger 有定量 GT；日语（PJS）无音素级 GT、粤语 n=3 → 结论仅结构性
     （`review8:19`；`00:156`）；② split 未冻结（draft SHA `f04e0b9b...`）；③ sealed 从未运行
2. **明确不讲**：realign-recovery 的"恢复"叙事（884 区域 recovered 0%，
   `00_SESSION_DISCUSSION_RECORD.md:1294-1300`）。若被问到，用"已充分探索、结论为负、
   已转向评测底座"回答——这是加分项而非减分项。
3. 数字**全部脚本生成**，不手抄（纪律：`AGENTS.md:220`"报告数字由结构化数据生成，绝不手抄"）。

**依赖**：`results/comparisons/*.json`(12 份)、`reports/progress/20260816_*`(7 份)。**无 GPU。**

**验收命令**
```bash
cd /home/hyan/LyricAlignment
# 数字可从 JSON 复算（举例：门控与回归汇总）
ls results/comparisons/20260816_gtsinger_regression_official_vs_rawdec.json \
   results/comparisons/20260816_gtsinger_hybrid_gate_analysis.json
python3 -c "import json;d=json.load(open('results/comparisons/20260816_gtsinger_regression_official_vs_rawdec.json'));print(json.dumps(d,ensure_ascii=False)[:600])"
# 一页纸产物存在且每个数字有来源标注
test -f <一页纸路径> && grep -c "results/comparisons\|reports/progress" <一页纸路径>   # 期望 >= 数字个数
```
**时长估计**：3–4 h。

---

### Day 5｜AST demo：RUN1 汇报报告

**目标**：产出一份**标注 provisional** 的内部筛查报告，并首次纳入两步式 select 结果。

**动作**
1. 从 selection.json **脚本化**抽取选参结论（禁止手抄）。
2. 报告结构：实验设计 → 数据与口径 → 5 个 joint head 结果 → 6 个 Eventizer 结果 →
   两步式 select 修复（含 OOM 根因）→ **未闭合项与边界**。
3. 双口径分栏：100ms/50cent（选参口径，`AGENTS.md` 冻结契约）与 150ms/100cent（汇报口径，
   `select_twostage.md:68`），**严禁同栏混排**。
4. 标题与摘要必须含 provisional / 内部筛查字样（依据 `EXPERIMENT_REPORT.md:3`、
   `RUN1_REVIEW.md:9-14`、selection.json 的 `eval45_policy`）。

**依赖**：磁盘 selection.json ×5（已验证）、`pesto` env（仅测试）。**无 GPU、无重训。**

**验收命令**
```bash
RUN=/home/hyan/Data/ast_runs_formal/pesto_causal_12h_run1_20260806
# ① 选参结论自动抽取（键已实测存在）
python3 - <<'EOF'
import json,glob,os
for p in sorted(glob.glob(f"{os.environ.get('RUN','')}/joint_eval/*/selection.json")):
    d=json.load(open(p))
    print(f"{d['head']:16s} epoch={d['selected_epoch']:<4} status={d['status']:9s} "
          f"proc={'two-stage' if 'two-stage' in d.get('selection_procedure','') else 'LEGACY'} "
          f"thr={d['selected_thresholds']}")
    assert 'two-stage' in d.get('selection_procedure',''), f"{p} 仍是旧口径！"
    assert d['status']=='complete'
print("ALL 5 HEADS: two-stage complete")
EOF
# ② 口径护栏：报告中 150/100 与 100/50 必须成对出现且标注
grep -c "150ms/100cent\|150/100" <报告路径>
grep -c "100ms/50cent\|100/50"   <报告路径>
grep -ci "provisional\|内部筛查"  <报告路径>     # 期望 >= 1
# ③ 回归测试（AGENTS.md:15）
conda run -n pesto python -m pytest -q 2>&1 | tail -5
```
**时长估计**：4–5 h。
**回退**：若 runtime/latency 证据补不齐（P1 §3.2 阻塞 1），**不阻塞报告**——
按 `RUN1_REVIEW.md:13` 原文把它列为"missing evidence"并交付 provisional 版本。

---

### Day 6｜联合验收 + 附录

**目标**：两个 demo 一起过验收清单；把 LA 候选③降级为诚实附录。

**动作**
1. LA：完整走 `03:297-306` 十项，逐项留证据（截图/ffprobe 输出/hash 对比）。
2. AST：核对报告每个数字都能由脚本从 JSON 复算。
3. 追加一页"产品化门控研究中"附录：严格门 33/75 通过、混合门无增益
   （`..._validation_report.md:192-193, 203-205`），并写明 `:206` 的开放问题。
4. **反向检查**：请一个独立 review 视角找"最容易被问倒的三个问题"并准备答案
   （建议问题：① 你们的 realign 到底有用吗？② 90.1% 是在多少数据上？③ 日语结论可信吗？）。

**验收命令**
```bash
# LA 十项逐项留痕（示例：第 1、10 项）
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 <final.mp4>  # 3840,1080
python3 -c "import json;a=json.load(open('<run>/scientific_hash_before.json'));b=json.load(open('<run>/scientific_hash_after.json'));assert a==b;print('第10项 PASS: rerender 未增前向')"
# 验收记录产物
test -f <验收记录路径> && grep -c "PASS\|FAIL" <验收记录路径>   # 期望 >= 10
```
**时长估计**：3–4 h。

---

### Day 7｜打包交付 + 文档回写

**目标**：产出可交付包，并把本周结论写回仓库文档（避免又一轮"成果不在文档里"）。

**动作**
1. 打包：视频（选中 4–6 个 mp4 + 对应 identity.json）、一页纸、AST 报告、验收记录。
   **注意** `AGENTS.md:152-153`：生成资产（pdf/pptx/docx）与大型 evidence pack **不进 git**，
   外置到数据目录对应 run 下，`reports/` 只登记路径与索引。
2. 回写：LA `docs/sessions/SESSION_INDEX.md` 与 `reports/README.md` 登记 demo 交付；
   AST `docs/status/project_current.md` + `next_execution_plan.md` 更新 `as_of`
   （这两份是 `selection_status.md:80`、`select_twostage.md:77` 一直未执行的最后待办）。
3. 最终提交 + 推送。

**验收命令**
```bash
# 交付包清单与大小
du -sh <交付目录>; find <交付目录> -type f | wc -l
# 仓库内不得出现大资产
cd /home/hyan/LyricAlignment && git status --porcelain | grep -Ei '\.(mp4|wav|pdf|pptx|docx|zip)$' && echo "违反 AGENTS.md:152-153" || echo "OK: 无大资产入库"
# status 文档已更新
grep -n "as_of" /home/hyan/AST/docs/status/project_current.md | head -2   # 期望不再是 2026-08-06
cd /home/hyan/LyricAlignment && git status --porcelain | wc -l            # 期望 0
```
**时长估计**：3–4 h。

---

### 工时汇总

| Day | 主题 | 估时 |
|---|---|---:|
| 1 | 保命：提交 + 契约回写 | 4–6 h |
| 2 | LA 素材审计选片 | 3–4 h |
| 3 | LA 补渲染 | 4–6 h |
| 4 | LA 叙事层 | 3–4 h |
| 5 | AST 汇报报告 | 4–5 h |
| 6 | 联合验收 + 附录 | 3–4 h |
| 7 | 打包 + 回写 | 3–4 h |
| **合计** | | **24–33 h** |

[推断 0.8] 按每天 5 h 有效工时算，7 天有 35 h 容量 → **留有 2–11 h 缓冲**，
足以吸收一次渲染返工或一次 AST 证据补齐尝试。

---

## 3. 风险与回退方案

| # | 风险 | 触发信号 | 回退方案 |
|---|---|---|---|
| **A** | 渲染环境损坏 / 字体缺失 / GPU 不可用 | Day3 渲染失败或 font preflight 失败 | **直接交付 Day2 已通过验收的既有 mp4**（314 个 3840×1080 已在磁盘）。demo 不依赖新渲染 |
| **B** | Day1 提交冲突 / 推送被拒 | `git push` 失败或 rebase 冲突 | 先 `git bundle` 或本地打 tag 做冷备份，再逐批处理；**绝不用 `--force`**。demo 素材本身在数据目录，不受影响 |
| **C** | AST runtime/latency 证据仍缺 | Day5 找不到 RTF/latency artifact | 按 `RUN1_REVIEW.md:13` 交付 **provisional** 版，显式列 missing evidence（这是文档已授权的状态，非失败） |
| **D** | 被问"realign 有效吗" | 现场提问 | 直接给负结果 + 转向理由：884 区域 recovered 0%（`00:1294-1300`）、0813 有 GT 的 65.4% catastrophic（`00:1167-1176`）→ 因此转向 evaluation-v1 底座。**诚实呈现负结果是加分项** |
| **E** | 版权质疑 | 现场提问数据来源 | 只展示已确认许可的素材；GTSinger 附加条款未澄清 → 仅内部；iKala 未授权 → 不出现；对外优先 PJS(CC BY-SA 4.0) 与自有测试曲目 |
| **F** | 双口径数字被误当同口径比较 | AST 报告审阅意见 | 分栏 + 每张表标注口径；引用 `select_twostage.md:68` 说明汇报/选参口径分离 |
| **G** | LA 候选③ gate 被当成产品承诺 | 附录被误读 | 附录标题写"研究中（open design question）"，直接引用 `:206` |
| **H** | 一周内两轨都想做全 | 进度落后于 Day4 | **砍 AST 轨（Day5）**，保 LA 主 demo 完整；AST 报告顺延到 P3 第一周 |

---

## 4. 明确不做（避免范围蔓延）

- ❌ 不跑新的 realign 大规模实验（P1 已证负结果，投入产出比差）。
- ❌ 不开启 `actual_writeback`（`AGENTS.md:157` 硬约束，且科学证据不足）。
- ❌ 不跑 AST `launch_causal_convergence_continuation.sh`（`selection_status.md:84` 硬禁令，会 resume 重进训练）。
- ❌ 不做 Windows GUI（无 Windows 机器；见候选②判定）→ 移入 P3。
- ❌ 不冻结 split、不跑 sealed（需 review 与策略决定，非一周 demo 范围）。
