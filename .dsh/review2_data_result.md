# Review2 数据一致性/文档对照/证据完整性审查结果

审查者:数据一致性审查 agent(用户约束:不造假/mislabel;数字由结构化 JSON 生成)
审查范围:20260814_runs_summary 6 份 md + session 03/04/08/09 + RUN_STATE;关键数字对照真实 JSON。
方法:python(json.load)对 `runs/20260814_*` 与 `viz_fullsong_prep/` 的 alignment.json 直接计数零时长(
`start_sec==end_sec`),并核对 FINAL_COARSE_FINE.json 聚合字段。零时长口径经验证与文档一致
(4/5 核心歌可复现,见下)。

---

## 已交叉验证为一致(非问题,W可放心引用)的数字

### 劣势歌零时长(Current=full-slot batch/schema `qwen_fa_batch_alignment_v4`,B4=pre-slot serial/schema `qwen_fa_serial_demo_v7`)
- **月半小夜曲**: Current 零时长 = 104/388 = 26.8%, B4 = 80/388 = 20.6%,Δ+6.2pp ✓
  依据 `viz_fullsong_prep/Cantonese/月半小夜曲_qwen_fa/alignments/r2/vocal/windowed/alignment.json`
  与 `runs/20260814_b4review/月半小夜曲/alignments/r2/vocal/windowed/alignment.json`
- **祈愿花开**: Current = 11/463 = 2.4%, B4 = 7/463 = 1.5%,Δ+0.9pp ✓
  依据 `test/Chinese/祈愿花开_qwen_fa/...`(Current,无 viz_fullsong_prep 副本)与 b4review 对应路径
- 104 空中 overlap_compressed=0、collapsed_to_zero=0(schema 与 summary 均确认)→ EXPLORE 称「零时长非后处理压缩」✓
- 散布起点 33.4(连3,如泣琴)/36.3/48.2/53.4/60.2/62.4 均存在 ✓

### 核心 5 首零时长(REVIEW_SLOT_VS_PRESLOT 表)
复现我(near-zero 容差测试不变):乙女... 见问题#1 例外。
- 浮夸 B4=7.2/Current=6.8 ✓、PastLives 4.3/4.3 ✓、此处通往天空 1.7/1.0 ✓、人造卫星 1.9/1.5 ✓,均与 JSON 复现一致。

### R-CF 数字
- 月半 EXPLORE「stage_a=36/36, stage_b=2/36 成功、34 失败」✓ 依据 `runs/20260814_explore/yueban_rcf/FINAL_COARSE_FINE.json`(stage_a=36,stage_b=2)
- R-CF test-demo「59/59 stage-B, recovered@200 53/59, fixed_context_disp=0ms」✓ 依据 `runs/20260814_rcf_demo/E4_demo_rcf/...`(stage_b=59,rec200=53)
- E4 40-region「stage-A 27/40, stage-B 15/27, catastrophic 8/40, fixed_ctx 全 0, rec200/500/1000=10/12/13」✓
  依据 `runs/20260814_wp6_E4_full/FINAL_COARSE_FINE.json`

---

## P0/P1 问题清单

### [P1 MAJOR] 1. runs_summary 中 3 处零时长率与 citable JSON 不符,且两文档互相矛盾(乙女解剖/浮夸/此处通往天空)
- **`VIZ_B4_VS_CURRENT_FAIR_FINDING.md` L14-17** 与 **`REVIEW_SLOT_VS_PRESLOT.md` L11,14-15** 的数值无法从文档所标 json 源复现:
  - 乙女解剖:文档称 B4=22.3、Current(vocal)=21.3(fair)/20.8(review)。真实 JSON:
    B4=78/341=**22.9%**, Current=74/341=**21.7%**(依据 `runs/20260814_viz_B4/乙女解剖/...` 与
    `viz_fullsong_prep/Japanese/乙女解剖_qwen_fa/alignments/r2/vocal/windowed/alignment.json`,na2 341 字 Japanese/nagisa 同源同分词,char 全同于 B4)
  - 浮夸:fair 文档 Current=6.4%,reality=**6.8%**;REVIEW 文档=6.8%(正确)。
  - 此处通往天空:fair 文档 Current=1.7%,reality=**1.0%**;REVIEW=1.0%(正确)。
- **性质**:同源 Current(vocal) 数值,FAIR 与 REVIEW 两文档本身就有矛盾(21.3 vs 20.8 / 6.4 vs 6.8 / 1.7 vs 1.0),
  且 REVIEW 除乙女外均与 JSON 复现一致 → 乙女(fair+review)、浮夸、此处的 fair 版数字是从早版/其他来源手抄或
  被混淆,违反「数字由结构化 JSON 生成,绝不手抄」。
- **影响**:乙女解剖 3 处当前值(22.3/21.3/20.8)都不对,正确 22.9/21.7;浮夸 fair 6.4 应 6.8;此处 fair 1.7 应 1.0。
  定性结论(Current 不劣于 B4)不变,但具体百分比引用必须修正。
