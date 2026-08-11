# 19. Codex-Reviewed Implementation Plan — Safe Real-GT Expansion First

**Status:** implementation handoff for OpenCode. This document does not itself create a run/session.

**Historical-scope addendum:** Document 20 is part of this handoff.  The
lineage audit begins with Research V7 long-timeline construction on 2026-08-05,
not with the first 2026-08-07 Transition report.  Stage 3 is incomplete until
Document 20's Stage 3A inventory and generated rerun manifest exist.

## 1. Verified scope and frozen policy

The existing `long_manifest_60` is an exploratory cache, not a held-out formal
cohort: its source-song roles are 52 R2-train, 3 validation, and 5 test.
It must never be reported as a held-out aggregate.

The 2026-07-23 overlay covers all 419 split songs. Current inventory provides
the following CPU-screened *candidates* with at least 180 seconds of accepted
material:

| role | candidate songs | use |
| --- | ---: | --- |
| R2 test | 11 | Cohort A, strict formal candidate pool |
| R2 validation | 16 | Cohort B, development/calibration candidate pool |
| R2 train | 167 | Cohort D only; never merged into held-out results |

These are candidate counts, not final cohort sizes. OpenCode must materialize
the new long manifest and apply the gates below before freezing any cohort.

### GT acceptance rule

Only these overlay statuses are GT:

```text
accepted_rule_based_pinyin_validated
accepted_rule_validated_held_vowel
```

`review_required_*`, absent records, invalid timestamps, non-monotonic rows,
and rows without both real overlay start/end timestamps are **unlabeled**. They
must not enter a metric denominator, a Safe/Grey/Unsafe label, model fitting,
threshold fitting, selection, or an oracle trigger. No synthetic-uniform
fallback is allowed in this round.

The overlay currently has no timing values for review rows, but filtering by
status must still be explicit so the contract remains true after data updates.

### Cohort gates

For a materialized long song, require all of:

1. source song appears exactly once in the frozen R2 split manifest;
2. role is `test` for Cohort A or `validation` for Cohort B;
3. natural concatenated source duration is at least 180 s before any seam
   operation;
4. usable real-GT coverage is at least 0.90 of canonical units for the primary
   cohort; 0.85--0.90 is diagnostic-only and must be named separately;
5. every projected GT start/end lies within its source segment after applying
   the recorded segment offset, and has `end >= start`;
6. audio, source rows, overlay rows, split row, and generated manifest hashes
   are present.

Use `--seam-silence-sec 0.0` for the primary manifest. Do not insert silence to
reach the duration threshold. The exact post-gate song list is the frozen
cohort; no GT-error or prediction-based inclusion/exclusion is permitted.

## 2. Work order: expansion precedes experiments

OpenCode must create a fresh session only when beginning this work, for example:

```text
runs/research_transition_recovery_detector_20260810_realgt_raw_catastrophic_recovery/
```

Copy Documents 16--19 to `metadata/plans/` and record `git rev-parse HEAD` plus
the dirty diff before writing outputs. Execute stages 1--4 fully before any GPU
inference, detector training, recovery, or catastrophic-case mining.

### Stage 1 — Make GT projection safe

**Problem / reason:** `real_gt.py` currently projects a real overlay start but
uses the synthetic canonical end; it also does not explicitly whitelist status.

**Implementation:**

- Update `src/lyricalign/research_transition_recovery_detector/real_gt.py` to
  retain status and both local overlay boundaries, add the segment offset to
  both, and whitelist only the two accepted statuses.
- Return a structured exclusion audit by song and reason:
  `review_status`, `missing_overlay`, `missing_time`, `bad_interval`,
  `missing_segment_offset`, and `text_or_index_mismatch`.
- Refuse `load_real_gt` callers that request uniform fallback for correctness
  labeling. Keep `load_uniform_gt` only for non-GT construction diagnostics.
- Add unit tests for offset of both boundaries, each excluded status/reason,
  a review row with timestamps, and no synthetic-end leakage.

