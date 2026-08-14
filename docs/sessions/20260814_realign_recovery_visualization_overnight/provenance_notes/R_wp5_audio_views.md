# R_note — WP5 E3 observation/context study：audio recrop/multi-scale + k1/k3 closure

会话：`20260814_realign_recovery_visualization_overnight`。实现人/时：WP5 实现子任务（STEP BUDGET=10）。
目标（02 E3 §225-268 冻结）：判断哪种上下文（尤其 audio observation）能把模型从错误迁移域拉出来。
本轮 WP5 只落地 E3-A（k1/k3 closure，no-GT structural）与 E3-B（audio recrop/multi-scale）；E3-C anchor 属后续。

## 1. 交付物

| 文件 | 角色 |
|---|---|
| `src/lyricalign/unit_realign/audio_views.py` | view 几何注册、按 view 建 v2 request、no-GT view 选择 |
| `scripts/unit_realign/run_audio_views.py` | E3-B 运行器（smoke/real + resume），产出 01/02/06/FINAL_VIEWS |
| `scripts/unit_realign/closure_k1_vs_k3.py` | E3-A 只读 closure，旧 k1/k3 复用 no-GT structural → `CLOSURE_REFERENCE.json` |
| `docs/sessions/.../provenance_notes/R_wp5_audio_views.md` | 本备注 |

## 2. `audio_views.py` 契约

### 2.1 AUDIO_VIEW_SCHEMAS（预注册 views，非网格）
seconds 口径按 02 E3-B：
- `base`：target span ±0.5s local；
- `wider`：target span ±1.5s（wider local）；
- `left_enriched`：左扩 +1.0s、右 +0.3s（left-context enriched）；
- `recentered`：R-U proposal 中心 ±0.8s；无 proposal 时回退 target-span 中心（记录 `recenter_source: "target_span_center"`）。

`register_audio_views(region, target_unit_ids, duration_sec, *, view_kinds, recrop_view_id_prefix, proposal_center_sec)` → list of
`{recrop_view_id, view_kind, audio_start_sec, audio_end_sec, recenter_source}`。
纯几何，无 forward、无 GT。crop 会被 `duration_sec` 裁剪到 `[0, duration_sec]`。

### 2.2 build_view_requests
对同 region 每个 view 建一个 v2 request（复用 `build_family_request`，family 默认 R-U），并把 view 音频范围覆盖到该 crop：
- `identity_context` 并入 `recrop_view_id`、`view_kind`、`audio_view_schema=audio_view_study_v1`；
- `build_family_request` 会把 identity_context 折入 `chain_context`，`build_request_identity` content-address 整个 chain_context，
  → **不同 view（同一音频不同 crop）identity 必不同，不复用旧 forward**（WP1 P1-2 / C_note §3.3）。
- 覆盖 audio 范围后 `_override_audio_range` 重新 `build_request_identity`（crop 本身也进 digest，双保险）。
- leaf view 无 parent，故 `build_request_identity` 的 chained-fail-closed（需四维度）不触发。
- null / not_constructible 保留各自行，不静默丢弃。

### 2.3 select_view_no_gt（GT firewall / fail-closed）
输入每个 view 的 result（含 `candidate_rows`，可带 no-GT 信号），**只用实际可得 no-GT 信号**，绝不读 GT/outcome/oracle：
- 数值信号（E_note §2 / unit_gate_features allowed keys）：`detector_p_bad(_after)`、`margin`、`entropy`、
  `raw_official_disagreement_ms`、`mean_boundary_displacement_ms`；
- 结构标志：`candidate_missing`、`context_protected`（计入 per-view 摘要，不作为决定性排序）。
- 逻辑：
  - 无可用数值信号 → `status=no_signal`、`selected=False`（**不用 GT 硬选**）；
  - 可用信号但无可唯一胜者（全平）→ `status=indeterminate`、`selected=False`；
  - 可用信号且唯一胜者在最多决定性信号上 → `status=selected_no_gt`、`selected=True`、`selected_view=recrop_view_id`；
  - 决定性票数平手 → `indeterminate`。
