# 08 会话终期执行报告（WP11 收尾）

> Session: `20260814_realign_recovery_visualization_overnight`
> 日期: 2026-08-14
> 状态: **规划与实现完成 + CPU smoke 全绿；GPU formal 因环境 GPU 不可用延后（命令模板已交付）**
> 依据: `04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md` §10 收尾要求

---

## 0. 结论强度与诚实性总述

本轮完成了 **2026-08-14 session 全部 11 个 work package 的实现 + 每批次双路 review + 修复**。
因本会话沙箱 **GPU 不可访问**（`nvidia-smi` 失败），所有 runner 只做了 **CPU smoke 验收**，
**未跑正式 GPU forward**。因此：
- 代码/契约/数据接线的正确性：**已验证**（387 个单元测试 + 每个 WP 的双路 review）；
- 科学结论（recovery rate、oscillation、context displacement 等数值）：**需在 GPU 可达环境
  按交付的 formal 批命令模板执行真实 forward 后才能得出**，不以 CPU smoke 数值冒充正式结果。

这符合 `01_CURRENT_EXPERIMENT_RESULTS_AND_CONCLUSIONS.md` 的原则（平均误差下降≠精确修复；
consensus/fixed-point 非 correct 充分条件）与 AGENTS「运行完备才算完成」纪律：
实现的正确性已完备，正式运行的启动条件（GPU）未满足——按 `04 §3` 交付 formal 命令模板。

---

## 1. 实际执行阶段 与 未执行项

### 已执行（全部走「实现 → 双路 review → 修复」循环）
| WP | 内容 | 实现 commit | review | review 修复 | 单测 |
|---|---|---|---|---|---|
| 合并 | zip → session 激活 | 20e4afb | sha256 核对 | — | — |
| 前置 | Codex provenance 10 事实 | 4785170 | — | — | — |
| 07 计划 | 实现计划 + G/F review | 0408667 | G/F | P0/P1 | — |
| **WP1** | E0 冻结 + identity | 94fa0bf,e2729fa | H/I | P1×2 | +2 |
| **WP2** | 可视化 adapter/controller | 714d514,dfb2e33 | K/L | P0×1,P1×3 | +4 |
| **WP3** | E1 multi-realign | 3d19152 | N/O | P0×1,P1×4 | +2 |
| **WP4** | E2 fine-split | e257542 | Q | P0×1,P1×1 | +4 |
| **WP5** | E3 recrop/k1k3 | 622708b | S | 无 P0/P1 | +4 |
| **WP6** | E4 coarse-fine + 四路 | b89654b | U | P1×2 | +4 |
| **WP7** | E5 no-GT selector | 202bcba | W | P1×4 | +11 |
| **WP8** | P6 adaptive expansion | 5f17160 | Y | P0×1,P1×2 | +3 |
| **WP9** | E6 atlas + E7 serial | 37e88d9 | AA | P1×2 | +4 |
| **WP10** | Test Demo 可视化 batch | 416621b | AC | P1×2 | +0 |
| **WP11** | 收尾 + free-exploration | 本文件 | (见 §7) | — | — |

**小计**：36 个新提交；417 个提交前单测（0→387 新增）；28 个 provenance review/实现 notes。

### 未执行（需 GPU 环境）
- 所有 **GPU formal forward**（WP3/4/5/6/7/8/9/10 的 `--real` 路径）。
- **正式多语言可视化批量**（中/粤/英/日 + hard-case 全量 MP4）。
- **formal 指标结论**（recovery/oscillation/context displacement 等真实数值）。

---

## 2. 每实验 hypothesis / setup / observation / alternative-explanation / conclusion-strength

> 以下 observation 均来自 **CPU smoke**（合成/既有缓存 evidence），**非正式 forward**；
> 结论强度标注为「实现正确性验证 / 科学结果待 formal」两类。

### E0 冻结/freeze
- hypothesis：从代码字面量冻结 Current/B4 resolved baseline + identity，可复现可 hash。
- setup：`build_resolved_baseline.py` + `FROZEN_BASELINE_IDENTITY`；B4 用 serial runner official。
- observation：Current(full_slot/raw) 与 B4(pre-slot serial/official) 均可 hash（`identity_digest`），
  B4 cascade 的 `skip_silent_windows` 修正为 serial runner 默认 False（H-review P1）。
- alternative：B4 历史 exact cursor/commit 版本需对照 run 对账（formal.gap U1）。
- strength：**冻结口径正确（强）**；B4 exact 版本待 formal 对照（中）。

### E1 multi-realign dynamics
- hypothesis：相同 formulation 多次 realign 是否逐步纠回 vs 进入错误 fixed point。
- setup：`multi_iteration.py`，iter 1/2/3/5 chain，identity 含 parent/iteration。
- observation（smoke）：链能构造、iter 间 baseline 继承正确、target vs fixed-context displacement 分离。
- 结论强度：**机制正确（已验）**；「是否纠回」需 real forward（待 formal）。

### E2 fine-split
- hypothesis：困难区拆 1/2-unit/adaptive/anchor 扩大 recovery basin。
- setup：`split_variants.py` 四 partition × 三 direction，split_slot_id identity。
- P0 修复（Q-review）：真实 REGION_POOL 无 unit-level state → 适配层回写 + state_missing_fallback。
- 结论强度：**分区机制正确、真实数据可用（已验）**；「拆小是否扩大 basin」待 formal。

### E3 observation/context
- k1/k3 closure（no-GT structural，C_note 确认旧 schema 兼容）；audio views（4 预注册 crop）+ no-GT 选择器。
- 结论强度：**closure/recrop 机制正确（已验）**；「audio view 是否比 text context 强」待 formal。