- **建议**:重跑同一 python 计数脚本(id 到 `files` 源),用结果覆盖 fair/review 两张表的乙女/浮夸/此处数值,
  并附源头 json 路径;两文档当前互相矛盾的 4 处必须统一。

### [P0 CRITICAL] 2. 月半小夜曲零时长「散布单点/孤立单字」刻画不实,遗漏占 47% 的 49 字连续块,动摇根因结论
- **`REVIEW_SLOT_VS_PRESLOT.md` L27-29** 与 **`EXPLORE_FULLSLOT_ZERO_DURATION.md` L13-15,18** 反复称 Current 月半
  零时长为「散布单点」「孤立单字」(仅举 33.4 连3,36.3/48.2/53.4/60.2…),并据此归因 R-CF 救不回是因为
  「target 多为孤立单字,没有足够无异常邻域做 sparse/fixed 精修」。
- **事实**:Current 月半 104 个零时空中,有 **49 个是 global index 160-208 的连续块**(109.6-109.7s,window1,
  词面「仍然倚在失眠夜望天边星宿仍然听见小提琴如泣似诉再挑逗…」),占全部零时长的 **47%**,并非散布单点。
  其余 36.3/48.2/53.4/60.2 等才接近孤立单点。见上面验证输出。
- **性质**:headline 根因叙事(「孤立单字→无邻域→sparse/fixed 救不回」)与源数据直接冲突;且该 49 字块在
  `runs/20260814_explore/yueban_rcf/01_requests/REQUESTS.jsonl` 的 36 个 region 里被切碎成 ≤3 字/区(24 区仅 1 字、
  最多 3 字),可能使 coarse-fine 看不到真实连续上下文。这是劣势歌根因探索的核心结论,属于 P0。
- **建议**:补一段对「49 字连续块(109.7s)」的显式披露与再分析:该块为何整体坍缩到同一点、它与「散布单点→无邻域」
  叙事是否冲突;若 region 构造把连续块切成 ≤3 字,需说明并对该块单独立 region 重测 R-CF,而非沿用散布单点结论。

### [P1 MAJOR] 3. B4 劣势歌 provenance 已实跑却未登记进索引/会话口径,读者无法溯源
- **`VIZ_AND_TRIALS_INDEX.md` L10** 与 **`09_GPU_REAL_RUN_REVIEW.md` L70** 均把「真 B4 对齐源」登记为
  `runs/20260814_viz_B4/<song>/…`(仅 5 首:乙女/浮夸/PastLives/此处/人造),未含月半小夜曲、祈愿花开、冬之花。
- 但劣势歌(月半/祈愿/冬之花)的 B4 零时长数字实际来自 **`runs/20260814_b4review/<song>/…`**(schema 同为
  serial_demo_v7,合法 pre-slot;数字本身经我对账正确),该目录未被 index/09/RUN_STATE 提及。
- **性质**:数字正确但 provenance 断链——严格按文档登记源无法复现月半/祈愿/冬之花的 B4。违背「可追溯、不 mislabel」。
- **建议**:在 VIZ_AND_TRIALS_INDEX 新增一行,登记 `20260814_b4review/`(月半/祈愿/冬之花,pre-slot serial,
  与 viz_B4 同 schema 同 ckpt step-000750),并把 REVIEW_SLOT_VS_PRESLOT 非核心 3 首的 B4 数据源引用到该目录。

### [P1 MAJOR] 4. runs_summary 归档 summary JSON(E4)是陈旧 5-region pilot,与 09 的 40-region 口径不一致
- **`20260814_runs_summary/E4_GPU_real_coarse_fine.json`** 记录 `regions:5, stage_b_constructible:3`(5-region pilot),
  而 **`09_GPU_REAL_RUN_REVIEW.md` L55-61** 报告的是 40-region 扩量(27/40, 15/27, catastrophic 8/40)。
- 40-region 数字我在 `runs/20260814_wp6_E4_full/FINAL_COARSE_FINE.json` 已验证准确;问题在归档 summary JSON
  与主流文档口径不一,误导读到 summary JSON 者。
- 同理 E2 summary JSON 只记 `regions:5`,而 09 L81-82 讲的是 40-region direction 矩阵(rec 0.748, 26/40, ctx_harmed 80)。两 summary JSON 均未反映 40-region 扩量。
- **建议**:将 E4/E2 的 summary JSON 更新为 40-region 聚合(数据源已存在 wp4/wp6 的 full run FINAL 文件),或加
  `scale:40` 副文件,和 09 对齐。

---

## MINOR(进 backlog,不阻塞)
- `VIZ_FINAL_4WAY_RCF_DEMO.md` 只覆盖 5 首,而 EXPLORE/REVIEW 讨论月半/祈愿等非核心劣势歌;交付目录
  `20260814_viz_DELIVER/` 实则含月半/祈愿 image/video,与文档标题「5 首」不一。建议在交付文档补非核心歌交付记录。
- `REVIEW_SLOT_VS_PRESLOT.md` L16 说「优势仅 0.4–1.5pp」但乙女实测 Δ=1.2pp(22.9→21.7),需随#1 修正同步更新。
