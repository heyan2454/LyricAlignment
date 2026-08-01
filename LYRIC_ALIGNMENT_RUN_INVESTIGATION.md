# 最新实验进展调查（临时报告）

> 调查时间：2026-08-01 01:21 CST
> 调查人：Reasonix 会话
> 说明：本文件为临时调查记录，供后续补全至正式文档，可随时删除或归档。

## 一、正在运行的实验

**Alignment Research v6 formal 全量套件** —— E8 continuation + **E9 跨窗 beam realign**
机制的大规模正式运行（含 E5 planner 修复、E4 96-unit 口径、降级冻结等配套修复）。

- 输出 root：
  `/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal_20260731_e9_lazy_compact_v8_inputcache_e9scope_aggregatefix`
- 名称关键修饰：`e9_lazy_compact_v8_inputcache_e9scope_aggregatefix`
- 主跑进程：`run_alignment_research_suite.py`（PID 545640）
  - 启动：2026-07-31 14:21:31，已运行约 11 小时
  - 状态：`Rl`，CPU ~345%，GPU(cuda) 活跃（99W，占用 5132MiB）
- 宿主管道进程：`run_research_v6_pipeline.py`（PID 544179，`Ss` 挂起等待阶段）
- 模型：`Qwen3-ForcedAligner-0.6B-hf`（revision `c07281df...`），R2 checkpoint `step-000750`，device cuda
- 复用 baseline：v3 的 `gtintervalfix/baseline`（sha256 校验）
- resume 模式 + `--compact-artifacts`（中间产物随阶段清理）

## 二、进度

| 指标 | 数值 | 说明 |
|---|---|---|
| 进度条 | **21024 / 21562 = 97.4%** | `formal/run_status.jsonl` |
| 当前 item | `m4long_673_玛依拉` | M4Singer 合成超长音频 |
| 待处理 | **538 项** | 全部为 `m4long` |
| 已跑满 E0–E9 | 21017 / 21017（100%） | 每项 `phases` 长度 = 10 |

Manifest 总量构成：`demo` 35、`mir1k` 17、`m4native` 20298、`m4long` 1212。

剩余 538 项分布（按 `duration_bucket`）：
- `target_120s`：155 项
- `target_180s`：383 项（估算值，随时间推进略减）

## 三、质量 / 健康信号

- **0 个 failure / error 项**：`items/` 下无 `.failure.json` / `*error*` / `*failed*`；
  抽样 200 项 `item_summary.json` 的 `phases` 全部完整（10 阶段齐全）。
- **推理缓存命中高**（input-cache 机制有效）：
  - `inference_cache`：hit 578k（60%）/ miss 380k
  - `serial_inference_cache`：hit 102k（78%）/ miss 28k
- 每个已完成 item 生成 E0–E9 全套产物（`E0_decoder_reanalysis` … `E9_beam/rank_01/02`），
  `frozen_decoder` 为 `weighted_isotonic`。
- 日志尾部 window plan 正在用 `E9_actual_cursor_window_text_budget_beam_v1` 推进，
  说明当前长项已进入 E9 beam 推理阶段（最重的部分）。

已完成 m4long 项 wall_sec（单 item 累计计算时间）：
- `target_60s`：median 8.8 s，mean 9.3 s（404 项）
- `target_120s`：median 28.8 s，mean 28.6 s（250 项）
- `target_180s`：**尚无样本完成**（剩余最多、最慢）

## 四、预计完成

- 实测速率（当前 m4long 段）：约 **36 秒/项**（180 秒推进 5 项）。
- 剩余 538 项 ≈ **5.4 ~ 7 小时**（180s 项占比高，偏慢端）。
- 预计大致 **2026-08-01 早上 07:00–08:30 CST** 前后跑完推理阶段。

## 五、后续建议

- 推理全部完成后，还需 `collect_research_evidence.py` / `summarize_research_v6.py`
  出正式证据与汇总报告（当前仅到推理阶段）。
- v7（`..._v7_inputcache_e9scope`）为历史目录，非占用状态；仅 v8 在跑。

## 六、相关文档