- 返回 schema `audio_view_study_v1`，含 `per_view`、`usable_signals`、`votes`、`reason`。
- 已单测：no_signal / tie→indeterminate / unique winner→selected_no_gt；序列化全量不含 `outcome/oracle/max_boundary_error` 等 GT 泄漏键（GT firewall pass）。

## 3. `run_audio_views.py` 输出（schema `audio_view_study_v1`）

CLI：`--out-root --regions --views base,wider,left_enriched,recentered --family R-U --duration-sec
--limit --smoke|--real --model-dir --revision --checkpoint-path --resume`。

- `01_requests/REQUESTS.jsonl`：每个 (region, view) 一个 v2 request（`recrop_view_id`/`view_kind` 标识 view）。
- `02_views/VIEW_OUTCOMES.jsonl`：每 view 一行，字段：
  `schema/song_id/region_id/request_id/request_identity/recrop_view_id/view_kind/family/audio_start_sec/
  audio_end_sec/status/candidate_rows` + 选择结果
  `selection{selected, selected_view, status, reason}`、`no_gt_selection_triggered`、`is_selected_view`。
  `candidate_rows` 每行含 no-GT 结构信号（`mean_boundary_displacement_ms`/`candidate_missing`/`context_protected`）。
- `02_views/REGION_<song>__<region>.json`：每 region 的完整选择 summary（含 per_view 与信号均值）。
- `02_views/FINAL_VIEWS.jsonl`：每 region 汇总 `selection_status/selected/selection_triggered/n_ok_views/selected_view_row`。
- `06_runtime/RUN_STATE.json`（schema `audio_view_run_state_v1`）：`completed_view_identities` 等，resume 依据；
  `--resume` 跳过已完成 identity。
- `FINAL_VIEWS.json`：run 级汇总（executor/n_regions/n_views/n_completed/n_skipped_resume/n_failed/
  n_selected_no_gt/n_indeterminate/n_no_signal/views）。

**smoke 模式**：合成确定性 region（8 units、target 3..5）且 `--regions` 可选；fake executor 确定性 nudge targets +0.1s；
基线来自 region.units（frozen detector，无 forward）。selection 用 `mean_boundary_displacement_ms`
（baseline vs candidate，no-GT）在 view 间比较 → smoke 里 base view 位移最小，故 `selected=base`。

**real 模式**：需 `--model-dir/--revision/--checkpoint-path/--regions`（有真实音频）；信号若含 raw/official 双 decoder、
per-unit entropy/margin（E_note §2），`select_view_no_gt` 才在这些信号上决策。

## 4. k1/k3 closure（`closure_k1_vs_k3.py`）

- 旧 `unit_realign_explore_context_{k1,k1_vs_k3,k3,k1_v3,k3_v2}_20260813*` 为 **research_v7 schema**
  （`input_variant/workflow_mode/parent_request_id/...`），非 v2 `unit_realign_request_v2` ，
  **不接 v2 可视化**（C_note §4 / 07 §11 anti-scope）。
- 本脚本**只读**，不重 materialize、不重 forward；读旧 `CONTEXT_PADDING_COMPARISON.json`
  （scope=`no_gt_structural_screen_only`，非 accuracy 声明）→ 输出 `CLOSURE_REFERENCE.json`
  （schema `audio_view_study_k1vsk3_closure_v1`）。
- 复用判断：`scope` 必须为 `no_gt_structural_screen_only`，否则拒绝当 closure 参考。
- 可再派 k1/k3 的 research_v7 `02_behavior`（`--k1-root/--k3-root`）重派生结构计数
  （sparse_fixed 数、active/text 比）与 CONTEXT_PADDING_COMPARISON 对账。
- 实测对账：k1 mean_active_to_text_ratio=0.789631、k3=0.576985（与旧 comparison 一致）；
  结构结论 = 长上下文(k3)平均多固定 ~3.04 units 且 target 槽不变、sparse fixed 精确还原（screen pass，不做 accuracy 声明）。

## 5. smoke 输出记录（CPU-only，本轮验收）

