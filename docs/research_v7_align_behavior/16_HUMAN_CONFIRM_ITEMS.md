# 离线性人工确认清单（Long-Slot Region Assessor，2026-08-04）

> 供 Review 者/ChatGPT 离线后逐项确认。离线前已完成的自动部分见
> `evidence/research_v7_stageA/PRECHECK.json` 与 `research_v7_evidence_bundle.tar.gz`。
> 自动结论一律标 `draft`，最终科研结论由人工复核后修订。

## A. 人工标签缺口（需审阅/补齐）— 依据 PRECHECK.human_review_audit

| Run | 状态 | 需要人工做什么 |
|---|---|---|
| `demo_all_partitioned_20260804` | ✅ 已填（140 例：VALID_STABLE 42 / TAIL_COLLAPSE 33 / LOCAL_SHIFT 32 / WRONG_REPEATED_SECTION 25 / ZERO_DURATION_CLUSTER 7 / UNRESOLVED 8 / VALID_BUT_UNCERTAIN 5 / HEAD_COLLAPSE 1） | 审阅 normalization 是否正确；确认是否可作标签源 |
| `demo_c10_repeated_sections_20260804` | ❌ 仅空模板（reviewer=null, labels=[]） | 需人工标注重复段行为 |
| `demo_low_vocal_energy_controls_20260804` | ❌ 仅空模板 | 需人工标注"弱人声"档位（当前只 auto candidate/RMS） |
| `demo_accompaniment_controls_20260804` | ❌ 仅空模板 | 需人工标注伴音对照 |

> 是否由我提前把空模板 `blinded_review_packets.json` 生成视频/分册、标注字段补好格式？请在离线回复中指示。

## B. 长时间线源选择（需确认主 cohort）

- **候选**：M4 同 song 片段累积 ≥180s 共 **194 首**，≥90s **379 首**。
- 样例：`演员`(1239s)、`好久不见`(1148s)、`小酒窝`、`东风破` 等。
- **需确认**：主 cohort 用哪些 song（建议 ≥10 首、覆盖多语言/多歌手）；0.5s seam control 用哪些。

## C. 蓝图完整实施决策

- 本轮只完成 **WP1(identity) + WP0-lite(preflight) + sparse_slots(已有) + real_executor(部分) + 证据包收集器**。
- **未实现**：WP2 timeline、WP3 canonical_mapping/slot_planning、WP4 hidden/logits、
  WP5 features/region_metrics、WP6 region_assessor、WP7 run/report。
- **需确认**：是否继续实施完整蓝图（多轮 + GPU 正式采集）；还是先审阅 preflight 与 demo 主批实现。

## D. 证据包

- `research_v7_evidence_bundle.tar.gz`（**0.12MB ≤5M**）已生成，含：
  `PRECHECK.json`、`EVIDENCE_INVENTORY.jsonl`（73 文件清单+sha256）、`BUNDLE_MANIFEST.json`、
  `SUMMARY.json`、v7 文档（00-15）、代码哈希；不含权重/音频/大数据。
- 离线结束后可据此复核。

## E. 硬约束提醒（14 合同）

- formal 目标 ≤10h / 硬限 ≤12h；不得用人工静音凑 180s；不得在 test/demo 选阈值；
  不得把 P1 prefix 叫真实串行；不得用 GT 每窗 reset；missing/replace 必须 proper 评价。

---

## 更新（2026-08-04，离线推进后）

### A'. 弱人声/伴奏 controls —— 已按你的反馈改进为三档
- **来源**：均来自早前 Demucs 分离的既有 `test/{song}_qwen_fa/work/audio/{vocals,accompaniment}.wav`（mtime 07-26/28，**非我新建、未破坏原数据**）；controls 为独立 `demo_challenge` run，**未混入正式实验**。
- **改进**（`build_vocal_energy_controls_v2.py`，已 push e55f905）：
  - 三档同窗口对照：`C6:normal`(70分位 normal 参考) / `C6:weak-vocal`(min RMS 窗) / `C6:weak-vocal+accomp`(low-vocal 混伴奏，MIX_ACCOMP_GAIN=0.25)。
  - **收紧**：weak 窗绝对 RMS ≤5（默认），且 weak/normal RMS ratio ≤0.5；结果 35→17 item（跳过 18 个仍太响的），weak RMS 现 0.82~3.75。
- 你在线可抽查 `runs/research_v7_align_behavior/demo_low_vocal_energy_controls_20260804/`（旧的）或 v2 manifest 输出；如需跑 v2 的 51 请求可再执行。

### B'. C10 —— 已确认是自动合成，无需人工标注
- `build_repeated_section_manifest.py` 自动从真实歌词检测重复 n-gram → 生成 `C10:short-repeat` / `C10:double-repeat`；多解由合成重复结构天然产生，taxon 自动可证。
- **无需人工盲审**；之前我将其列为"需人工判断"是误判，已更正。
- C10 位置：`runs/research_v7_align_behavior/demo_c10_repeated_sections_20260804/`。

### 仍待你确认
- 主 cohort 长时线（≥180s）song 选择；
- 是否继续实施蓝图 WP2-7（此前已 scaffold + smoke；正式模型采集待你批准 budget）。