- `docs/sessions/20260731_alignment_research_v6_e8_e9_completion.md`
- `docs/sessions/20260731_alignment_research_v6_correctness_completion.md`
- `docs/research_v6/README.md`（阅读顺序 01–07）
- `docs/research_v6/02_COMPLETE_EXPERIMENT_DESIGN.md`（E0–E9 设计）
- `docs/research_v6/06_CORRECTNESS_FIXES_20260731.md`
- `docs/research_v6/08_FORMAL_FROZEN_DECODER_AND_PILOT_LEAKAGE_FIXES_20260731.md`

---

## 七、对照实验设计

> 依据 `docs/research_v6/02_COMPLETE_EXPERIMENT_DESIGN.md`，结合本次已落盘
> per-item summary 的中间信号补全。标注 **“已有中间信号”** 的臂已有数据可支持
> 初步方向；标注 **“待跑/空白”** 的臂当前 formal 无法回答，需要补充对照实验。

### 7.1 策略链纵向对照（E0–E9 各为“臂”）

| 臂 | 对照内容 | 关键指标 | 当前状态 |
|---|---|---|---|
| E0 | baseline decoder 重分析（raw 等 5 候选） | structural、MAE | 数据可用 |
| E1 | Detector 自然错误（logistic/risk threshold） | risk_span、safe_boundary | 数据可用 |
| E2 | 人工腐化（8 类） | corruption 命中 | 数据可用 |
| E3 | Decoder 困难区修复 | span_sources | 数据可用 |
| E4 | 歌词输入量（-50%…+50%；96 vs 3×32） | coverage、seam、调用数 | budget/chunk case 已计，明细被 compact |
| E5 | 安全边界 exact/−2/−4 分窗 | GT cursor distance、MAE | **仅在长/多窗序列适用** |
| E6 | 静音机制（5 种变体） | 静音前后 MAE、恢复 | 数据可用 |
| E7 | 串行累计/级联（cursor/prev/边界扰动 + reset） | 后续窗外 MAE、恢复 | **m4native 空白** |
| E8 | 简化 Realign 局部候选 + continuation | improvement/clean harm/oracle | **已有可辨信号** |
| E9 | 跨窗 beam + 系统级 pilot | delta_MAE/oracle match/fallback | **已有可辨信号** |

### 7.2 已有数据暴露的对照盲区（需补做）

1. **E9 跨窗 beam 在“单窗/短序列”上的适用性对照**
   - 现象：demo（多为 1–3 窗）E9 `applicable` 31/35 项，但平均 `fallback_window_count=2.68`
     （占总窗 3.29 的约 **81%**），即 beam 大量回退到 baseline；且 oracle 无数据（0/0）。
   - 待对照：`beam 开 vs beam 关(baseline)` 在 demo 上逐窗的 MAE/coverage/fallback；
     验证是“beam 不适用短窗”还是“剪枝过早淘汰导致 fallback”。
2. **E8 continuation 在 demo 上的传播失败原因**
   - 现象：demo 上 `candidate_propagation_failure` 远超 case 数、`eligible_for_selection` 全 False、
     `metrics=None`；候选无法写回 committed prefix 重推下游。
   - 待对照：区分“demo 是单窗无下游可推”与“候选结构与 frozen baseline window plan 不兼容”。
3. **E5/E7 在 M4Singer native 上不可用**
   - 现象：m4native（20298 项）E5_app=0、E7_app=0（单窗，无跨窗需求）；demo 才触发这些臂。
   - 待对照：需要**多窗 native 样本**（如更长 M4Singer 原生歌或拼接）才能测 E5/E7 的级联/边界；
     否则长序列策略的真实横断面样本被合成 long 与 demo 垄断。
4. **E4 歌词输入量的 per-case 明细被 --compact-artifacts 清理**
   - 现象：per-item 只剩 `budget_case_count=2`、`chunk_case_count=2`。
   - 待对照：若要报 B/C（96 vs 32、覆盖率/调用数），需在**不 compact** 的 subset run 上补明细，
     或让汇总器从 E4 文件重算（当前文件已被清）。

### 7.3 建议的补做实验批次（设计）

- **C-E9-fallback**：仅 demo 集，`beam_width∈{1,2,3}` × `剪枝强度{默认,放宽} × {beam, baseline}`，
  输出逐窗 selected/fallback 与因果。
- **C-E8-propagation**：仅 demo，重跑候选传播，落盘每个 case 的 `downstream_metrics`
  （当前为 None），报告“无下游”与“不兼容”分流计数。
