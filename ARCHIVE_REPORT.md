# Archive Report: Qwen FA Follow-up Repaired Archive

**Archive date:** 2026-07-24  
**Stable extracted root:** `LyricAlignment/`  
**Output:** `LyricAlignment_20260724_qwen_fa_followup_repaired_archive.zip`  
**Role:** canonical closeout of the first Qwen Forced Aligner LoRA experiment cycle.

## Integrated evidence

The archive integrates the original follow-up handoff, completed evaluation evidence,
row-level recomputation inputs, the missing-evaluation controller, and the consolidated
overnight summary.

Confirmed return-code-0 evaluations:

1. seed3407 R2 MIR-1K OOD;
2. seed20260724 terminal step1110 validation;
3. seed20260724 M4Singer sealed test;
4. seed20260724 MIR-1K OOD.

The second R2 seed remains frozen at step750 after terminal validation is added to
the validation-only candidate set.

## Direct repairs

- corrected character metric state semantics and valid-only denominator;
- added deterministic metric recomputation with provenance and primary-metric invariance checks;
- recomputed 19 preserved test/OOD/long-diagnostic result sets under
  `character_interval_metrics_v3_tolerant`;
- fixed MIR-1K timestamp milliseconds/seconds handling;
- added complete pinned-model snapshot preflight;
- added terminal-checkpoint validation and selection support;
- separated requested item limits from resolved sample counts;
- reconciled historical seed2 identity without rewriting the original evidence;
- added a long-context per-item/outlier audit;
- replaced the old non-portable/self-referential archive checksum pattern with
  relative-path manifests that exclude themselves.

## Evidence boundary

- No training or GPU inference was run while constructing this archive.
- Original metrics and identity files remain preserved.
- Corrected metrics and reconciled identities are separate, versioned files.
- The primary metric `song_macro_boundary_mae_sec` remained unchanged in all 19
  row-level recomputations.
- Audio, base-model weights, LoRA checkpoints, Hugging Face caches, and large
  per-item external runs are not copied into the source tree.

## Primary results

| Configuration | M4Singer test | MIR-1K OOD |
|---|---:|---:|
| R0 raw | 251.391 ms | 97.108 ms |
| R1 projector-only, seed3407 | 90.775 ms | 44.007 ms |
| R2 audio LoRA, seed3407 | 79.590 ms | 42.557 ms |
| R2 audio LoRA, seed20260724 | 80.920 ms | 40.459 ms |

## Remaining limitations

- seed2 terminal-validation auxiliary metrics cannot be recomputed without its
  validation reference rows;
- the exact seed3407 R2 M4Singer sealed-test row-level input is not present, so
  its historical v2 auxiliary fields remain explicitly historical;
- the approximately 150-second R2 regression is localized but not mechanistically
  resolved;
- a second full R1 seed would be required to estimate cross-seed variance of the
  R2-minus-R1 difference.

## Validation

- `python -m compileall -q src scripts tests`: passed;
- targeted regression/entrypoint/archive tests: **26 passed**;
- shell syntax: **7 scripts passed `bash -n`**;
- full pytest collection is blocked only by missing local `pypinyin` in three
  unrelated dataset/audio test modules.

See:

```text
reports/review/20260724_qwen_fa_followup_repair_archive_validation.md
runs/evaluation/20260724_qwen_fa_followup_repair_archive/run_summary.json
```