**Outputs:** `REAL_GT_PROJECTION_AUDIT.json`, a per-song inventory JSONL, and
a SHA-256 manifest. The audit must distinguish all canonical / accepted-GT /
unlabeled counts.

### Stage 2 — Build and freeze cohorts (CPU only)

**Implementation:**

- Add `scripts/research_transition_recovery_detector/build_real_gt_cohorts.py`.
  Inputs: overlay manifest and annotations, R2 split manifest, audio root,
  duration/coverage thresholds, and a role allowlist. It must emit a complete
  inventory before filtering and deterministic Cohort A/B/D candidate lists.
- Extend `scripts/research_v7/build_long_timeline_manifest.py` with an explicit
  `--song-allowlist` JSONL argument. It must reject a source song whose role is
  outside the supplied cohort, and preserve the source/split fields in every
  output row.
- Materialize Cohort A from R2 test and Cohort B from R2 validation, then run
  the Stage-1 projector against each generated long manifest. Remove only
  songs failing pre-registered structural/coverage gates and record the reason.
- Freeze `COHORT_A_FORMAL.jsonl`, `COHORT_B_DEVELOPMENT.jsonl`,
  `COHORT_D_TRAIN_OVERLAP_DIAGNOSTIC.jsonl`, `EXCLUSION_LOG.jsonl`,
  `SPLIT_AUDIT.json`, and `FREEZE.json` with input and output hashes.

**Required checks:** no song in both A and B; no train song in A/B; source-song
identity is retained after concatenation; all primary songs meet the 0.90
coverage gate; no `review_required_*` unit enters a GT table.

### Stage 3 — Manifest and cache audit (CPU only)

**Implementation:**

- Add `scripts/research_transition_recovery_detector/audit_realgt_inputs.py`.
  It joins cohort, long-manifest, real-GT, historical request/cache metadata,
  and R2 checkpoint identity.
- Mark each historical cache `reusable`, `reusable_for_diagnostic_only`, or
  `not_reusable`; reuse only when model/checkpoint, audio SHA, request schema,
  text, mapping, code version, and environment identity match.
- Do not use the 60-song aggregate or its cached metrics as a formal baseline.

**Outputs:** `INPUT_PROVENANCE_AUDIT.json`, `CACHE_REUSE_PLAN.json`,
`HISTORICAL_GT_LINEAGE.csv`. Required historical decisions: Transition timing
metrics = REAGGREGATE where predictions are identity-equivalent; old
correctness-detector training = RERUN; historical recovery effectiveness =
RERUN; H/P/V/S expansion = RETIRE as next-round priority.

Also run Document 20 Stage 3A.  It is mandatory to classify the pre-Transition
Research V7 long-slot timing results and Detector V2's separate pinyin
local-to-global label lineage.  Do not silently treat all Detector V2 output as
uniform-GT-contaminated: prove the axis per artifact.

### Historical GT-lineage decisions: current verified state

The following is the pre-execution Codex audit status. `CONFIRMED` means the
claim was traced to code and/or a versioned artifact; `PENDING_TRACE` means
OpenCode must not cite or reuse the quantitative result until Stage 3 writes
the specified evidence.

