# OpenCode Execution Brief — Expand Before Experimenting

## Objective

First organize, materialize, audit, and freeze a clean real-GT dataset in this session. Only then execute the P0 reruns. Do not create another output root and do not add records to previous sessions.

## Phase 0 — Session registration (CPU only)

1. Copy Documents 16--20 from the archived docs directory into `metadata/plans/source_documents/`, preserving SHA-256 values.
2. Write `metadata/SESSION_MANIFEST.json` with git HEAD, dirty diff SHA-256, environment identity, absolute source paths, and input hashes.
3. Create atomic, append-only logs in `logs/`; do not overwrite aggregates.

## Phase 1 — Safe GT implementation and inventory (CPU only)

- `real_gt.py` must whitelist `accepted_rule_based_pinyin_validated` and `accepted_rule_validated_held_vowel` only.
- Project both overlay `start_sec` and `end_sec` with recorded segment offsets. Never use a synthetic canonical endpoint as real GT.
- Return exclusions: review status, missing overlay, missing time, bad interval, missing offset, and text/index mismatch.
- Add tests for multi-segment offsets, later windows, repeated text, sparse query sets, review rows carrying timestamps, and synthetic-fallback refusal.

Generate `metadata/lineage/REAL_GT_PROJECTION_AUDIT.json` and a per-song JSONL inventory. A row missing accepted status or valid real boundaries is unlabeled and excluded from every correctness denominator.

## Phase 2 — Expand and freeze cohorts (CPU only)

Generate deterministic source-song inventory and materialize long manifests using a role allowlist and `--seam-silence-sec 0.0`.

- Cohort A formal candidate pool: 11 R2-test songs with >=180 s accepted source material.
- Cohort B development candidate pool: 16 R2-validation songs with >=180 s accepted source material.
- Cohort D: R2-train diagnostic only; never merge it with A/B.

Final A/B inclusion requires: known unique source-song role; natural duration >=180 s before seams; accepted real-GT canonical coverage >=0.90; complete audio/source/overlay/split/manifest hashes; and no cross-cohort song. Preserve 0.85--0.90 songs only in a named diagnostic manifest.

Freeze `COHORT_A_FORMAL.jsonl`, `COHORT_B_DEVELOPMENT.jsonl`, `COHORT_D_DIAGNOSTIC.jsonl`, `EXCLUSION_LOG.jsonl`, `SPLIT_AUDIT.json`, and `FREEZE.json` under `metadata/lineage/` before model work.

## Phase 3 — Provenance and cache audit (CPU only)

Write `HISTORICAL_GT_LINEAGE.csv` and `CACHE_REUSE_PLAN.json`. Run Document 20's exhaustive pre-Transition scan and emit `PRETRANSITION_GT_AUDIT.json` plus `HISTORICAL_RERUN_MANIFEST.json`. A historical prediction is reusable only when checkpoint, audio SHA, text, request/mapping schema, code version, and environment identity all match. The previous 60-song aggregate is diagnostic-only because 52/60 songs overlap R2 train.

## Phase 4 — P0 execution after freeze

1. Reaggregate or reproduce T1/T2/T3/full-song on B for development and A once for formal evaluation; report labeled and unlabeled counts.
2. Fit/calibrate Raw-only detector on B; lock it; evaluate it on A. Do not use GT or A to choose a threshold.
3. Run recovery capability with GT only as oracle selector/evaluator of pre-existing wrong windows; never pass GT to retry or writeback policy.
4. Run detector-triggered recovery only when oracle capability has succeeded.

Run Document 19's test suite and stop if any Phase 1--3 gate fails.
