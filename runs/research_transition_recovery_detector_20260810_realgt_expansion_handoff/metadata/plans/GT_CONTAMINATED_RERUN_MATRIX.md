# GT-Contaminated Experiment Rerun Matrix

No old timing number below may be cited as a current conclusion until the stated action completes in this session.

| Priority | Experiment / claim | GT impact | Required action | Safe design / output |
| --- | --- | --- | --- | --- |
| P0 | Research V7 long-slot timing MAE/unsafe-rate, timing seam and timing density conclusions (8/5 onward) | Long timeline constructed character times uniformly within each segment; some outputs explicitly label it non-human, but timing-quality numbers remain non-real-GT | **TRACE then REAGGREGATE/RETIRE** | Write `PRETRANSITION_GT_AUDIT.json`; recompute only accepted real-GT common queried units. Keep virtual-gap/ownership findings in a structural-only appendix. |
| P1 | Detector V2 early `run1` and later M4/family/stress/serial results | Early labels had a separate local-to-global pinyin projection/matching defect; later labeler may be repaired and must not be assumed uniform-GT | **RETIRE early run; TRACE later runs** | Require label SHA, accepted-status/segment-offset/source-index proof and query-set audit. Failed proof means minimal re-label/frozen evaluation rerun. |
| P0 | T1/T2/T3/full-song and serial align quality; route/product selection | Old 100/250/500/1000-ms results used segment-uniform timing | **REAGGREGATE**, or reproduce only missing identity-equivalent predictions | B develops no route from A; A is evaluated once. Write `BASELINE_REALGT_BY_ROUTE.json` with labeled/unlabeled denominators and per-song macro. |
| P0 | Raw detector labels, AUROC, working points | Synthetic labels and historical split/provenance can affect fitting and thresholds | **RERUN** Raw-only | Fit/calibrate on B, lock schema/threshold, evaluate A; report severity/event metrics, not pooled AUC alone. |
| P0 | Oracle and closed-loop recovery benefit/harm | Correctness and retry improvement used wrong GT; historical report conflicts with underlying improved cases | **RERUN** | Oracle GT only selects/scores error windows. Separate before/retry/accepted-writeback outputs and harmful-writeback audit. |
| P1 | Slot/sparse-slot/full-slot/non-slot timing-quality comparison | Timing outcome contaminated; early sparse evaluation also treated intentional unqueried units as missing output | **REAGGREGATE then conditional RERUN** | Compare matched common `query_set` units on accepted real GT; `context_only` is `not_queried`, never Unsafe. Rerun only routes without identity-equivalent predictions. |
| P1 | Serial/transition propagation conclusions using timing failure onset | Error onset and episode success can depend on wrong GT | **TRACE then RERUN/RETIRE** | Trace whether targets are structural-only. If timing enters a target/trigger, rerun with real GT. |
| P1 | Mutation/invalid-input timing degradation and detector capture rates | Mutation construction is valid, but timing degradation/capture labels are contaminated | **REAGGREGATE or RERUN** | Retain construction metadata; evaluate accepted-GT units only and separate expected text-identity effects from timing quality. |
| P2 | H/P/V/S/O/RO feature-family leaderboard | Usually label/threshold affected and not part of the current Raw question | **RETIRE from next-round execution** | Preserve artifacts; do not rebuild unless Raw catastrophic false negatives identify a precise mechanism. |
| P2 | PR propagation predictor | GT dependence of target is not fully traced | **TRACE; KEEP only if structural-only, otherwise RERUN/RETIRE** | No citation or cache reuse until target provenance is recorded. |
| Keep separately | Inline realign mechanics, shadow-writeback safety, deterministic/runtime/ownership tests | Normal execution has no GT input | **KEEP as structural evidence** | Any claim that realign improves timing quality joins the recovery rerun above. |
| Keep separately | R2 training and native-short validation | Uses original M4Singer annotation lineage, not synthetic long timeline | **KEEP, with normal provenance limits** | Do not merge native-short metrics with long-form formal results. |

## Mandatory checks for every rerun

- Every metric table has `canonical_units`, `accepted_real_gt_units`, and `unlabeled_units`; percentages use accepted-real-GT denominator only.
- All comparisons are source-song grouped; formal A is never used for fitting, calibration, threshold choice, case selection, or retry input.
- Reruns record cohort, GT projection SHA, split SHA, prediction/cache identity, code SHA, and environment SHA.
- Failure to trace an old experiment means `PROVENANCE_UNKNOWN` and therefore non-citable, not implicitly valid.
