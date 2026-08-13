# Codex implementation plan — unit-level realign

## Review decision

The current `realign_gate` branch is a sound candidate-level R-U/R-A/R-B
baseline, but is not ready for unit-level sparse claims.  Implement the work
below in a new `src/lyricalign/unit_realign/` package; retain
`realign_gate` as the baseline adapter and do not change its historical
metrics in place.

Implementation findings to address:

1. `gate_features.pair_gt` has canonical unit pairing and start/end error
   fields, but its public schema is v1: it has no explicit offset/max-boundary
   before/after buckets at 1 s and candidate reporting collapses targets with
   conservative any-harm semantics.
2. `RealAligner.align_units(..., slot_indices)` currently forwards
   `timestamp_slot_indices` into the decoder.  The raw-decoder path may
   already preserve non-active slots, but this must be measured on each
   request: there is not yet an explicit fixed-slot/reference-row contract
   or remerge audit that demonstrates it.
3. Test Demo's `to_behavior_suite_manifest` constructs local text correctly,
   but serializes `text_start_index=0` and
   `target_unit_ids=range(start,end)` in a request-local index space. The
   executor/behavior artifacts then lose document-global identity; whole-item
   targets can result when an adapter interprets those IDs globally.

## Package and schemas

Add:

- `unit_outcome.py`: `pair_unit_outcomes(baseline, candidate, gt)` emits
  one row per `(song_id, region_id, request_id, family, canonical_unit_id)`.
  Store old/new onset, offset, max-boundary errors, missing/extra/duplicate,
  target/context role, signed deltas, and booleans at 100/200/500/1000 ms for
  each error. Aggregate candidate outcomes separately by target and context;
  never use unit rows as independent candidate-AUROC samples.
- `region_sampling.py`: builds contiguous 1--8 unit regions from production
  detector spans; records RS/US/AS/BR/BG/BA stratum, song/language, population
  hash, exclusion reason, per-song cap, and refill/exhaustion audit.
- `request_families.py`: typed `UnitRequest` builders for R-NULL, R-U1,
  R-U3, R-A, R-B, R-L, R-R, R-S, and evaluation-only R-O.
- `intervention_check.py`: validates locality, baseline identity difference,
  anchor requirements, sparse active/fixed masks, GT firewall, and request
  digest. Invalid requests become explicit NULL/failed rows and consume no GPU.
- `unit_gate_features.py`, `consensus.py`, and
  `request_sensitivity.py`: no-GT features, per
  `(song,region,canonical_unit)` family consensus, and perturbation/fixed
  point analyses.

All manifests use schema versions and carry `source_song_id`,
`canonical_unit_id`, `region_id`, `index_space=document_global`, and
`request_identity`. `assert_no_label_leak` is applied before writing
no-GT features; R-O and all GT/error keys are rejected from that branch.

## P0/P1 review ledger and acceptance rules

The following records the remaining P0/P1 findings from the review.  They are
implementation and reporting requirements; except for malformed inputs or a
GT-firewall violation, an individual failure is isolated and recorded rather
than stopping the full overnight controller.

### P0 — correctness / identity / leakage

1. **Unit outcome v2 is mandatory.**  Preserve the old candidate-level
   `any-harm` result only as a historical diagnostic.  New formal summaries
   must pair by canonical document-global unit and separately report target
   recovery, target harm, safe-context collateral harm, catastrophic harm,
   and missing/extra coverage at the stated error buckets.
2. **Test Demo local identity is mandatory.**  Each request serializes global
   target IDs, request-local indices, and a bijective local-to-global map.
   A request whose target covers the complete item, or whose maps are
   inconsistent, is a fail-fast `R-NULL` and is not sent to the executor.
3. **R-O remains physically evaluation-only.**  Its GT-derived construction,
   cache/artifact namespace, and outcome files are separate from no-GT
   feature inputs; feature writers reject R-O plus GT/error-derived fields.
4. **Sparse safe-unit invariant follows the agreed non-blocking policy.**
   Use the raw decoder / active-slot route first; audit fixed rows on every
   request.  Drift or ineffective masking becomes
   `SAFE_SLOT_INVARIANT_VIOLATION`, suppresses that request's writeback, and
   triggers adapter repair plus a regression test without stopping unrelated
   screening/expansion work.

### P1 — protocol / fairness / automatic continuation

1. **Selection and confirmation are separated.**  Screening chooses surviving
   families; its outcome rows are marked exploratory.  Expansion includes a
   predeclared song-held-out confirmation population, and production claims
   are based on that confirmation population rather than reusing selected
   screening performance as unbiased evidence.
2. **Region and unit dependence is explicit.**  The sampler prevents a
   canonical target unit entering more than one primary region.  Unit tables
   retain all units but uncertainty and gate generalization use song-clustered
   bootstrap / song holdout, never pseudo-independent unit rows.
3. **Family rules are frozen before real screening.**  The resolved config
   records exact R-U1/R-U3 text-context and audio-margin definitions,
   constructibility rules, minimum valid-intervention coverage, strata
   accounting, and the criteria used to keep or retire a family.  This avoids
   changing a family definition after observing its outcomes.
4. **Constructibility is a result, not a silent filter.**  R-B/R-L/R-R and
   R-S report eligible, constructed, NULL, invariant-violation, and failed
   counts by stratum and song.  Comparisons show both all-case coverage and
   constructible-case behavior; missing anchors never degrade into a no-op.
