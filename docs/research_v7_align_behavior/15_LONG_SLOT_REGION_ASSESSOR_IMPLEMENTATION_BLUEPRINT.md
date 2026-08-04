# 长时间线 Slot/子区间判别器：可交接实现蓝图

日期：2026-08-04  
状态：**只定义实现，不运行 formal，不产出科研结论**。本文件是 `13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md` 与 `14_AGENT_EXECUTION_CONTRACT_12H.md` 的工程化补充；如有冲突，以 13/14 的冻结约束为准。

## 1. 交接目标和非目标

实现 agent 的完成目标是把已有 v7 的「单请求、基础 mutation、基础 evidence」骨架扩展为一个可 smoke、可 resume、可审计的长时间线研究管线。主线由 `>=180s` 数据时间线上的多个 **fixed 60s** 请求组成；不得实现或默认启用 180s 模型输入。

本次不得：修改 production commit 路线、把 demo 无 GT 一致性称为 accuracy、用 test/demo 调阈值、替用户选择弱人声档位、或直接启动 formal。实现完成后只能在 smoke/pilot 产出标有 draft 的自动结果。

## 2. 先做的现状核对（必须记录到 PRECHECK）

当前可复用实现：

- `src/lyricalign/research_v7/requests.py` 的 `AlignmentRequest`；
- `attempt.py` 的 `AlignmentAttempt`/`EvidencePack`；
- `real_executor.py` 的 raw、official、posterior、repair trace 基础抽取；
- `sparse_slots.py` 的 timestamp token mask；
- `scripts/research_v7/run_behavior_suite.py` 的 evidence 落盘与最小 resume；
- 既有 GT、workflow、demo/human-review 脚本。

现有实现不能直接用作本轮 formal 的原因也必须写明：`evaluate_behavior_gt.py` 只按 request index 做有限 mapping；`run_behavior_suite.py` 只按输出文件和完整 request dict resume，尚无内容寻址 identity、gap candidate、source-song split、严格 lineage/commit 状态或 region assessor；`real_executor.py` 尚未给出 hidden token 的可逆映射。不要暗中把这些缺口当成已完成。

先执行下列只读核对，并在 `PRECHECK.json` 保存命令、路径、摘要和 sha256：

```bash
PYTHONPATH=src python -m pytest -q tests/research_v7
PYTHONPATH=src python scripts/research_v7/verify_research_v7_outputs.py --help
find data runs docs -iname '*review*' -o -iname '*human*' -o -iname '*C10*'
```

不要根据文件名猜测 M4 的顺序、source-song id 或人工标签存在性；从实际 manifest/元数据读取并记录来源字段。

## 3. 固定目录、版本和公共 JSON 契约

新增的运行根目录固定为 `runs/research_v7_long_slot_region/<run_id>/`；`run_id` 必须由 UTC 开始时间、短 code hash 和冻结 manifest hash 组成。不得复用或覆盖既有 `runs/research_v7_align_behavior/` 的 evidence。目录如下：

```text
<run>/
  preflight/                 # 所有审计和冻结输入
  manifests/                 # jsonl；一行一个 source-derived request
  cache/{derived_audio,processor_inputs,audio_features,attempt_evidence,unit_gap_features,evaluations}/
  items/<request_identity>/evidence.json
  features/{train,val,test}/ # unit.jsonl、gap.jsonl、split.json
  assessor/                  # train-only transforms、models、frozen operating points
  reports/                   # json/csv/md；自动文档必须带 draft=true
  failures.jsonl
```

所有 JSON 顶层加入以下字段，且版本号不允许省略：

```json
{
  "schema_version": "research_v7_long_slot_v1",
  "created_at_utc": "...Z",
  "code_identity": {"git_commit": "...", "dirty_tree_hash": "..."},
  "request_identity": "sha256:...",
  "source_song_id": "...",
  "split": "train|val|test|demo",
  "draft": true
}
```

`request_identity` 是 canonical JSON（键排序、UTF-8、无空白）的 SHA-256，输入必须包含：代码/环境、model+checkpoint+processor、音频内容 hash 和 crop/transform、normalized units、slot indices、workflow/window 身份、mutation+seed、hidden schema、decoder/global-time conversion、canonical-mapping schema。只要任一字段不同，就不能共享 legal baseline 或 attempt cache。

## 4. 工作包与文件级实现顺序

