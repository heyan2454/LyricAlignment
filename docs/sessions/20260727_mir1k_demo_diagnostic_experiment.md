# MIR-1K demo diagnostic experiment — 2026-07-27

## Decision scope

This experiment diagnoses three factors in the current Qwen Forced Aligner
demo:

1. extra lyric context;
2. vocal input source: mix, official MIR-1K vocal channel, Spleeter, Demucs;
3. current v6 serial-window propagation.

It does not train or select a checkpoint.  MIR-1K remains OOD test-only.  The
8-song development subset may select a demo setting; the 4-song held-out subset
is used once after the setting is frozen.  Five aligned songs remain spare.

## Why MIR-1K is suitable here

The project already has 17 manually character-aligned MIR-1K songs and a fixed
channel contract.  The data provides:

- full mixture reconstruction from accompaniment + vocal channels;
- an official isolated-vocal diagnostic input scaled to its contribution in the reconstructed mix;
- character-level GT for direct onset/offset evaluation;
- natural variation in duration, character rate, gaps, and singer.

The official vocal channel is not a realistic deployed separator.  It is scaled by 0.5, matching its contribution to the reconstructed diagnostic mix, and is used to distinguish separator failure from aligner failure.

## Reproducible subset selection

Selection uses only GT/data complexity descriptors, never Qwen predictions:

- duration;
- character rate;
- gap ratio;
- mean character duration;
- annotation coverage;
- singer diversity.

The development set first includes feature extremes, then farthest-point
feature diversity.  The held-out set is selected from the remaining songs by
the same diversity rule.  Seed: `20260727`.

```bash
cd /home/hyan/LyricAlignment

python scripts/demo/prepare_mir1k_demo_subset.py \
  --manifest /home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood/mir1k_vocal_ood_manifest.jsonl \
  --characters /home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood/mir1k_vocal_ood_characters.jsonl \
  --mir1k-root /home/hyan/Data/datasets/mir1k/raw/MIR-1K \
  --out-dir /home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1 \
  --development-count 8 \
  --heldout-count 4 \
  --seed 20260727 \
  --units-per-line 12
```

Expected outputs:

```text
selection.json
selection.jsonl
items/<item_id>/item.json
items/<item_id>/lyrics.txt
items/<item_id>/lyrics.continuous.txt
items/<item_id>/ground_truth.characters.jsonl
items/<item_id>/audio/mix.wav
items/<item_id>/audio/official_vocal.wav
items/<item_id>/audio/accompaniment.wav
```

`lyrics.txt` is wrapped every 12 alignment units without using timestamp
boundaries.  This prevents a single long lyric line from silently expanding a
window candidate to the whole song.

## Step 1 — separator preparation

Follow `docs/manual/demucs_deployment.md`, then run Spleeter and Demucs on the
8 development songs only.

```bash
python scripts/demo/prepare_mir1k_separator_variants.py \
  --subset-root /home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1 \
  --roles development \
  --separators spleeter demucs \
  --spleeter-model-root /root/autodl-tmp/AST_storage/Data/lyricalign/models/spleeter \
  --spleeter-command "conda run -n spleeter spleeter" \
  --demucs-command "conda run -n demucs demucs" \
  --demucs-model htdemucs_ft \
  --demucs-shifts 0 \
  --demucs-overlap 0.25 \
  --demucs-torch-home /root/autodl-tmp/AST_storage/Data/lyricalign/models/torch
```

## Step 2 — independent-window context experiment

### Purpose

Determine whether extra future lyrics change the model prediction before any
serial cursor or cross-window commit is applied.

### Controlled setup

- model/checkpoint fixed;
- `official_vocal` fixed for the first pass;
- 30-second core;
- 10-second left and right acoustic context;
- GT used only to choose which lyrics acoustically overlap the input and which
  units belong to the evaluation core;
- GT timestamps are not passed to Qwen;
- windows are independent and have no state propagation.

Conditions add future lyrics beyond the acoustic input end:

```text
0 s / 5 s / 15 s / 30 s
```

```bash
QWEN_PY=/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python
R2=/home/hyan/Data/lyricalign/runs/20260723_qwen_fa_r2_full_seed3407/checkpoints/step-001000
OUT=/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_runs_v1

$QWEN_PY scripts/demo/run_mir1k_demo_diagnostics.py \
  --subset-root /home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1 \
  --out-dir "$OUT" \
  --experiment context \
  --role development \
  --model-kind lora \
  --checkpoint "$R2" \
  --audio-variant official_vocal \
  --future-text-sec 0 5 15 30 \
  --left-text-policies matched \
  --oracle-core-sec 30 \
  --left-context-sec 10 \
  --right-context-sec 10 \
  --local-files-only
```

Optional left-context diagnostic, after the future-text result is known:

```bash
$QWEN_PY scripts/demo/run_mir1k_demo_diagnostics.py \
  ...same fixed arguments... \
  --experiment context \
  --future-text-sec 5 \
  --left-text-policies matched omit
```