### E4 coarse→fine + 四路可视化
- hypothesis：R-U proposal→recrop→sparse/fixed refine 组合同时接近 R-U target 与 R-S safety。
- setup：`coarse_fine.py`（family=R-CF）+ `render_current_4way --fourth-family R-CF` 四路接线。
- P1-1（U-review）：Stage B not_constructible 时 A-stage coarse 恢复不丢弃。
- 结论强度：**组合机制与四路渲染正确（已验）**；「组合是否达成两全」待 formal。

### E5 no-GT selector/safety
- setup：`no_gt_selector.py`，p_bad 主代理 + margin/entropy/raw-official，recovery-first/safety-first 分开。
- P1 修复（W-review）：proxy 生产者、true-85th、disjoint heldout、测试。
- 结论强度：**selector/firewall 正确（已验）**；「是否选对/安全拒坏」需真实 decoder 信号 + heldout formal。

### E6 atlas / E7 serial
- setup：`recovery_atlas.py`（6 分类）+ `run_serial_stress.py`（下游错误累计）。
- P1 修复（AA-review）：coarse 比例当布尔、recrop schema 标记。
- 结论强度：**atlas/serial 机制正确（已验）**；「真实 recoverability 图谱」待 formal evidence。

### E8/E9 Test Demo 可视化 batch
- setup：`run_test_demo_viz.py`（复用 WP2 controller + transcode）。
- P1 修复（AC-review）：family tracks item 收敛（防跨歌污染）、rerender-only 委托真实 renderer。
- 结论强度：**批量渲染正确、U4 3 mp4 判可开（已验）**；「正式多语言批量」待 GPU collection。

---

## 3. 预算 / forward / cache（04 §3, §6）

- 本 session **实际 GPU forward = 0**（GPU 不可访问）。
- CPU smoke 全部 `--smoke`/`forward=0`（E5 selector、E6 atlas 为纯读缓存）。
- 预算 projection（WP8 P6 adaptive expansion）：扩量 ~2880 forwards（estimate，记账非实跑）。
- GPU formal 命令模板已在各 WP note（R_note §6 / P_wp4 §6 / T_wp6 §6 / V_wp7 / Z_wp9 / AB_wp10 §6）。

---

## 4. Negative results / 结论边界

- **尚无正式 negative**（未跑 formal）。
- 已知边界（01 文档冻结）：CPU smoke 数值不可当科学结论；smoke 假 executor 的 target +0.1s 是
  离散 artifact 非真实声学；consensus/fixed-point 非 correct 充分条件。

---

## 5. Sample accounting / failed / not_constructible

- 各 runner 均实现 resume 幂等（按 request_identity 内容寻址）与 RUN_STATE 落桶
  （completed/queued/planned/failed/not_constructible；WP3 修复后 failed/not_constructible 正确落桶）。
- not_constructible 均为 fail-closed 显式（非静默）。
- CPU smoke 的 sample 为合成/既有缓存，non-coding；真实 samples 待 formal。

---

## 6. 可视化路径

- `scripts/realign_recovery/visualization/`：`visualization_controller.py` + `render_b4_vs_current.py`
  （B4-vs-Current 双路）+ `render_current_4way.py`（四路，`--fourth-family R-CF` 含 WP6 第四路）
  + `render_comparison_batch.py` + `render_rerender_only.py`（cache-only 重渲 + hash 断言）
  + `run_test_demo_viz.py`（Test Demo 批量）+ `transcode_media_to_wav.py`（U4 mp4 转码）。
- collection-before-visualization、GT firewall、纯 CPU（读 frozen evidence）已落实。
- Smoke 通过：Side by Side（B4 双路 + 三/四路）、Test Demo dry-run + 3s fourway。
- 正式多语言批量模板见 `AB_wp10_testdemo_viz.md §6`。

---

## 7. Free-exploration todo 状态

按 `04 §9`，主计划完成 + GPU 预算（此轮为 GPU 不可用）后进入 free-exploration 循环。
已生成首轮 free-exploration todo（见 `RUN_STATE.md` 与下一节），并保留「生成下一轮 todo 作为末项」
的递归约定，确保挂机时持续推进而非 run 完即空闲。

---

## 8. 下一步（formal 前置 + free-exploration）

### 进入 GPU formal 前必须
1. 在 GPU 可达环境执行各 WP 的 `--real` 命令模板（`model-dir='Qwen/Qwen3-ForcedAligner-0.6B-hf'`
   revision + checkpoint `step-000750`）。
2. 正式 B4 alignment 替换 raw stand-in（formal.gap U1）。
3. `<out>/scientific/` 落盘纳入 rerender hash 断言（formal.gap）。
4. E3/WP7 接真实 detector_p_bad/posterior（需 FrozenScorer 矩阵 / `research_evidence_config`）。
5. 用真实 FINAL 复核 WP8 schema 对齐（Y-review P0 已按真实字段名修）。

### Free-exploration 首轮 todo（`04 §9`）
1. 汇总 recovery-basin atlas，找"只差一种机制未测"的 hard cases。
2. mine 新 catastrophic / multi-view disagreement / serial drift / repeated-lyrics cases。
3. 用已缓存 candidate 研究真实 no-GT selector/safety feature。
4. 检查 coarse localization/retrieval 低成本替代实现。
5. 检查 current vs B4 客观回归，找最值得看的 Demo。
6. 扩 detector hard-negative / realign-failure 数据。
7. 汇总 negative results 与替代解释。
8. **重新审阅所有结果、失败样本、未验证假设，生成下一轮 free-exploration todo，
   并把"再次生成后续 todo"作为新 todo 的最后一项**（递归，保持挂机持续推进）。

---

*本报告仅基于已完成实现与 CPU smoke；正式结论需在 GPU 环境按 §8 命令执行后更新。*
