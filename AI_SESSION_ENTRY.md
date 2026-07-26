# AI Session Entry

## Read in this order

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/manual/qwen_fa_batch_demo.md`
4. `docs/sessions/20260726_demo_v2_failure_diagnostics_and_pack_repair.md`
5. `docs/sessions/20260726_demo_exploration_archive.md`
6. `docs/status/known_issues_20260724.md`
7. `docs/status/next_execution_plan.md`
8. `docs/principles.md`

## Current stage

```text
first Qwen FA LoRA cycle complete and archived
-> current focus: reusable multilingual demo
-> validate hard_core_forward_overlap_compression_v6 on real Cantonese/Japanese songs
```

## Canonical facts

- R0/R1/R2 and two complete R2 seeds are available;
- missing seed3407 OOD and seed2 test/OOD evaluations completed with rc=0;
- seed2 checkpoint selection remained step750 after terminal step1110 validation;
- metric schema v3 fixes valid-only, missing/invalid, and coverage semantics;
- nineteen result sets were recomputed without changing the primary metric;
- R2 long-context regression is dominated by one late-sequence collapse;
- failed demo alignment now preserves `alignment.progress.json` and
  `alignment.failure.json` instead of leaving only a missing final JSON;
- Japanese alignment uses parser-owned pretokenized units and does not run
  Nagisa a second time on reconstructed window text;
- window ownership is frozen by current-core start time; later-window overlap is
  resolved by forward-only left compression against the previous committed end;
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