Interpretation:

- `matched` supplies lyrics corresponding to the left acoustic context;
- `omit` retains left audio but begins the transcript at the core;
- if `omit` is worse, duplicated already-sung text is necessary acoustic
  context rather than an accidental repeat;
- if predictions deteriorate as future text grows, candidate text is directly
  changing model search rather than only affecting serial propagation.

## Step 3 — separator experiment

### Purpose

Compare aligner accuracy on the same independent windows using:

```text
mix
MIR-1K official vocal channel
Spleeter vocals
Demucs htdemucs_ft vocals
```

Use the best finite future-text condition from Step 2; the initial default is
5 seconds.

```bash
$QWEN_PY scripts/demo/run_mir1k_demo_diagnostics.py \
  --subset-root /home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1 \
  --out-dir "$OUT" \
  --experiment separator \
  --role development \
  --model-kind lora \
  --checkpoint "$R2" \
  --audio-variants mix official_vocal spleeter demucs \
  --separator-future-text-sec 5 \
  --demucs-model htdemucs_ft \
  --oracle-core-sec 30 \
  --left-context-sec 10 \
  --right-context-sec 10 \
  --local-files-only
```

Primary comparison:

- processor-decoded onset MAE, median, P90;
- offset MAE, median, P90;
- onset/joint rates within 0.08, 0.16, 0.24, 0.5 and 1.0 seconds.

Auxiliary comparison:

- raw-to-processor change;
- timestamp probability, margin and entropy in per-unit rows;
- separator structural quality JSON;
- blind listening for consonant damage, vocal discontinuity, backing-vocal
  leakage, and accompaniment leakage;
- wall time and peak GPU memory recorded externally.

Do not select a separator from listening alone.  A cleaner-sounding vocal may
remove consonant onsets and reduce alignment accuracy.

## Step 4 — current v6 serial propagation

Run only after Step 2 and Step 3 freeze the context and separator candidates.
The script applies current `hard_core_forward_overlap_compression_v6` and
reports raw, processor-decoded, selected, and final metrics against GT.

```bash
$QWEN_PY scripts/demo/run_mir1k_demo_diagnostics.py \
  --subset-root /home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1 \
  --out-dir "$OUT" \
  --experiment serial \
  --role development \
  --model-kind lora \
  --checkpoint "$R2" \
  --audio-variants official_vocal spleeter demucs \
  --demucs-model htdemucs_ft \
  --core-sec 60 \
  --left-context-sec 10 \
  --right-context-sec 10 \
  --future-line-padding 1 \
  --minimum-forward-characters 64 \
  --future-character-ratio 1.35 \
  --max-candidate-expansions 4 \
  --local-files-only
```

Interpretation:

- independent windows poor: model/audio/context dominates;
- independent windows good, serial raw poor later: transcript cursor/candidate
  feedback dominates;
- serial raw good, processor/final poor: decode or commit policy dominates;
- selected good, final poor: overlap compression is damaging the result;
- official vocal good, both separators poor: separation remains the bottleneck;
- Demucs improves independent windows but not serial: separator helps local
  evidence but propagation remains dominant.

## Step 5 — freeze and held-out confirmation

Before touching held-out data, write a frozen decision JSON containing:

- model/checkpoint hashes;
- future-text condition;
- separator/package/model/parameters;
- serial-window parameters;
- development aggregate metrics;
- the exact command to run.

Then prepare only the chosen separator on held-out songs and execute exactly
one confirmation configuration:

```bash
python scripts/demo/prepare_mir1k_separator_variants.py \
  --subset-root /home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1 \
  --roles heldout \
  --separators demucs \
  ...same frozen Demucs arguments...

$QWEN_PY scripts/demo/run_mir1k_demo_diagnostics.py \
  ...same frozen Qwen/window arguments... \
  --experiment serial \
  --role heldout \
  --audio-variants demucs
```

Do not retune after viewing held-out results.  Unexpected held-out failure is a
reported negative result and should trigger a new experiment version with a new
held-out policy, not silent reuse.

## Artifact schema

Each trial is written to:

```text
<out>/<experiment>/<role>/<condition>/<item_id>.json
```

Each file contains:

- immutable model/checkpoint identity;
- audio variant and path;
- experiment condition;
- per-stage aggregate metrics;
- per-character GT/prediction/error rows;
- oracle window records or current serial trace.

Each experiment role also has `summary.json` with condition-stage pooled
metrics.  Frame-level, event-level, demo listening, and character-alignment
metrics must remain separate.

## Current conclusion strength

No preferred separator, context length, or propagation repair is assumed in
this plan.  The scripts provide a controlled way to determine which component
first creates the observed drift.  MIR-1K conclusions are OOD diagnostics and
must not be generalized to all Chinese or multilingual singing without a
separate dataset.