5. **Test Demo coverage is audited before execution.**  Dynamically report
   discovered/runnable items and detector spans by language, then select
   bounded local regions.  If the 40--60-region target is unattainable, emit
   a language-by-stage exhaustion audit rather than treating a historical
   fixed item count as the population.

## Real sparse execution and safe-unit handling

Do not delete safe text.  Prefer the existing raw-decoder / slot path first:
the local request contains active targets *and* safe context, while its
active-slot mask identifies the units permitted to change.  For every R-S
forward, record the raw decoder output for fixed units and compare it with
the baseline in document-global coordinates.  This is a runtime correctness
invariant, not a precondition that blocks screening or the overnight run.

Extend
`AlignmentRequest` with `active_slot_indices`, `fixed_slot_rows`, and
`slot_constraint_schema=v1` where the decoder exposes an explicit fixed-row
interface. Decode the complete local text span.  In the default raw-decoder
path, first use the native active-slot behavior and validate safe rows; when
available, additionally provide baseline boundaries as fixed references.  In
both cases, re-merge into global coordinates and assert canonical coverage,
order, and fixed-slot start/end equality within the declared decoder
quantization tolerance.

If a fixed unit drifts, disappears, crosses an active unit, or the raw output
shows that the active mask is ineffective, emit a structured
`SAFE_SLOT_INVARIANT_VIOLATION`, do not write back that request, and preserve
the baseline safe rows in the assembled timeline.  The controller continues
with other constructible families/cases and records the failure by decoder,
family, and request shape.  The implementation should then repair the
adapter/constraint mapping and add a regression case; it must not silently
call the result true sparse or fabricate sparse behavior by deleting text.

R-U1/R-U3 use the target plus 0/1 contextual neighbors; R-A uses detector
unsafe span plus configured context; R-B requires nearest bilateral ACCEPT
anchors; R-L/R-R require exactly the respective one-sided anchor and altered
audio/text request; R-O is constructed in an evaluation-only adapter after
no-GT request construction. Every builder includes document-global targets and
both local-to-global maps. Fix Test Demo at
`realign_gate.test_demo.to_behavior_suite_manifest` to serialize global
`target_unit_ids`, a local map, and local `text_start/end_index`; add a
whole-item pseudo-local fail-fast check.

## Execution control

Use content-addressed cache key SHA-256 over family/version, full request
payload, active/fixed slots, baseline reference digest, audio SHA, model and
checkpoint content SHA, decoder options, and mapping schema.
Persist atomic `REQUESTS.jsonl`, `FORWARDS.jsonl`, `FAILURES.jsonl`, and
`RUN_STATE.json`; resume skips only completed matching identities. Retries
are bounded and classified (transient/model/input/contract).

`run_unit_realign.py screen` samples 48 regions (minimum one RS/AS/BR per
available language), runs constructible families, then ranks families only
after valid-intervention coverage, safe-preservation, catastrophic proxy,
runtime, and sparse-invariant accounting. Keep at most four production-capable
families. A sparse invariant failure invalidates that request rather than
blocking the run; persistent failures trigger an adapter repair task and the
family remains diagnostic until repaired. `expand --resume` adaptively refills to 240 regions, prioritizing
RS/AS/BR and least-represented songs; failed/unconstructible requests trigger
replacement sampling until exhaustion is recorded. No hard family-by-region
Cartesian table.

Test Demo is a first-class population: dynamically discover items, run the
production detector, select 40--60 local spans across languages or write
exhaustion audit, then execute baseline/R-U/R-S (when supported)/best-anchor.
Report only detector, consensus, stability, collateral, and provenance
signals—never GT accuracy.

## Tests and commands

Add pure tests for bucket boundaries, missing/extra, global/local mapping,
whole-item rejection, R-B/R-L/R-R identity, R-S active/fixed semantics and
safe-slot invariant violations, R-O firewall, cache-family collision, resume deduplication, sampling refill,
candidate-level aggregation, consensus grouping, and feature leakage.

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
PYTHONPATH=src python -m pytest -q tests/unit_realign tests/realign_gate
PYTHONPATH=src python scripts/unit_realign/run_unit_realign.py smoke --out-root /home/hyan/Data/lyricalign/runs/unit_realign_smoke
PYTHONPATH=src python scripts/unit_realign/run_unit_realign.py screen --out-root /home/hyan/Data/lyricalign/runs/unit_realign_overnight --real --resume
PYTHONPATH=src python scripts/unit_realign/run_unit_realign.py expand --out-root /home/hyan/Data/lyricalign/runs/unit_realign_overnight --real --resume
```

Formal artifacts reside below the supplied data-directory run root:
`00_population`, `01_requests`, `02_forwards`, `03_unit_outcomes`,
`04_no_gt_features`, `05_analysis`, `06_test_demo`, `07_runtime`, and
`FINAL_REPORT.md`. If no reliable no-GT gate survives song holdout, continue
small controlled exploration of posterior/raw-official disagreement, anchor
asymmetry, local score gradient, request-size sensitivity, and ranking
stability; each must have shortcut audit and counterexamples. Stop only after
the predefined and these bounded fallback signal families are exhausted and
recorded as negative results.
