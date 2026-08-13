# Realign Gate 重构实施方案（审查后）

## 结论与门槛

当前 `realign_gate` 不可进入 formal：它以整窗分层、允许无锚点 R-B、把 GT `delta_error_ms` 用作 writeback gate，且 Demo 只生成计划而未执行 realign。以下重构以 region/candidate 为主实体；GT 只在 evaluator side 的 outcome 表出现；所有正式 writeback 固定为 shadow-only。

## 实施地图

| 阶段 | 代码/产物 | 完成门槛 |
|---|---|---|
| P0 | `detector_audit.py`：`extract_region_cases`、GT-conditioned 指标；`REGION_POOL.jsonl` | 生产 baseline 的连续 unsafe 与 ACCEPT controls 均可追溯到 `(song, window, cid)` |
| P1 | `case_selection.py`：自适应 sampler、R-U/R-A/R-B/R-NULL、identity checks | S2>=20、S3>=20 或 `EXHAUSTION_AUDIT.json`；R-B 必有两个 anchor |
| P2 | `gate_features.py`：candidate 表、no-GT signal 与 song holdout | feature 表不含 GT/error/delta；无 `ACCEPT_WRITEBACK` recommendation |
| P3 | `test_demo.py`、CLI：formal fail-fast、真实 executor adapter | 全量真实 detector，subset 真 forward；plan 与 behavior 分离 |
| P4 | 报告/可视化与 run manifest | paired R-A/R-B completeness、actual_writeback=0、失败可 resume |

## Region schema 与采样

`REGION_POOL.jsonl` 每行：`region_case_id, song_id, window_id, window_index, target_unit_ids, seed_kind, detector_state, detector_interval_sec, left_anchor_candidates, right_anchor_candidates, baseline_identity, gt_summary`。`gt_summary` 只在 evaluator-side companion 文件，forward manifest 不携带它。unsafe region 是连续 `UNCERTAIN|REJECT` unit span，可把时距 <=0.25s 的相邻 span 合并，长度大于 8 unit 时切块；ACCEPT control 以同 song、相近 unit 长度/时间位置采样。GT strata 用 region target errors：all/90% <=200ms 为 correct，任一 >1000ms 为 bad，中间为 `SG`，永不静默丢弃。

采样初始 song cap=4、每 stratum/song=2，总 cap=80；优先跨歌填 S2=20、S3=20，继而 S1=10--16 与自然 S4。未满足时扫描全部歌/窗口，再把每歌 cap 递增至 8，最后写 exhaustion audit（每步 remaining/reason）；不允许直接 `insufficient`。

## Requests、公平性与缓存

R-U 为 target 加每侧 1--2 safe unit、小 audio margin；R-A 为该 seed unsafe interval 加有限 context；R-B 在同一 window 以 unit-distance 2→4→8→16→全窗搜索左右 ACCEPT anchors，audio 真正由 anchors 夹定。任一 anchor 缺失写 `R-NULL`（只作 deterministic diagnostic），该 case 重抽，绝不作为 R-B。`effective_intervention` 要求双 anchor（R-B）及 `(audio range,text cid list)` 相比 baseline 不同；同 case 的 R-U/R-A/R-B 共用 original/targets/model/decoder 和 `pairing_key=(song_id,region_case_id,baseline_identity)`。缺 R-A 或 genuine R-B 禁止进入 R-A-vs-R-B 主比较。

forward cache key 是 source-audio SHA、audio span、ordered canonical text ids/text SHA、model/checkpoint/revision、decoder/context/schema/code identity；没有 GT、detector threshold 或 recommendation 字段。每 candidate 原子落盘，`--resume` 仅复用相同 identity。

## Candidate gate

candidate-level no-GT 表只含 locality/collateral displacement、target/context detector risk and entropy/margin deltas、coverage/missing/extra、structural anomalies、anchor safety、family consensus、`n_big`、限定 ambiguous subset 的 second-pass stability。缺失值显式 `null` + reason，不能用零代替。GT `delta_error_ms`、label 仅在独立 outcome 表，join 后只用于离线 AUROC/risk-coverage 评价；任何结果只能是 `DIAGNOSTIC_ONLY`/`NOT_READY`，不得产生 writeback decision。按 song split，报告 candidate count/CI，并检查 no-op、song ID、request-size shortcut。

## Test Demo 与实验

formal CLI 需 `--formal --gpu`，拒绝 `adapter=mock`。动态发现全量 item 后跑真实 detector；跨语言选 12--20 regions，真跑 R-U/R-B（可加 R-A），产出 baseline/candidate evidence、per-language summary、top suspicious/stable/counterexample 和可视化索引。Demo 不使用 GT，不报告正确率。

CPU smoke：`PYTHONPATH=src pytest -q tests/realign_gate`；GPU smoke：2--4 regions × R-U/R-A/R-B；formal 先满足 P0/P1，再最多 80 GT candidates、Demo 20 regions，soft 4--6h/hard 8h。每阶段输出 CONFIG/input hashes/RUN_MANIFEST/FAILURES/SAMPLE_ACCOUNTING；任一 firewall、identity、pair completeness 或 mock-formal 失败即停止后续 formal。
