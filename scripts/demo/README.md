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

## GPU decoder + paired realignment smoke/overnight

```text
run_demo_realign_smoke.sh
run_demo_realign_overnight.sh
run_demo_realign_overnight.py
cache_gpu_decoder_features.py
train_gpu_decoder.py
evaluate_gpu_decoder.py
build_realign_funnel.py
collect_demo_realign_overnight.py
```

The path is GPU-first. M4Singer Qwen evidence is cached once as compact
float16 slot features, then both a CUDA residual TCN and a CUDA bidirectional
Transformer refine raw timestamp classes. MIR-1K baseline and realignment are
paired across official, TCN, and Transformer decoders. Cases follow an
`exact -> +2 -> +4` escalation funnel; the controller does not execute the full
decoder × context × audio × window Cartesian product. The deployment default is
Demucs/30 s. Add `--audio-variants official_vocal` only for a targeted diagnostic
upper-bound run.

Execution details:

```text
docs/manual/demo_realign_gpu_decoder_overnight.md
```

## Raw guarded demo

`align_qwen_fa_raw_guarded_demo.py` is the conservative standalone demo path
selected after the 2026-07-27 decoder overnight:

1. R2 Qwen timestamp-logit argmax is the baseline decoder;
2. broad structural and cross-window anomalies are detected;
3. only non-overlapping suspicious regions are considered;
4. exact-anchor and `+2` lyric-context local inferences must agree within 160 ms;
5. the bounded replacement must reduce the non-GT anomaly score and preserve
   global non-overlap before it is committed;
6. `+4` is not used by default because the overnight showed higher harm risk.

The server defaults point to the current Qwen snapshot and R2 step-750
checkpoint, while `MODEL_SOURCE`, `MODEL_REVISION`, `R2_CHECKPOINT`,
`PYTHON_BIN`, and `RAW_GUARDED_OUT_ROOT` remain overridable.

```bash
bash scripts/demo/run_raw_guarded_demo.sh lyrics.txt demucs_vocals.wav
```

The output retains both `baseline_raw/alignment.json` and the guarded final
`alignment.json`, plus `raw_guarded_realign.json` with every rejected or
selected decision.

For GT-backed development/held-out runs, compute detector and intervention
metrics from the full (not compact) evidence and Q2 directories:

```bash
python scripts/demo/analyze_raw_detector_repair.py \
  --baseline-root /path/to/raw_baseline \
  --q2-root /path/to/raw_q2 \
  --output /path/to/raw_detector_repair_metrics.json
```

To measure the actual raw detector and guarded intervention PRF on the MIR-1K
GT subset with the same no-GT anchor policy as the standalone demo:

```bash
bash scripts/demo/run_raw_realign_prf_experiment.sh
```

This experiment runs only the raw baseline and the paired `exact +2` repair
check. It does not run TCN, Transformer, `+4`, audio-source matrices, or window-
length matrices. Set `ROLES=heldout` only after thresholds are frozen.

### Full raw-guarded karaoke demo

`run_raw_guarded_karaoke_demo.sh` restores the user-facing functionality of the
historical demo while replacing only the alignment policy:

1. extract the original mix from media;
2. create and validate Spleeter vocal/accompaniment stems;
3. align the vocal track with R2 raw timestamps;
4. run conservative exact + matched-`+2` guarded realignment;
5. render baseline and guarded-final karaoke videos over the original video;
6. retain mix-audio primary videos, vocal diagnostics, and two-way comparisons.

The default fixed-song paths still point to `夜苏打`, and all paths/weights are
overridable:

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh

SOURCE_MEDIA=/path/song.mp4 \
LYRICS=/path/song.txt \
OUT_ROOT=/path/output \
  bash scripts/demo/run_raw_guarded_karaoke_demo.sh
```

The primary output is `raw_guarded_demo.mp4`. Stage resume uses
`STAGE=prepare|align|render`; force flags are `FORCE_SEPARATE`, `FORCE_ALIGN`,
and `FORCE_RENDER`.

Follow-up detector/repair protocol:

```text
docs/sessions/20260727_raw_guarded_followup_experiment.md
```