以下是建议的增量提交顺序。每个工作包应先写纯 CPU 单测，再接入真实 executor；提交不得混入运行产物。

| WP | 新增/修改文件 | 实现验收 |
|---|---|---|
| 0 | `scripts/research_v7/preflight_long_slot_region.py` | 输出 source、时长、可构造 90/180s、human-review、语言边界、cache 和预算审计；不做推理。 |
| 1 | `src/lyricalign/research_v7/identity.py`、`schemas.py`，修改 `requests.py`/`attempt.py` | canonical JSON、内容 hash、严格 identity、schema upgrader；相同输入稳定，不同 slot/crop/text 必变。 |
| 2 | `timeline.py`、`scripts/research_v7/build_long_timeline_manifest.py` | 只从同 song/version/singer 且元数据排序明确的片段拼接；输出 seam 和全局 GT 映射。 |
| 3 | `canonical_mapping.py`、`slot_planning.py`、`scripts/research_v7/build_long_slot_run_manifest.py` | 输入轴、canonical GT 轴、output row 与 virtual gap 的可逆映射；60s windows、common anchors/phase 与 lineage manifest。 |
| 4 | 修改 `real_executor.py`、`attempt.py`、`run_behavior_suite.py` 或新增 `run_long_slot_suite.py` | raw/official/hidden 的一次 forward evidence、内容寻址 cache、阶段级 resume、失败隔离、真实 serial 状态。 |
| 5 | `features.py`、`region_metrics.py`、`scripts/research_v7/extract_region_features.py`、`evaluate_region_assessor.py` | 生成 unit/gap 特征、独立 source-song split、标签和 operating-point 指标。 |
| 6 | `region_assessor.py`、`scripts/research_v7/train_region_assessor.py` | rule、logistic、交互模型顺序训练；只从 train 拟合，val 冻结阈值和合并规则。 |
| 7 | `scripts/research_v7/run_long_slot_smoke.py`、`report_long_slot_region.py` | 执行 smoke gate、budget/pilot 报告、draft 汇总；formal 命令必须显式 `--formal-approved-manifest` 才可运行。 |

若仓库现有模块名已占用，可调整文件名；但不得把 mapping、feature/label、训练和报告揉进一个大脚本，也不得复制既有 runner 后产生两套不兼容 evidence schema。

## 5. 三个核心数据结构

### 5.1 Long timeline manifest（一行一个派生时间线）

```json
{
  "timeline_id": "m4:<song>:v1", "source_song_id": "...", "dataset": "m4",
  "duration_sec": 183.42, "language": "zh", "split": "train",
  "audio": {"path": "...", "content_sha256": "...", "sample_rate": 16000},
  "canonical_units": [{"canonical_unit_id": 0, "text": "...", "start_sec": 0.0, "end_sec": 0.3, "source_segment_id": "...", "source_unit_index": 12}],
  "seams": [{"left_source_segment_id": "...", "right_source_segment_id": "...", "timeline_sec": 59.8, "inserted_silence_sec": 0.0}],
  "construction": {"order_source": "metadata:<field>", "artificial_silence_sec": 0.0}
}
```

验证规则：`duration_sec >= 90`；主 cohort 必须 `>=180`；每个 canonical unit 都有唯一 id；seam 不改变 source split；正常主版本的 inserted silence 为 0。0.5s seam control 是另一条显式记录，且在汇总时可证明 attempt 比例和静音时长比例均 `<0.1`。

### 5.2 Request manifest（一行一次模型调用）

在现有 `AlignmentRequest` 外加入 `window_id`、`timeline_id`、`window_index`、`window_role`、`canonical_mapping_id`、`slot_topology`、`baseline_request_identity` 和 `lineage`。`audio_end_sec - audio_start_sec` 必须等于 60s（最后窗口按既有冻结尾窗规则并显式标注例外）。

`lineage` 至少含 `parent_request_identity`、`text_cursor_before/after`、`time_cursor_before/after`、`commit_state_before`、`commit_decision`、`oracle_reset=false`。真实 serial 下一窗只能从父 evidence 的 trusted/provisional/unresolved 状态读取 cursor；不得重读 GT 来重置。

### 5.3 Canonical mapping（与 evidence 同存）

不要再由 evaluator 通过 `position` 和随机 seed 反推 mapping。每个 request 直接保存：