| historical group | status / action | verified evidence and required implementation action |
| --- | --- | --- |
| T1/T2/T3/full-song timing comparison and candidate selection | **CONFIRMED — REAGGREGATE** | `research_v7/timeline.py` constructs the old canonical times as `duration / len(units)`; the stored Transition artifacts consume that axis. Reuse only identity-equivalent predictions and recompute every 100/250/500/1000-ms metric with accepted real GT and labeled/unlabeled denominators. |
| 2026-08-09 second-supplement 9-song real-GT binding | **CONFIRMED, but REPORT-ONLY / reaggregate before citation** | Versioned binding counts are 3093/97/38 (=3228 labeled) with 3374 total. Its summary also calculates a percentage using 3374, so new reports must recompute from the row-level binding and state 146 unlabeled. |
| historical detector models trained or thresholded on old correctness labels | **CONFIRMED — RERUN if retained** | Old synthetic-GT labels affect fitting/threshold selection; metric-only relabeling cannot repair a trained model. Implement Raw-only fit/calibration on B and one locked evaluation on A. |
| reported Raw `0.976` result | **PENDING_TRACE — diagnostic only** | The stored report establishes the value but not a clean R2-disjoint evaluation/provenance chain; do not call it formal or reuse its threshold. New Raw output must use the frozen B->A chain. |
| closed-loop / oracle recovery effectiveness | **CONFIRMED — RERUN** | `SECOND_SUPPLEMENT_REPORT` states zero improvements while its versioned decomposition records 3 accepted and 2 blocked retry improvements. The outcome is internally inconsistent and requires real-GT oracle capability rerun, then detector-triggered rerun. |
| propagation / PR | **PENDING_TRACE — no reuse** | Trace whether its targets consumed timing correctness or only structural injected state. Until the generated lineage table proves this, do not cite the PR AUC or reuse its model. |
| slot/sparse-slot and mutation timing-quality conclusions | **PENDING_TRACE — no reuse** | Structural construction/ownership checks can remain diagnostic, but any timing-quality conclusion needs GT-path tracing and then reaggregation or rerun according to whether GT changed execution. |
| H/P/V/S/O/RO feature expansion | **CONFIRMED — RETIRE as next-round priority** | It is not part of the Raw-only research question. Preserve artifacts, but do not spend the expansion run rebuilding them unless catastrophic Raw analysis identifies a precise blind spot. |

`HISTORICAL_GT_LINEAGE.csv` must include an artifact path/hash and code entry
point for every row above. A PENDING_TRACE result is not a failure of the
expansion stage, but it is a hard prohibition on presenting that historical
number as a confirmed conclusion.

### Stage 4 — Tests and stop gate

Run:

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
PYTHONPATH=src python -m pytest -q tests/research_transition_recovery_detector tests/research_v7/test_research_v7_long_timeline_builder.py
python -m compileall -q src scripts
git diff --check
```

OpenCode must stop before inference if any freeze hash is absent, a formal song
has train overlap, coverage is below the frozen gate, GT rows are not wholly
accepted-status overlay timings, or an unlabeled row has received a label.

## 3. Only after expansion: experiment sequence

1. **A: baseline reaggregation.** Run T1/T2/T3/full-song only for frozen A/B
   requests (reuse verified predictions, otherwise reproduce). Report labeled
   and unlabeled denominators separately; no model/route selection from A.
2. **B/C: Raw-only severity and catastrophic decomposition.** Fit/calibrate R
   on B only; evaluate A once. Pre-register error bins and event definitions
   from Document 17. Mine catastrophic cases only after these predictions and
   scores are frozen.
3. **D: recovery capability.** Oracle selection may use real GT only to choose
   and score wrong windows; the recovery backend, policies, and writeback never
   receive GT. Keep before/retry/accepted-writeback outputs separate, immutable,
   and transaction-audited.
4. **E: detector-triggered recovery.** Run only if D shows actual capability;
   evaluate clean-window harm, harmful writeback, and catastrophic event recall.

Formal A results are reported once, after all frozen requests finish. Cohort D
may be useful for failure discovery but must never be pooled with A/B.

## 4. Runtime and resume policy

Stages 1--4 are CPU-only and should complete before GPU reservation. Their
runtime is expected to be minutes plus filesystem hashing. Baseline/recovery GPU
work remains under the project formal ceiling (target <=10h, hard <=12h); the
run planner must project requests from the frozen A/B manifests before launching.
Each stage writes atomically, records a completion marker and input hashes, and
resumes only if all identities match. A changed input creates a new output path;
never overwrite a previous aggregate or silently reuse a cache.

## 5. Material deviations from Documents 14--18

- The verified maximum strict candidate pool is 11 test songs, not the existing
  five-song subset; its final size is contingent on post-materialization gates.
- The 60-song / 20k+ result is training-overlap-heavy and has no independently
  recoverable all-song metric artifact, so it is diagnostic only.
- The historical 9-song report has a denominator inconsistency: 3093+97+38 =
  3228 labeled units, while one report also states 3374 total. All new output
  must carry both values and never calculate labeled accuracy with 3374.