```
PYTHONPATH=src python scripts/unit_realign/run_audio_views.py \
  --out-root <OUT> --smoke --views base,wider --limit 3
# -> n_regions 3, n_requests 6, n_completed 6, n_failed 0
#    每 region selection: status=selected_no_gt, selected=base (位移最小)
PYTHONPATH=src python scripts/unit_realign/run_audio_views.py \
  --out-root <OUT> --smoke --views base,wider --limit 3 --resume
# -> n_skipped_resume 6, n_completed 6   (幂等)
```
- 验收 1 不同 view identity 互异：6 requests 的 `request_identity` 全部 distinct（recrop_view_id 生效、不复用）。
- 验收 2 VIEW_OUTCOMES 字段齐全：上述 schema 全量存在（含 candidate_rows 信号与 selection 结果）。
- 验收 3 resume 幂等：重跑 `--resume` 6 identities 全 skip，完成数不变。
- 验收 4 GT firewall：`select_view_no_gt` 无 GT；单测 no_signal/indeterminate 路径 fail-closed，
  winner 用 `mean_boundary_displacement_ms`（no-GT），输出无 outcome/oracle/max_boundary_error。
- 全 4 views smoke（`--limit 2`）：8 requests identity 全 distinct，view_kinds 覆盖
  base/wider/left_enriched/recentered，`recenter_source=target_span_center`（smoke 未喂 proposal）。

> 注意：由于本子任务沙箱不可写 `/home/hyan/Data/lyricalign/runs/`，smoke 用 workspace 临时 out-root
> （`.smoke_wp5_*`）验证后已清理。正式 formal 请在 data 目录另建 run root（`--real + --regions`）。

## 6. GPU formal 模板

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
OUT=/home/hyan/Data/lyricalign/runs/wp5_audio_views_formal_20260814
PYTHONPATH=src python scripts/unit_realign/run_audio_views.py \
  --out-root "$OUT" --real \
  --regions "<real REGION_POOL jsonl>" \
  --views base,wider,left_enriched,recentered \
  --family "R-U" \
  --model-dir <snapshot> --revision main --checkpoint-path <ckpt> \
  --resume
# 产出：01_requests/REQUESTS.jsonl, 02_views/VIEW_OUTCOMES.jsonl+REGION_*+FINAL_VIEWS.jsonl,
#       06_runtime/RUN_STATE.json, FINAL_VIEWS.json
```
预置：真实 region 需 identity_context 已经冻结（audio_sha256/baseline/model/checkpoint/decoder/mapping/code/text_adapter），
沿用 `run_unit_realign.py population` + `source_adapter.attach_audio_and_identity` 产出的 REGION_POOL。
正式期 freeze 所有 view 偏移/length/duration；只修复 schema/identity bug。

## 7. 遗留 / 后续

- `proposal_center_sec`（recentered 用 R-U proposal 中心）在 smoke 未喂入 → 回退 target 中心；
  正式接 WP6 coarse→fine 时从 R-U proposal 流水线注入。
- `detector_p_bad / margin / entropy / raw_official_disagreement` 依赖真实 decoder 输出（E_note §2）；
  当前 v2 flat candidate 行未含（smoke fake 两者同构无 disagreement），real 若配 `research_evidence_config`
  才导出。E5 no-GT selector（07 §9 WP7）会接这些。
- k1/k3 只做 no-GT structural 复用，**不**为旧 run 补 forward/进 v2 可视化（anti-scope）。
- E3-C stable anchors、one-sided anchor pilot 未在 WP5，属后续（02 E3-C）。

## 8. review 后补充（S_review_wp5，2026-08-14）

S review：**无 P0/P1**，3 MINOR。其中 MINOR-1（select_view_no_gt 无提交级回归）已补
`tests/unit_realign/test_audio_views.py`（no_signal / unique winner / all-tied-indeterminate /
votes-tie 四路径 + GT firewall 断言，4 passed）。MINOR-2（real 下 identity=None 的 view 静默缺行）
与 MINOR-3（死参数 `_view_result.view_out`）记 backlog，formal real 前优先处理 MINOR-2。
