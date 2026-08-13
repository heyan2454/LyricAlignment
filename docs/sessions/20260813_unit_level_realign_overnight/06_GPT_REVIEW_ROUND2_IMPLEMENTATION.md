# GPT review round 2 — implementation update

## Resolved P0 findings

1. Formal evaluator no longer binds canonical IDs by decoded-row enumeration.
   It uses decoder-emitted request-local indices and the request-local map.
   Unmappable decoder outputs are retained as `extra/invalid_unpairable` rather
   than dropped.
2. Production detector population contains zero-length and inverted baseline
   intervals. Population records preserve them for audit but mark them
   `baseline_available=false`; evaluator stratification emits
   `ineligible_invalid_baseline_interval`, so they cannot enter S1--S4.
3. R-B requires explicit ACCEPT-anchor candidate provenance and rejects an
   anchor that is not the nearest eligible left/right anchor.
4. Request identity now covers the actual local text content as well as its
   canonical IDs, preventing changed lyrics from reusing a stale forward.
5. Refill preserves prior selected cases even without `--resume`; all writes
   publish atomically to avoid a half-written controller state after an
   interruption.
6. Family screening now counts only explicit `status=valid` P1 records and
   reports selected/not-constructible/null/failed/invalid/executed/valid
   denominators per `(family, stratum)`. A historical manifest without a
   status field keeps the narrow legacy `effective_intervention=true` adapter.

## Read-only production-population audit

Input: `BASELINE_DETECTOR_SHADOW.jsonl` from the frozen production detector.

- 40 shadow windows produced 8,694 population rows.
- 1,091 unsafe-span rows have invalid baseline geometry and are now excluded
  from formal strata, rather than silently counted as baseline-valid.

This is a data-quality eligibility result, not a detector or decoder change.
All formal execution remains shadow-only and `writeback_gate=NOT_FROZEN`.
