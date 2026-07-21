# Qwen Raw Baseline v1

The Qwen forced aligner ran successfully on all 7 frozen M4Singer native-short validation records and all 17 MIR-1K natural-long OOD records.  The M4Singer character metric result is recorded in the run summary.

MIR-1K structural output is not a valid metric input: the raw predictions contain 410 zero-duration and 47 near-zero-duration character intervals.  The strict evaluator correctly hard-failed rather than filtering or interpolating these timestamps.  This is a model diagnostic and does not change data quality tiers, the frozen OOD role, or any alignment rule.

Synthetic-long has no raw result because no valid synthetic-long source exists under the current A-tier invariants.