```json
{
  "input_units": [{"input_index": 7, "text": "...", "role": "retained|inserted|replacement", "canonical_unit_id": 41}],
  "removed_canonical_unit_ids": [42, 43],
  "replaced_canonical_unit_ids": [44],
  "output_row_map": [{"output_row_index": 7, "input_index": 7, "canonical_unit_id": 41}],
  "gap_candidates": [{"gap_id": "g:41:45", "left_canonical_unit_id": 41, "right_canonical_unit_id": 45, "omitted_canonical_unit_ids": [42,43,44], "positive": true}]
}
```

mapping 生成器必须统一服务 extra/missing/replace 和所有 position。replace 同时生成 wrong-output input unit 与 omitted-original gap；100% replace 标为无 retained anchor。mapping 中可以有 GT/mutation 信息，但 feature extractor 必须明确拒绝这些字段。

## 6. 实现细节和关键测试

### 6.1 Timeline、window 与 slot

`timeline.py` 仅接受已审计 source rows。排序键、同版本/歌手检查失败时拒绝构造，不得按文件名排序兜底。音频和 GT 同步拼接后，所有 subsequent GT 时间应加上累计时长；seam 控制要同步平移。生成窗口时固定 60s，沿用已验证 overlap/stride 配置并把其版本写入 manifest。

`slot_planning.py` 接收 canonical queried ids 而不是局部偶然 index，输出严格递增的 local timestamp indices 与 topology（`contiguous|two_regions|three_regions|review|anchors`）。density 主比较先求 100%、stride2/4/8 都命中的 common anchors；每种 stride 轮换 phase，汇总只在同一 common-anchor 集合成对比较。非连续 slot、联合/分别请求必须保留同一个 `comparison_group_id`。

最低单测：排序拒绝、禁止跨 source song 拼接、GT seam 平移、180s 不由静音凑成、60s window、slot 严格单调、两/三区索引、phase 覆盖、common-anchor 相等和不同 density identity 不同。

### 6.2 Evidence、hidden 与缓存

真实 executor 必须在一次 forward 内取得 logits/posterior 和 requested hidden；不得为每个 feature 重新跑模型。先加入 hook adapter：显式保存 model module path、layer、pre/post norm、tensor shape、token position、boundary type、unit id。hook 启用/禁用要在同一 deterministic input 上比较 raw logits top-k、raw geometry、official geometry；容差、比较条数和 hash 写入 `HIDDEN_EXTRACTION_AUDIT.json`。不能建立 token-position 可逆映射时，停止 hidden work，保留 R/O 路线并把 gate 标为失败。

attempt evidence 采用「先写临时同目录文件，再原子 rename」；已有 identity 相同才 cache hit，identity 不同直接新目录而非覆盖。每个 attempt 记录 elapsed、GPU/forward 数（无法取得则 null+reason）、cache hit/miss、异常类型。`--resume` 只跳过 hash 和 schema 都完全相同的项目。

最低单测：identity 对 slot、crop、text、decoder、mapping version 敏感；resume 拒绝 schema/identity drift；fake executor 输出保持旧 schema；hook audit 的比较器能发现一处 logit/row 差异；parent failed 时子请求按策略 recorded unresolved 而非用 GT 继续。

### 6.3 标签、特征与 assessor

先按 `source_song_id` 冻结 train/val/test，所有 timeline、seam、window、mutation、slot view 继承同一 split。保存 `split.json` 后若输入 source 集合变化即拒绝续跑。demo 恒为 `demo`，不参与训练或阈值选择。

unit label 分 raw 与 official 两套：unsafe 当且仅当 identity error、无效/严重逆序时间，或任一边界绝对误差 `>250ms`；trusted 当且仅当 identity 正确、时间有效且两边界都 `<=250ms`。同时输出 100/500ms 敏感性表。gap positive 当且仅当相邻 retained canonical ids 间的 mapping 有 removed/replaced-original ids。deleted count、mutation mask/family、GT identity/error 只准出现在 label/stratification 表，不得进入 feature 列表；训练脚本启动时要 assert 禁止列不存在。

分别导出 `unit_features.jsonl` 与 `gap_features.jsonl`：

- R：entropy/margin/top-k span、raw duration、逆序/零时长、局部速度和跨视图差；
- O：official duration/gap/overlap、repair shift/run、跨视图差；
- H（通过 audit 后）：start/end vector 的 norm/diff/cosine、邻域变化、层间变化、train-only distance；
- gap：左右 unit 的同类特征、左右时间跳变和跨视图差，不含缺失数。

