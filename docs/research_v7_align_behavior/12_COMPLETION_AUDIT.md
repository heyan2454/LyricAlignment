# research_v7 完成审计

**审计日期：2026-08-04。** 本文件区分已由当前 artifact 证明的项目和仍未完成/不可证明项目；不将大量真实 runs 视作自动完成全部计划。

16 个正式/对照 run 的内容寻址索引已冻结于 `/root/autodl-tmp/AST_storage/Data/lyricalign/runs/research_v7_align_behavior/research_v7_provenance_index_20260804_v9.json`（SHA256 `d92da5ff47ab72939c0957cdbd9e1f00bd85ac00ee285dd5cb7bce886f9ed18a`，2,269 条 collection records）。索引记录 manifest/freeze 的实际文件名与 SHA256，避免 workflow 旧命名被误判为缺失；并记录 source-song coverage、C10 multi-answer、recovery、GT diagnostics、internal separation 与 blinded review artifacts。

| 计划要求 | 当前状态 | 直接证据 |
| --- | --- | --- |
| A1 E1 item/source-song 修复 | 完成 | `stageA_revalidated_20260803/`、E1 bootstrap 输出 |
| A2 E5 paired | 不可验证，已冻结 | 原 artifact 缺 fixed baseline；拒绝用 dynamic 替代，见 execution log |
| A3 E6 paired | 完成 | 11,988 paired 输出 |
| A4 分母审计 | 部分完成 | historical compact artifact 无 lifecycle attempted/completed；缺失已显式保留 |
| C1–C6 percentage curve | 完成（M4 19-song strata、MIR 4-song slice） | 1,178 + 268 real attempts，frozen manifests/collections |
| strict cross-song no-match | 完成 | frozen donor manifests：跨 song、连续、LCS + bigram 阈值 |
| C6 reorder/random/wrong-language | 完成 | 19-song / 76 real controls |
| C6 same-song wrong section | 完成（同歌多 segment 派生） | 19-song / 38 real attempts；donor segment provenance |
| C6 accompaniment-only + real lyrics | 完成（demo 无 GT） | 35 real accompaniment controls + review bundle；不可作 GT accuracy |
| C6 pure instrumental formal GT control | 完成（MIR heldout 4/4） | 发现并使用与正式 vocal target 同目录的真实 `accompaniment.wav`；4 paired items / 8 real attempts，macro ΔMAE `+23.46764s`，bootstrap `[+15.13557,+37.18049]s` |
| C6 low-vocal-energy review control | 完成（无 GT 候选） | 35 demo real attempts + RMS provenance/review bundle；非 formal pure-instrumental claim |
| C7–C9 audio range | 完成（M4 19-song strata） | 190 real attempts，full source ranges |
| C10 repeated/multisolution | 完成（可用 formal 重复母集 + demo review） | MIR heldout 3/4 存在真实重复段、6 次完整 WAV real attempts，按 multiple legal GT locations 评分；另有 33 demo / 66 no-GT review。M4 test 无可用非重叠重复 n-gram，未伪造样本 |
| P0/P1/P2/D/S | 完成（MIR 4-song slice） | stateful P1 36 runs；S 实际 sparse slots；workflow evaluator |
| 错误输入后的 recovery propagation | 完成（MIR heldout 4/4） | 16 real attempts：正确 prefix → 反序错误 prefix → 正确 prefix；恢复尾段相对 P0 同窗口均 ΔMAE `0.0s`，结论限于当前无跨调用隐状态实现 |
| cursor ±2/4/8 | 完成（MIR 4-song 80-unit slice） | 100 real attempts |
| provisional 8/16/10s | 完成（同 slice） | 76 real attempts，actual slot masks |
| raw/official/top-K/weighted/repair | 新 evidence 完成；历史 evidence 不齐 | top-16 weighted contract case；旧 top-8/weighted unavailable 保留 |
| threshold localization / geometry / repair diagnostics | 完成（M4 + MIR formal curves） | `gt_evidence_diagnostics.json`：0.25/0.5/1/2/5s、near-zero、gap/overlap、posterior 与 repair 汇总；只对可验证 GT 匹配单元报告 |
| 可区分内部信号 | 完成（诊断级，不是 QualityAssessor） | `internal_signal_separation.json` 在 M4/MIR 的 request-level entropy/margin 均可区分 baseline 与 invalid mutations；AUROC 已冻结 |
| no-GT data/review | 完成 | 35 demo / 140 attempts + 66 C10 cases/review bundles |
| human blind labels/errors-min | 待外部人工填写；盲审交付完成 | 140 demo + 66 C10 的 blinded packets 不含 mutation type，decode key 隔离；字段含 taxonomy、errors/min、longest error、unresolved，但无人类填写结果 |
| full source-song population coverage | 完成（source-song 层） | `source_song_coverage.json` 证明 M4 test 19/19 source song、MIR heldout 4/4 source song 均被最长可用代表覆盖；不等同于 839 个相邻 M4 segment 的逐段全量推理 |
| final decision/report | 部分完成 | `11_STAGE_B_FORMAL_REPORT.md`；自动化实验闭环已完成，仍缺人类盲审标签/错误时长指标 |

## 结论

当前阶段已经形成可重放的生产型行为证据体系和明确的负/稳定观察，但尚不能宣称“既定计划全部完成”。尤其不能用无 GT demo 代替人工指标，或把同歌错段/纯器乐空缺改称 cross-song no-match。
