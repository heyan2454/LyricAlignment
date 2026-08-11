# 20. Pre-Transition GT Lineage Audit and Rerun Plan

**Status:** Codex audit supplement. This document extends Documents 16--19
back to the creation of the long timeline; it does not authorize a GPU run
before the cohort/projection gates in Document 19 pass.

## 1. Audited finding: two GT defects must not be conflated

### 1.1 Synthetic-uniform timing axis

Commit `09a7357` (2026-08-05 00:05 +08) introduced
`research_v7/timeline.py::build_timeline`.  For each source segment it writes
the canonical start/end as `segment_duration / len(segment_characters)`.  This
is a useful construction clock, but not sung-character timing GT.

`evaluate_long_slot_gt.py` already calls that axis
`synthetic_uniform_timeline_axis (not human GT)`.  The first verified misuse as
a *correctness* GT is commit `1caf32f` (2026-08-07 23:51 +08):
`run_transition_formal.py::load_gt()` passes `canonical_units.start/end` to
the Transition formal metric, candidate selection and later error records.

### 1.2 Detector V2's separate local-to-global GT bug

Early Detector V2 did not use the uniform axis as its intended label source.
It consumed M4Singer pinyin timestamps, but its pre-`42522c3` implementation
failed to project segment-local times onto the concatenated long-song clock and
could greedily bind repeated characters to the wrong occurrence.  `42522c3`
(2026-08-06 02:18 +08) changed the labeler to use
`source_segment_id/source_unit_index + segment_offsets.global_start_sec` and
regenerated the M4 labels.  This is a real GT-lineage defect, but it is not
evidence that every Detector V2 result used the synthetic-uniform axis.

The inventory must record these axes separately:

```text
U = synthetic-uniform construction clock
P = accepted pinyin/slur overlay projected to global clock
G = pre-42522c3 local-to-global pinyin projection defect
```

## 2. Verified historical inventory and actions

| period / artifact family | actual GT use | finding | action | reusable work |
| --- | --- | --- | --- | --- |
| Research V7 long-slot `GT_EVAL`, `BASELINE_QUALITY_ANALYSIS`, timing MAE/unsafe-rate and timing seam/density comparisons | U | Boundary-quality numbers are not real alignment accuracy. | **REAGGREGATE** on P where identity-equivalent predictions and canonical mapping survive; otherwise **RETIRE** the timing conclusion. | Forward rows may be reused only after cache identity audit. |
| Research V7 missing/replace/extra virtual-gap, ownership, common-query coverage, mutation construction | mutation/structural, not U timing | These measure known construction/coverage rather than sung timing. | **KEEP structural only.** Any accompanying MAE/unsafe or “alignment improves” statement follows the preceding row. | Existing records usable if identity-equivalent. |
| Detector V2 `run1` labels, fitted model, frozen thresholds and evaluations before `42522c3` | P with G defect | Labels are coordinate/mapping-corrupted; review 22 records 91.4% unsafe before repair. | **RETIRE**; do not reaggregate a fitted model. | No model/threshold/cache may be reused as a scientific result. |
| Detector V2 regenerated labels and Phase B--D M4 held-out/family-LOO/stress/serial; M4->MIR | P, subject to artifact proof | Current labeler uses accepted pinyin statuses and offsets, not U. The final run must prove it used post-fix labels and hashes. | **KEEP only after TRACE**; otherwise **PROVENANCE_UNKNOWN / non-citable**, then minimally re-label/re-evaluate without refitting unless label artifact is pre-fix. | Feature evidence can be reused only with label/run SHA and source-map audit. |
| Transition 8/7 original and 8/8 corrected/reaggregated T0/T1/T2/T3/full-song, route/product selection | U | Formal correctness, pairwise deltas and selection use U. | **REAGGREGATE** all tolerances on P; reproduce only missing identity-equivalent predictions. | Rows/predictions conditionally reusable. |
| Natural propagation/episode taxonomy and PR target/model | U-derived error onset or target | `error_sec`, `correct`, occurrence jump and subsequent risk may be U-defined. | **RERUN** episode extraction and PR evaluation on P if the target will be cited; otherwise **RETIRE** PR result. | Structural injected-state-only analyses may be kept separately. |
| Oracle recovery, closed-loop recovery, retry/writeback and clean-harm conclusions | U selected/scored wrong windows; detector was trained/thresholded on U | Both the case mix and success/harm result are affected. | **RERUN** oracle capability first, then detector-triggered loop after Raw lock. | Do not reuse triggers, threshold or old recovery rate. |
| 8/9 first supplement: raw/official comparison, detector v2/v3/v4 labels, intervals, sequence model, signal ablations | U labels/working points, except explicitly rebuilt 8/10 rows | Any fit, threshold or interval based on U cannot be repaired by changing only reporting. | **RERUN Raw-only**; **RETIRE** H/P/V/S/O/RO and sequence leaderboard unless Raw audit creates a precise dependency. | Raw feature/prediction evidence may be reused; fitted outputs not. |
| 8/9 PR and recovery decomposition | U for target or before/after in the original chain | PR provenance and recovery capability are not citable. | **RERUN/RETIRE** as above. | No old quantitative conclusion reusable. |
| 8/10 real-GT second supplement | P attempted, but current projection copies U canonical end and report mixes total/labeled denominator | Not U contamination, but not final real-GT evidence. | **REAGGREGATE after Stage 1**; no threshold/model/report value is final until both boundaries and denominators are repaired. | Row-level predictions may be reusable if identity-equivalent. |