模型顺序固定为 rule baseline → 标准化 logistic（unit 与 gap 分开）→ 显式二阶交互 → 必要时受限浅层模型。每一步均保存 feature list、train-only scaler/PCA/reference、seed、模型 hash 和 val 指标。仅 validation 选择 `high_recall_95`/`high_recall_99` 的最小阈值及两种轻度区间合并规则（无平滑、填一 unit 孔且左右最多扩一 unit）；冻结后才读 test。

`region_metrics.py` 应对每个 target、domain、mutation family 输出：unit recall、correct retained-unit FPR、gap event recall、deleted-GT weighted gap recall、wrong-output recall、replaced-GT omission recall、interval recall@75/@100、>=3-unit 错误区间全漏检率、unsafe 扩张长度、请求数/延迟/unresolved/stall。M4 synthetic-long、MIR natural、demo 分表；至少含 M4 heldout、M4→MIR、family leave-one-out 结果。

## 7. Gate、命令和交付顺序

实现 agent 应按此顺序推进，每项失败都写入 `FAILURES.jsonl` 并停止依赖它的后续阶段：

1. `pytest -q tests/research_v7` 通过后添加 WP0--WP3 单测；
2. 运行 preflight，生成 14 合同要求的全部审计文件和弱人声 calibration packet；若主数据不足 180s，报告实际规模并等待决定；
3. fake smoke：一条 >=180s timeline、三个 60s windows、non-contiguous slot、missing gap、replace 双向 mapping、English/Japanese boundary fixtures；
4. real smoke：一条 M4 长 timeline 和一首 MIR 多窗歌曲；检查 raw/official/hidden audit、lineage 无 oracle reset、cache resume；
5. 小 pilot：生成每 condition runtime p50/p90、forward、cache、实际分母与 formal 预计；若 >10h，按 13 §12.3 缩减并重新冻结 manifest；
6. 只有用户/负责人提供明确的 frozen formal manifest 后，才允许 formal executor 启动；12h 必须硬停，低优先级未启动 cohort 标 `not_run_budget`。

建议命令接口（由 agent 实现，参数名可微调但语义不得变）：

```bash
PYTHONPATH=src python scripts/research_v7/preflight_long_slot_region.py --out-root <run> --seed 3407
PYTHONPATH=src python scripts/research_v7/build_long_timeline_manifest.py --precheck <run>/preflight/PRECHECK.json --out <run>/manifests/long_timeline.jsonl
PYTHONPATH=src python scripts/research_v7/build_long_slot_run_manifest.py --timelines <...jsonl> --out <run>/manifests/smoke.jsonl --mode smoke
PYTHONPATH=src python scripts/research_v7/run_long_slot_smoke.py --manifest <...jsonl> --out-root <run> --resume
PYTHONPATH=src python scripts/research_v7/extract_region_features.py --run-root <run> --out-root <run>/features
PYTHONPATH=src python scripts/research_v7/train_region_assessor.py --features <run>/features --out-root <run>/assessor
PYTHONPATH=src python scripts/research_v7/evaluate_region_assessor.py --run-root <run> --assessor <run>/assessor --out <run>/reports/AUTO_SUMMARY.json
```

## 8. 最终交付清单

除代码和测试外，必须存在且可机器读取：`PRECHECK.json`、`LONG_TIMELINE_MANIFEST.jsonl`、`WINDOW_PLAN.jsonl`、`SEAM_CONTROL_MANIFEST.jsonl`、`HUMAN_REVIEW_AUDIT.json`、`HIDDEN_EXTRACTION_AUDIT.json`、`RUN_MANIFEST.json`、`RUNTIME_BUDGET.json`、`CACHE_AUDIT.json`、`FAILURES.jsonl`、`AUTO_TABLES.csv`、`AUTO_SUMMARY.json` 与 `AUTO_FINDINGS_DRAFT.md`。

交付说明须逐项给出：实际 source-song 分母、被丢弃条件及理由、所有 gate 状态、formal 是否运行、任何未完成的 hidden/人工标签/弱人声阻塞项。不得把缺失字段填成 0 或 success；未知应写 `null` 并附 reason。完成后将 compact evidence 和这份说明交回审查者，由其复核结果并更新科研结论。
