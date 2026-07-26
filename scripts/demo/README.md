# Demo scripts

## Recommended reusable entry

```text
run_qwen_fa_batch.sh
run_qwen_fa_batch.py
```

The batch entry discovers same-stem media/TXT groups and defaults to:

```text
R2 + vocal + windowed
```

It supports single files, basenames, folders, optional output roots, arbitrary
individual modes, model/input composites, stage-specific resume and strict
Spleeter quality checks.  `--language` now controls language-aware alignment
units: English uses words, Japanese uses Nagisa words, and Chinese/Cantonese use
CJK characters plus contiguous Latin words.  Language and unit mode are part of
the cache identity.

Detailed guide, including English/Japanese/Cantonese examples and Japanese
dependency installation:

```text
docs/manual/qwen_fa_batch_demo.md
```

scripts/demo/run_qwen_fa_batch.sh \
  /home/hyan/Data/lyricalign/test/Chinese \
  --language Chinese \
  --spleeter-model-root \
  /root/autodl-tmp/AST_storage/Data/lyricalign/models/spleeter

## Historical fixed-song entries

- `run_yessoda_serial_demo.sh`: 夜苏打完整 12-mode demo entry.
- `align_qwen_fa_serial_demo.py`: shared R0/R1/R2 full and strict serial-window implementation.
- `run_yessoda_tail_windowed.sh`: 03:05 / 03:12 vocal-tail diagnostic entry.
- `align_qwen_fa_tail_windowed.py`: tail R0/R1/R2 strict serial-window inference.
- `render_qwen_fa_karaoke.py`: historical black-background full-demo renderer.
- `render_qwen_fa_tail_windowed.py`: tail individual and three-model renderer.

## Audio separation

- `download_spleeter_model_resumable.sh`: resumable checksum-verified 2-stem model installation.
- `check_audio_separation.py`: rejects silent, mix-copy or mutually identical stems.

## Windowed policy

`windowed` uses `hard_core_forward_overlap_compression_v6`:

- adjacent 60-second trusted cores with up to 10 seconds of acoustic context on both sides;
- lyric-unit ownership is decided by the current window's predicted start time;
- a unit starting before the core end belongs wholly to that core, even if its end crosses the boundary;
- already committed overlap lyrics are context-only and can never be overwritten;
- uncommitted current-window predictions are accepted even when they begin before the current core start;
- when a new interval overlaps the frozen prefix, only its left overlap is removed: `start=max(predicted_start, previous_end)`, `end=max(predicted_end, start)`;
- fully overlapped units may collapse to zero duration; later intervals are not shifted to preserve duration;
- no previous-window lookahead replacement, no core-start rejection and no overlap-triggered rerun;
- the previous window still determines the next transcript start at the next acoustic-input boundary.

Important result/trace fields:

- `selected_start_sec` / `selected_end_sec`: current-window prediction before compression;
- `overlap_compressed`;
- `overlap_compression_sec`;
- `overlap_compression_floor_sec`;
- `overlap_compression_collapsed_to_zero`;
- `overlap_compressed_character_count`;
- `overlap_compression_max_sec`;
- `next_window_input_character_start`;
- `next_uncommitted_character_start`;
- `input_boundary_cut_character`;
- `core_boundary_character`.

Demo output is diagnostic-only and cannot select checkpoints.

## MIR-1K controlled demo diagnostics

- `prepare_mir1k_demo_subset.py`: selects 8 development + 4 held-out songs from
  the 17 manually character-aligned MIR-1K OOD songs using GT/data descriptors
  only, then materializes mix, official vocal, lyrics and character GT.
- `prepare_mir1k_separator_variants.py`: prepares cached Spleeter and Demucs
  variants with command/weight/output identities and structural quality checks.
- `run_mir1k_demo_diagnostics.py`: runs independent oracle-window context and
  separator probes, plus current v6 serial propagation, and evaluates all
  stages against MIR-1K character GT.
- `check_qwen_fa_processor_equivalence.py`: compares official Processor input
  preparation with the project's pretokenized unit path in the real Qwen
  environment.

Canonical experiment and deployment guides:

```text
docs/sessions/20260727_mir1k_demo_diagnostic_experiment.md
docs/manual/demucs_deployment.md
```

MIR-1K remains OOD test-only.  Development songs may choose one demo setting;
held-out songs are run once after the configuration is frozen.  The official
MIR-1K vocal channel is a diagnostic upper-bound input, not a deployable
separator.

## Alignment evidence bundle

Every successful alignment now writes:

```text
alignment.raw.json
alignment.processor_decoded.json
alignment.selected.json
alignment.json
alignment.quality.json
```

`alignment.quality.json` distinguishes structural success, warning, and
structural failure.  It surfaces raw regressions, processor changes, candidate
expansion, overlap compression, and zero-duration units.  It is not a GT score
and cannot be used to select a checkpoint.

## Demucs

The general batch entry supports:

```text
--separator demucs
--demucs-command "conda run -n demucs demucs"
--demucs-version 4.1.0
--demucs-model htdemucs_ft
--demucs-device cuda
--demucs-shifts 0
--demucs-overlap 0.25
--demucs-torch-home <external cache>
```

The experiment default uses zero shifts for deterministic, lower-cost
comparison.  Keep the same parameters across development and held-out runs.

## Demo local-realignment quick diagnostics

```text
run_demo_realign_quick.sh
run_demo_realign_quick.py
collect_demo_realign_quick.py
```

These entries implement Q1–Q3 quick scientific diagnostics.  Quick results are
reviewed before the overnight design is frozen; they are not the later
post-design overnight smoke.  Execution and collection guide:

```text
docs/manual/demo_realign_quick_execution.md
```