## 3. Required implementation additions

### Stage 3A -- exhaustive historical scanner (CPU)

Add `scripts/research_transition_recovery_detector/audit_historical_gt_lineage.py`.
It must scan, rather than rely on report prose:

1. every `runs/research_v7_align_behavior/**/{GT_EVAL,LABELS,LABEL_SUMMARY,ASSESSOR,BASELINE_QUALITY}*` artifact;
2. every `runs/research_transition_recovery_detector_20260807/**` and
   `research_transition_recovery_detector_20260808_corrected/**` transition,
   propagation, detector, oracle and closed-loop artifact;
3. both 2026-08-09 supplement run roots and all report input paths;
4. the 2026-08-10 real-GT binding/rebuild artifacts.

For each discovered result write one JSONL/CSV row with: artifact path/SHA,
producing commit/code entrypoint, prediction SHA, GT axis (`U`/`P`/`G`/none),
GT start and end source, label/metric/selection/trigger/recovery use,
upstream fitted threshold/model identity, source-song split, and the action in
Section 2.  Missing evidence is `PROVENANCE_UNKNOWN`, never `KEEP`.

Outputs under the fresh session:

```text
metadata/lineage/HISTORICAL_GT_LINEAGE.csv
metadata/lineage/HISTORICAL_GT_LINEAGE.jsonl
metadata/lineage/PRETRANSITION_GT_AUDIT.json
metadata/lineage/HISTORICAL_RERUN_MANIFEST.json
```

`PRETRANSITION_GT_AUDIT.json` must assert that every category in Section 2 has
at least one classified artifact or an explicit `no_artifact_found` record.
No report is final while an U/G load-bearing row is unresolved.

### Stage 3B -- Research V7 timing reaggregation (CPU, then conditional GPU)

Add `scripts/research_v7/reaggregate_long_slot_real_gt.py`.
It must take a frozen Cohort A/B manifest, accepted overlay projection, and an
identity-verified historical `GT_EVAL`/row stream; join only common queried,
accepted-GT units; and write per-request, per-song and macro summaries for
start/end MAE plus 100/250/500/1000-ms thresholds.  It must report
`canonical_units`, `accepted_real_gt_units`, `unlabeled_units`, and
`context_only_not_queried` separately.

Never re-use the old `GT_EVAL` metric as a denominator.  If its row-level
prediction identity or canonical mapping is unavailable, add that route to the
GPU portion of `HISTORICAL_RERUN_MANIFEST.json`; otherwise this is CPU-only.
Virtual-gap/ownership outputs are copied to a separately named structural
appendix and must not receive timing labels.

### Stage 3C -- Detector V2 proof gate (CPU)

Before retaining post-`42522c3` Detector V2 results, add an audit test/command
that verifies each `LABEL_SUMMARY` points to a post-fix label artifact whose
rows use accepted pinyin statuses, segment offsets, source id/index mapping,
and an explicit query set.  A failed proof retires the model/threshold and
creates a minimal relabel -> frozen-evaluation rerun.  This check prevents the
separate G defect from being misreported as U contamination.

## 4. Execution order and completion gates

1. Run Document 19 Stages 1--3, including repaired real-GT projection.
2. Run Stage 3A and freeze the exhaustive lineage/rerun manifest.
3. CPU reaggregate eligible Research V7/Transition artifacts and publish no old
   timing result until corresponding P output exists.
4. Execute Document 19 P0: Transition baseline, Raw-only B->A, and recovery.
5. Execute only manifest-selected P1/P2 historical reruns; retire any result
   outside the next research direction rather than silently preserving it.

The session cannot be marked complete if a historical U/G row supports a
current alignment-quality, detector, threshold, route, propagation or recovery
claim and remains `PROVENANCE_UNKNOWN`.
