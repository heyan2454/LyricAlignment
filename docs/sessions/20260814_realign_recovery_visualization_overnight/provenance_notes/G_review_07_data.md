# G-note：07_CODEX_IMPLEMENTATION_PLAN.md 数据一致性 / 跨模块接线 / 文档对照 review

- 审查对象：`07_CODEX_IMPLEMENTATION_PLAN.md`（2026-08-14，plan 未实现）
- 对照源：02（指标/运行顺序）、03（V4/V6/V7）、04 §7/§8（指标口径/分离契约）、
  D_note §B.1/§C（pipeline 顺序 + Test Demo 33/3）、E_note §5（GPU 预算）、06_PLANNED_RUNS.yaml
- 结论：**存在 P0（06→07 phase/gate 映射遗漏 + 编号错位）；存在多处 P1（E1/E2/E4 指标口径不全）**。
  以下"问题→证据→建议"。

---

## P0

### P0-1：06 的 P6（adaptive_expansion 扩量）在 07 中完全缺失；且 G 编号与 06 phase 编号错位
问题 → 06_PLANNED_RUNS.yaml 的 phases 是 **12 个**：P0 freeze → PV viz_smoke → P1 screening → P2 split →
P3 context → P4 coarse2fine → P5 no_gt → **P6 adaptive_expansion(rule: expand_only_top_1_or_2_mechanisms_from_screening)** →
P7 recovery_basin_atlas → **P8 serial_accumulated_error_stress** → P9 multilingual_viz → PF。
07 §6 的 gates **只有 11 个**（G0–G10），其中：
- G7 标 `(P6)` 却写"E6 atlas / hard-case mining"；
- G8 标 `(P7)` 却写"E7 serial accumulated-error stress"。
→ 07 用 G7/G8 两个 gate 承接 06 的 P7(atlas)+P8(stress)，**既丢掉了 06 的 P6(adaptive_expansion)，
又把 06 的 P7/P8 错误标成 07 自己的 P6/P7**。
证据：07 §6 L157-158 `G7 (P6) E6 atlas`、`G8 (P7) E7 serial stress`；07 §5 run roots 只含
P6=E6_atlas、P7=E7_serial、P9，**没有任何 adaptive_expansion run root**；07 全文 grep 无
"adaptive_expansion / 扩量 / expand top1|2" 的 stage/gate/WP（仅 §8 预算推想用了 "expansion：1–2 机制 × ≥200 regions ≈ 300–500 forward"）；
07 §13 自称"本 plan 是 06_PLANNED_RUNS.yaml 的实现化映射"，故漏映射直接构成合同违约。
影响：screening(120–300 forward，07 §8) 无法按 06/02 E9"根据 strict recovery + safety 选 1–2 方向扩量"
落地到可执行、可 resume、可计账的正式扩量阶段；06→07 phase 无法一一对应。
建议：补回 `G7(P6) adaptive_expansion` run root（如 `20260814_visualization_P6_adaptive_expansion`）与对应 WP，
并把 atlas/stress 的 gate 标号改为与 06 一致的 P7/P8（atlas→G(07 的 G8 删去标 (P7) 前的错标，新增独立 gate 链）。
修正后 G 序应与 06 的 P0/PV/P1..P9/PF 一一对应，无遗漏。

---

## P1（会污染结论的指标/流程缺口）

### P1-1：E2（fine-split，WP4 / G3）指标清单严重不全
问题 → 02 E2 §205-214 明确 8 项指标：strict 100/200ms recovery、500/1000ms coarse recovery、context preservation、
split boundary harm、merge collision/overlap / **non-monotonic**、**recovered unit fraction**、**region all-hit / ≥75%-hit**、
**extra forward cost**。07 WP4 只写"指标 strict/coarse recovery、context preservation、merge collision"三句，
**漏 boundaria harm、non-monotonic（只检测 detect 于 test_split_variants.py 目标但未进所得口径）、recovered fraction、region all-hit/≥75%、extra forward cost**。
证据：07 §9 WP4 L223-225 与 02 §205-214 逐项比对。影响：split 结论缺 harm/fraction/forward-cost 维度，
无法判定"拆小是否扩大 basin"，会污染 E2 主结论。
建议：WP4 补全全部 8 项指标，并把 non-monotonic 与 merge collision 纳入产出 schema/报告（并记入 07 §3.2 `split_realign_v1`）。

### P1-2：E4（coarse→fine，WP6 / G5）无任何指标清单
问题 → 02 E4 §311-319 指标：target 100/200/500/1000ms、fixed context displacement、catastrophic regression、
constructibility/coverage、forward cost、no-GT safety signals、Test Demo objective structural regressions。
07 WP6 只写"R-U proposal→recrop→sparse/fixed refinement；fail-closed"，**无一句指标**。
证据：07 §9 WP6 L231-234。影响：第四路组合结论无法量化 report，也无法跟 E5 no-GT 衔接。
建议：WP6 补全 02 E4 §311-319 的 7 项指标，并入 §3.2 `coarse_fine_v1` schema 字段。

### P1-3：E1 multi-realign 指标把 target/fixed-context displacement 并成一个"displacement"，违反 04 §7 分离口径；first-hit iteration 未进 schema
问题 → 04 §7 要求 **target correctness 与 context safety 分开**：target displacement（02 §138）与 fixed-context
displacement（02 §139）是两个维度；审查/02 E1 §133 还要求 **first-hit iteration**。07 §3.2 `multi_realign_dynamics_v1`
只列 `displacement` 一项（未分 target/fixed-context），且**不含 first-hit iteration**（WP3 文字提了 first-hit，
但未固化进 schema，冒口口径易丢）。
证据：07 §3.2 L86 与 02 E1 §130-146。
建议：schema/指标分离 `target_displacement` 与 `fixed_context_displacement`（后者并入 context safety 报告类），
并补 `first_hit_ms_iteration{100,200,500,1000}` 字段；WP3 指标行显式列出 forward count/wall time。

### P1-4：Test Demo 3 个失败 song 是否补跑未落 plan
问题 → D_note §C.2（L136-138）明确：3 个 mp4 媒体打开失败发生在 detector pre-request，未进 realign manifest；
**修复媒体后重跑 detector 即可补上，且已完成 118 走 cache-only 不重算**。07 将 U4 列为 unknown 并用 ffprobe 判定
（正确），但**未把"3 个失败 song 是否补跑、补在哪个 run/gate（P9 Test Demo 可视化 batch 是否含这 3 首）"写入任何 WP/gate**。
证据：07 §1 U4、§12 U4；07 P9/PV 无补跑 3 song 的 action。影响：Test Demo 可视化批量（P9）若直接消费
现有 collection，将缺 3 首（Side by Side 正是 Smoke1 参考视频）；漏则 33+3→33 代表性不足。
建议：在 WP2(WP2 smoke)/WP9 明确决策：对 3 个 mp4 用 ffprobe 判定后，可打开的则转码/修复并补进
Test Demo collection，**必须在 G9 前完成补跑**；不可开则记录 failed 并确认不在 33 之列，避免可视化漏歌。

---

## 无 P0/P1 项

- **item2 run 布局**：07 §5 声明布局 = `scientific/ collection/ analysis_complete.json/ visuals/ renders/
  render_manifest.json/ scientific_hash_before.json/ scientific_hash_after.json`，与 03 V7 逐项一致 ✅
  （P0-1 已单列 run root 缺 adaptive_expansion，此处布局本身无缺项）。
- **item4 预算一致性**：07 §8 per-forward 取 0.5s（实测 0.2–0.75s，E_note §5.2）、screening 120–300 +
  expansion 300–500 ≈ 500–1000 forward、5–10 分钟 warm GPU、账本 RUN_MANIFEST.runtime_budget
  {elapsed_sec,forward_count,cache_hit,cache_miss}，均与 E_note §5 一致，且远 <10h/12h ✅
  （但见 P0-1：expansion 的 forward 计算依赖 06 P6，该阶段 run root/gate 缺失，预算与阶段编排不一致）。
- **item5 阶段顺序**：07 确实把 collection→visualization 落到实处，非仅文字声称——§0、§2.8、§4.2 代码改动表
  （`run_inline_realign_pipeline.py` 调整顺序或独立 visualization runner）、§6 G1/G9、WP2/WP9 均有明确 action，且
  §4.2 同时给出"不篡改旧 pipeline"的隔离备选 ✅。
- **item3 Test Demo 数量**：07 fact 9 正确引用 33 成功/3 失败/118 可 cache-only resume，无误报 ✅；
  Smoke1 媒体（Side by Side.mp4 恰为失败项）被 07 正确识别并用"换 `.mp3`/修路径"兜底（WP2）✅
  （补跑决策缺口归 P1-4）。

---

## MINOR（backlog）

- M1：§3.2 `multi_realign_dynamics_v1` 写 `osc`，02 §137 是 "oscillation / divergence" 两个词，建议分开列 div。
- M2：E7（WP8/G8）指标漏 cursor recovery latency、extra forwards/wall time、false recovery on originally safe
  windows（02 E7 §451-456）；已列 downstream error area / windows-to-recover / cumulative bad units 可续补齐。
- M3：WP8 标题 "E6/E7 long-running（P6/P7）" 引用了 06 不该存在的 "P6=long-running"，应改为与 06 对应
  （P7 atlas / P8 stress），一并修正于 P0-1。
- M4：04 §7 no-GT 含 `hidden`, 07 只接生产路径可得信号（raw/official/entropy/margin/p_bad/disagreement/stability），
  已在 fact8/E_note 注明 hidden 不可生产导出，属合理裁剪，非缺口；建议在 WP7 明示"hidden 实验性、需 collect_evidence_v3
  并重新走 E_note §6 核实"以免误解。

---

## 结论摘要
- P0：06 adaptive_expansion(P6) 阶段在 07 无 run root/gate/WP，且 atlas/stress 的 G7/G8 编号与 06 P7/P8 错位 → 修 phase 映射。
- P1：E2(WP4)、E4(WP6) 指标清单缺失/严重不全；E1 displacement 未分 target/fixed-context 且 first-hit 未进 schema；
  Test Demo 3 失败 song 补跑决策未落 plan。
- 预算(item4)、顺序(item5)、run 布局本体(item2)、Test Demo 数量(item3) ：无 P0/P1。
