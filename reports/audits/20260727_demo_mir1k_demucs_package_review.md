# Demo / MIR-1K / Demucs package review — 2026-07-27

## Scope

This package completes the current demo code path without redesigning the
`hard_core_forward_overlap_compression_v6` propagation policy.  It adds the
evidence and controlled experiments needed to decide whether later changes
should target text context, vocal separation, processor input preparation, or
serial propagation.

The recursive duplicate-stem issue was intentionally not changed because the
owner judged it outside the expected usage pattern.

## Implemented

### Alignment evidence and failure semantics

- successful alignments write:
  - `alignment.raw.json`;
  - `alignment.processor_decoded.json`;
  - `alignment.selected.json`;
  - `alignment.json`;
  - `alignment.quality.json`;
- structural status is separated into `passed_structural`, `warning`, and
  `failed_structural`;
- warnings expose raw regressions, overlaps, processor changes, candidate
  expansion, cross-window compression, and zero-duration units;
- historical fixed-song and tail entries now preserve progress/failure JSON and
  invalidate stale final output on rerun failure;
- the tail script records the actual current window-policy constant rather than
  hard-coding v3;
- render-only execution resolves cached audio without validating Spleeter or
  Demucs weights.

### Demucs

- reusable batch entry accepts Spleeter or Demucs;
- Demucs identity includes requested package/model, device, shifts, overlap,
  segment, jobs, clip mode, mix hash, command, and output hashes;
- default experiment settings are `demucs==4.1.0`, `htdemucs_ft`,
  `--two-stems vocals`, `--shifts 0`, and `--overlap 0.25`;
- separator outputs run through the existing silent/near-copy structural gate;
- weights and separated WAV files remain external;
- deployment and failure-recovery instructions are in
  `docs/manual/demucs_deployment.md`.

### MIR-1K experiment package

- deterministic selection from the 17 manually aligned OOD songs:
  - 8 development;
  - 4 held-out;
  - 5 spare;
  - seed `20260727`;
- selection uses only duration, character rate, gap ratio, character duration,
  coverage, and singer diversity;
- no model output participates in selection;
- materialized diagnostic mix is exactly:

  ```text
  0.5 * accompaniment channel + 0.5 * vocal channel
  ```

- the official vocal and accompaniment diagnostic stems preserve the same 0.5
  contribution scale, so they reconstruct the diagnostic mix exactly;
- lyrics are wrapped every 12 units without timestamp leakage;
- separator variants are cached and structurally checked;
- independent oracle windows compare future lyric context without serial state;
- separator comparison evaluates mix, official vocal, Spleeter, and Demucs on
  identical windows;
- current v6 serial evaluation reports raw, processor-decoded, selected, and
  final character-level metrics;
- output includes per-character GT/prediction/error evidence, wall time, and
  peak allocated GPU memory;
- held-out use is explicitly one frozen confirmation run.

### Multilingual input diagnosis

`check_qwen_fa_processor_equivalence.py` compares the official Processor path
with the project's parser-owned pretokenized path, including:

- unit lists;
- input length and hash;
- timestamp-slot positions;
- first token mismatch;
- optional decoded outputs from the real model.

This does not assume that non-Chinese weakness is caused by either Qwen or the
project input path before the integration result exists.

## Validation completed in the review environment

```text
Python compilation:
  all modified/new demo Python scripts passed

Focused regression suite:
  45 passed

MIR-1K materialization smoke:
  synthetic 17-song two-channel fixture
  selection = 8 development / 4 held-out / 5 spare
  ffmpeg mix/vocal/accompaniment generation passed
```

Focused tests include:

- existing serial-window and language-unit tests;
- existing batch discovery/render/failure tests;
- existing separation-quality tests;
- stage artifact and structural-quality tests;
- deterministic MIR-1K selection tests;
- context candidate-bound tests;
- oracle-window GT evaluation tests;
- Demucs batch CLI/default and render-only tests.

The full repository suite did not collect in this review environment because
`pypinyin` is absent.  Three data-preparation test modules fail import before
execution.  `pypinyin` is already declared in `pyproject.toml`; this is an
environment dependency gap, not a demonstrated code failure.  No claim of a
full-suite pass is made.

## Not executed here

- actual Qwen GPU inference;
- real MIR-1K 17-song selection, because the external dataset is not in the
  review container;
- Spleeter inference;
- Demucs installation, weight download, or GPU separation;
- Chinese/English/Japanese real-Processor equivalence;
- development or held-out alignment results.

These remain server execution tasks.  The package provides exact commands,
external paths, identities, resume behavior, and expected outputs.

## Current conclusion

The package is ready to deploy as a controlled diagnostic baseline.  It does
not solve cascade drift.  It makes the first source of drift measurable before
new propagation rules are introduced.  Structural validity, character GT
accuracy, separator quality, listening quality, and engineering runtime remain
separate result categories.
