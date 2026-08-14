# AD_review_wp11_report — WP11 收尾报告（08_SESSION_FINAL_REPORT.md）review

> 对照: `04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md` §10（收尾要求）与 §§1–9
> 证据来源: `08_SESSION_FINAL_REPORT.md`、`RUN_STATE.md`、`git log --oneline | head -40`、`ls provenance_notes/`、`ls scripts/realign_recovery/visualization/`
> review 日期: 2026-08-14
> 结论: **无 P0**；P1 ×3；MINOR 若干 → backlog

---

## 总体判断（摘要）

报告在「如实性」上表现优秀：§0/§2/§3/§7 反复、明确地声明 GPU formal 未跑、CPU smoke
数值非正式结论、forward count=0，未把 smoke 数值冒充 formal 结论，符合 04 §1
「不得提前收尾」与 AGENTS「运行完备/诚实」纪律。引用的 commit hash 全部在 git 历史真实存在
（15/15 抽查命中）；§6 引用的可视化脚本文件全部真实存在（8/8）；provenance notes B–Z/AA/AB/AC 共
28 份均在。free-exploration 递归约定（04 §9 第 8 项「生成下一轮 todo 作为末项」）在 §7/§8 完整保留。
未发现引用了不存在的 artifact。

**无 P0。**

---

## P1 （MAJOR）

### P1-1  §10 要求字段「CPU wall time」「cache hit」完全缺失（契约覆盖缺口）
- 问题: `08` §3 给出了 GPU forward = 0、CPU smoke `--smoke`/forward=0，但**没有任何 wall time**
  数字，cache hit 也只以 "E5 selector / E6 atlas 为纯读缓存" 一句话定性，未给出命中量/命中率。
  04 §10 明确要求报告含 "GPU/CPU wall time、forward count、cache hit"。
- 证据: `08` §3；`04` L162。
- 建议: 补一节注明 GPU wall time=0（未跑）、CPU smoke 各阶段 wall time（秒级）与 cache-hit
  计数/比例（按 request_identity 命中数），字段与 04 §10 逐字对齐。

### P1-2  单测计数自相矛盾、且与 RUN_STATE 不一致，削弱 §0“实现正确性已验证”的证据
- 问题: `08` §0 一句 "387 个单元测试" 作验证证据，但 §1 同一句是 "417 个提交前单测（0→387 新增）"——
  417 与 387 无法同时成立，语义自相矛盾。§1 表内每 WP 测试增量亦与 RUN_STATE 不符：
  WP1 "+2" vs RUN_STATE "243→351"（+108）；WP2 "+4" vs "6 track_view tests"；WP3 "+2" vs
  "6 multi_iteration tests"。
- 证据: `08` L15/L45 与 WP 表；`RUN_STATE.md` L11–21。
- 注: 本次会话中 `PYTHONPATH=src python -m pytest --collect-only` 因已知 conda readline
  SIGSEGV（commit e87c56e 提及）无法独立复核精确总数。
- 建议: 统一全报告的单一测试总数口径，明确「387」指当前 HEAD 全量单测数还是本 session 新增；
  修正 "417 提交前单测" 表述；每 WP 增量与 RUN_STATE 逐条对账。

### P1-3  §10 "alternative explanation" 仅 E0 有，E1–E9 缺失（契约覆盖缺口）
- 问题: `08` §2 每个实验均有 hypothesis/setup/observation/conclusion-strength，但显式
  "alternative explanation" 只出现在 E0（B4 历史版本待对账）；E1/E2/E3/E4/E5/E6/E7/E8/E9
  均无此字段。04 §10 要求"每个实验的 hypothesis/setup/observation/alternative explanation/
  conclusion strength"。
- 证据: `08` §2 E0–E9；`04` L163。
- 建议: 为每个正式实验补一行候选替代解释（如 E1 的"oscillation 是否 signed artifact"、
  E2 的"basin 扩大是否被 split identity 混淆"、E5 的"proxy 信号阈值敏感性"），即使结论为
  "待 formal 后补"。

---

## MINOR（进 backlog）

- M-1  §1 WP2 commit 引用 `714d514,dfb2e33`，RUN_STATE 记为 `714d514 + 44cc51d`；两个 fix
  commit（dfb2e33 为 transcode helper、44cc51d 为 P0/P1 fix）均为真实 commit，但表格未列全，
  报告与 RUN_STATE 对 WP2 的 commit 清单不一致。
- M-2  §1 "36 个新提交"：`git log 20e4afb~1..HEAD` = 38 个（含 20e4afb）；若扣除 merge 与
  `docs(state)` 辅助提交，"36" 可成立但口径未言明。
- M-3  §1 WP3 "E1 multi-realign … 未执行" 的表述建议明确：WP3–WP10 的 `--real` 均已交付命令
  模板但未执行，表格中 "已执行" 专栏仅指实现/CPU smoke，需避免读者误读为 formal 已跑（§0 已
  声明，属轻微措辞）。
- M-4  `08` §4 "尚无正式 negative" 合理；建议在 §4 同时注明哪些是"已存在的既有 evidence"，
  以便自由探索阶段不误判为新增 negative。

---

## 核查记录（最小命令）

```
git log --oneline | head -40
  → 15/15 声称 commit 命中（20e4afb 4785170 0408667 94fa0bf e2729fa
    714d514 dfb2e33 3d19152 e257542 622708b b89654b 202bcba
    5f17160 37e88d9 416621b）
ls provenance_notes/ → B–Z + AA/AB/AC 共 28 份，均在
ls scripts/realign_recovery/visualization/ → 7 个 .py（controller/b4vs or四路/
  comparison_batch/rerender_only/run_test_demo_viz/transcode），报告 §6 引用 8 个文件全部存在
  报告 §3 引用的 R/P/T/V/Z/AB note 的 formal 模板均含 --real/template 字样
```

---

## 结论

「如实性」与「artifact 正确性」为优（无标注不存在文件、无虚构 commit、GPU 未跑已诚实声明），
free-exploration 递归契约保留完整。P1 集中在 3 处：§10 两个必填字段（CPU wall time / cache hit）
与实际 alt-explanation 覆盖缺失，以及单测计数口径自相矛盾/与 RUN_STATE 不一致。MINOR 进 backlog。
