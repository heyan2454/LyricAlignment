# AI Session Entry

## Read in this order

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/status/known_issues_20260724.md`
4. `docs/sessions/20260724_qwen_fa_followup_repair_archive.md`
5. `reports/review/20260724_qwen_fa_followup_repair_review.md`
6. `docs/status/next_execution_plan.md`
7. `docs/principles.md`

## Current stage

```text
first Qwen FA LoRA cycle complete and archived
-> isolate approximately-150-second collapse
-> decide chunked inference versus local-data/label diagnosis
```

## Canonical facts

- R0/R1/R2 and two complete R2 seeds are available;
- missing seed3407 OOD and seed2 test/OOD evaluations completed with rc=0;
- seed2 checkpoint selection remained step750 after terminal step1110 validation;
- metric schema v3 fixes valid-only, missing/invalid, and coverage semantics;
- nineteen result sets were recomputed without changing the primary metric;
- R2 long-context regression is dominated by one late-sequence collapse;
- checkpoints, audio, and large predictions remain external.

## Constraints

- checkpoint selection stays validation-only;
- never overwrite original result evidence with corrected aggregates;
- use corrected v3 files for auxiliary-metric interpretation;
- do not call synthetic 152.5-second data a natural three-minute benchmark;
- do not expand LoRA scope before the dominant long-context failure is isolated;
- treat `rule_validated` M4Singer boundaries as weak supervision, not manual GT.

## Canonical outputs

```text
results/comparisons/20260724_qwen_fa_followup_final_summary.json
results/recomputed/20260724_character_metrics_v3/
reports/progress/20260724_qwen_fa_overnight_overall_summary.md
reports/audits/20260724_qwen_fa_long_b180_outlier_audit.md
```