- **C-E5E7-native-multiwindow**：构造 M4Singer 原生多窗子集（每源 60–120s 非合成），跑 E5/E7，
  报告在 native 上的边界/级联恢复，与合成 long 对照。
- **C-E4-uncompact**：每数据集子样本，不 compact，取 E4-B/C 的 coverage/调用数/RTF 明细。

### 7.4 补做实验的时间估计（新增，2026-08-01）

> 假设：单卡 cuda 串行执行、不与当前 v8 并行；当前 formal 用 `--compact-artifacts`，
> 每 item 结束后 **inference cache 被删除**（`run_alignment_research_suite.py:2356-2363`），
> 因此补做实验**无法复用现行缓存、需从零重建**（cache miss）。
> 基准（已落盘）：demo 全量项 wall≈63–67s（含 E0–E9）；demo 的 E9 适用项 ≈66–73s、
> 平均 3.29 窗；m4long 的 E9 项 ≈30s/项；mir1k E9 项 ≈20s/项。
> 下表为参数化区间，实际以所选样本量与是否并行为准。

| 批次 | 设计规模（示例） | 每项成本因子 | 估算总耗时 |
|---|---|---|---|
| **C-E9-fallback** | 35 demo（或扩至 35 demo + 17 mir1k + ~50 m4long ≈ 100 项） | 每项新增 2–3 个 beam 配置 × 当前 E9 项成本 ~40s | demo 35 项 ≈ **50–90 min**；扩至 100 项 ≈ **2.5–4 h** |
| **C-E8-propagation** | demo 35 项（322 个 E8 case，量小） | 每项 E8 continuation 重推 <30s（case 少、传播快速失败） | ≈ **15–25 min** |
| **C-E5E7-native-multiwindow** | 构造 native 多窗子集；取 50–200 项 | E5(3 变体) + E7(16+ 注入×含 reset) 每项 30–80s（cache miss） | 50 项 ≈ **35–70 min**；200 项 ≈ **2.5–4.5 h** |
| **C-E4-uncompact** | demo 全量 + native/long 每类 ~50 ≈ 200 项 | 只跑 E4-B/C 文本预算推理，无 E5–E9，每项 15–30s | ≈ **1–1.5 h** |

**合计**（四批，示例规模）：
- 最小（demo 只做 C-E9+C-E8，加各 class 小样本）：约 **2–3 小时**。
- 最大（100 项 C-E9 + 200 项 C-E5E7 + 200 项 C-E4）：约 **7–11 小时**。

**结论**：四批补做规模可控（亚天级）。其中
- 最快：C-E8-propagation（demo，~20 分钟）、C-E4-uncompact（~1–1.5 h）。
- 最贵：C-E5E7-native-multiwindow（因 16+ 注入 × reset 的次数多，且 cache 需重建）；
- C-E9-fallback 依样本量从 1–4 小时不等，建议先用 demo 35 项（~1 h）确认是否值得放大。
- 若想省时：让补做 run 复用同一 out-root 的子集、或关闭 compact-清理暂时保留 cache、
  或对 E5E7 用 pilot 级注入采样（当前 pilot 已按 1/3 采样注入），可把最贵批次再降一个量级。

---

## 八、已有数据中间信号（“已能看出什么”，截至 2026-08-01 01:25，未完成、非最终结论）

> 基于已落盘的 21017 个 per-item summary 横断面。formalin 推理未完成，
> 以下为**方向性中间信号**，最终以 `research_summary.json` 为准。

### 8.1 数据覆盖结构
- Manifest 总量：demo 35 / mir1k 17 / m4native 20298 / m4long(合成超长) 1212。
- **E9 applicable 仅 289 项**（demo 31、m4singer_synthetic_long 257、mir1k 5）；
  其余 20738 项 E9 不适用 → E9 只在“多窗/长序列”上有样本，横断面窄。
- **E5 仅 demo+long+mir1k 适用**，m4native 0；**E7 同** → 长序列病只在合成 long/demo 被试到。

