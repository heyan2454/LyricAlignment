# AI Session Entry

## Read in this order

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/sessions/20260727_mir1k_demo_diagnostic_experiment.md`
4. `docs/manual/demucs_deployment.md`
5. `docs/manual/qwen_fa_batch_demo.md`
6. `docs/sessions/20260726_demo_alignment_stability_exploration.md`
7. `docs/sessions/20260726_demo_v2_failure_diagnostics_and_pack_repair.md`
8. `docs/sessions/20260726_demo_exploration_archive.md`
9. `docs/status/known_issues_20260724.md`
10. `docs/status/next_execution_plan.md`
11. `docs/principles.md`

## Current stage

```text
first Qwen FA LoRA cycle complete and archived
-> current focus: MIR-1K controlled demo diagnostics
-> isolate context, separator, and v6 propagation effects before redesigning cascade logic
```

## Canonical facts

- R0/R1/R2 and two complete R2 seeds are available;
- missing seed3407 OOD and seed2 test/OOD evaluations completed with rc=0;
- seed2 checkpoint selection remained step750 after terminal step1110 validation;
- metric schema v3 fixes valid-only, missing/invalid, and coverage semantics;
- nineteen result sets were recomputed without changing the primary metric;
- R2 long-context regression is dominated by one late-sequence collapse;
- MIR-1K demo diagnostics use a deterministic 8-development / 4-held-out / 5-spare split selected without model outputs;
- successful demo alignments preserve raw, processor-decoded, selected, final, and structural-quality artifacts;
- Demucs 4.1.0 / htdemucs_ft is available as a pinned optional separator input with external weight caching;
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