### 8.2 E8 简化 Realign（信号明确）
| dataset | E8 applic | cases | selected improvement | clean harm | oracle match |
|---|---|---|---|---:|---:|---:|
| m4singer | 7714 | 9725 | 1116 | **2433** | 5804/9725 (59.7%) |
| m4singer_synthetic_long | 597 | 3811 | 1474 | 1500 | 1973/3811 (51.8%) |
| mir1k | 16 | 91 | 42 | 21 | 72/91 (79.1%) |
| demo | 30 | 322 | 0 | 0 | 0/322（且传播大失败） |

- 中间读法：**m4singer 全量上 clean harm(2433)>improvement(1116)**——E8 局部修正整首
  clean harm 多于改善，oracle 命中不足六成；**mir1k 明显正向**（harm 只有 imp 一半，
  oracle 79%）；**demo 基本失效**（传播全失败）。
- 这提示 E8 detecctor 选择标准在全量/长序上偏激进，而 mirror-1k/mir1k 是更可控的对照域。

### 8.3 E9 跨窗 beam（信号初步）
| dataset | app | beam width | multi-hyp窗均值 | fallback窗均值 | oracle match | delta_MAE mean | line boundary MAE |
|---|---|---|---:|---:|---:|---|---:|---:|
| demo | 31 | 3.0 | 0.58 | **2.68**（占 3.29 窗 81%） | 0/0 | — | — |
| m4singer_synthetic_long | 257 | 3.0 | 1.0 | 1.01（占 2.01 窗 50%） | 47.9% | +0.0033s | 2.06s |
| mir1k | 5 | 3.0 | 1.0 | 1.0（占 2.0 窗 50%） | 80.0% | −0.0007s | 2.04s |

- 中间读法：**demo 上 E9 严重 fallback**（beam 几乎没推进）；合成 long 上 oracle 命中约一半、
  selected delta_MAE≈0、改善/劣化对半（63/64）——**beam 目前未表现出稳定增益**；
  mir1k 相对正向但样本极少(5)。
- 一句话：**E8 存在 clean-harm 风险（native harm>imp），E9 在 demo 上近似退化、在长序上未显著胜出**；
  两者都亟待 7.2 的补做对照实验确认是“机制不适用/配置激进”还是“数据不足”。

### 8.4 工程信号
- 推理缓存有效：inference_cache hit 60%、serial 78%；当前 m4long 段约 36s/项。
- 0 failure；抽样 200 项 phases 全完整 —— 数据落盘完整性良好，值得做最终汇总。

### 8.5 关于"大量 m4singer native 会否在 E5/E7 上浪费时间"（已核实）

**结论：不会浪费。E5/E7 对 M4Singer native 是"按需激活+推理前短路"，非全量跑一遍。**

- E5（`run_alignment_research_suite.py:1759`）：`applicable = len(base_plan["windows"]) >= 2`
  —— base_plan 构建在 `safe_boundary_candidates`/`build_dynamic_window_plan`（纯 CPU）之上，
  单窗 m4native 直接 `applicable=False`，**跳过 3 个变体的 `windowed_alignment` 模型推理**。
- E7（`run_alignment_research_suite.py:1902`）：`len(windows) < 2 → applicable=False`，
  只做从既有 baseline trace 构建 frozen_plan 的 CPU 遍历，**跳过 16+ 注入推理与 reset 重跑**。
- E6/E8/E9 同理按 `silence`/`case_count`/`beam` 判定；单窗无静音 native 全 not_applicable。

时间分布（已落盘 21047 项，累计 wall 40261s）：
| 类型 | 项数 | 累计 wall | 占比 | 单项均值 |
|---|---:|---:|---:|---:|
| 多窗 或 E8 适用项 | 9589 | 27291s | 67.8% | ~2.8s |
| 轻量(全不适用)项 | 11458 | 12969s | 32.2% | **1.13s** |

- M4Singer native 典型项 wall≈1.1–1.4s，E5/E6/E7/E8/E9 全 False，仅 E0/E1/E3 存 JSON。
- **时间大头集中在 "多窗或 E8 适用" 的 ~9589 个样本**（demo / m4long / mir1k / 有 E8 case 的 native），
  即真正触发 E5/E7/E8/E9 推理的那些；大量单窗 native 走轻路径，不是瓶颈。
- 经验证：E5/E7 在各 item 上**只对 ≥2 窗样本执行代价昂贵的变体/注入枚举**，
  其余样本仅 CPU 计划判定即退出，因此批量浪费可忽略。
