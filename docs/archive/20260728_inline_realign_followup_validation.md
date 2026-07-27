# 2026-07-28 Inline Realign Follow-up Archive Validation

## Scope

Validated the follow-up implementation for:

- localized automatic anomaly spans;
- GT-oracle local realign;
- stable-segment assistance for next-window input and safe commit cursors;
- active stable-window reruns;
- forced +25%/+50% future-text expansion;
- raw/official planner divergence targeting;
- constructed fail-closed incomplete outputs;
- expanded Demo/MIR-1K/M4Singer manifests;
- align-all-then-render Demo batching with one render directory per item;
- compact follow-up summary and bounded evidence collection.

## Static and regression validation

```text
python -m compileall -q src scripts tests       passed
bash -n for every scripts/**/*.sh               passed
focused inline-realign tests                     21 passed
all runnable tests                               168 passed
```

Runnable-test command:

```bash
PYTHONPATH=src pytest -q \
  --ignore=tests/test_audio_contract.py \
  --ignore=tests/test_m4singer_preparation.py \
  --ignore=tests/test_mir1k_partial_align.py
```

Full `pytest` remains blocked during collection by the local archive container
missing `pypinyin`. The three blocked files are the same existing data/audio
preparation tests listed above; no executed test failed.

## Synthetic manifest smoke

A synthetic smoke root containing one prepared Demo, one MIR-1K development
item and one M4Singer validation item produced:

```text
item_count: 3
dataset_counts: demo=1, mir1k=1, m4singer=1
heldout: excluded
Demo prepared suffix found: _qwen_fa_raw_guarded
```

The smoke confirms `--require-demo`, recursive discovery, multiple prepared
suffixes, MIR-1K role filtering and M4Singer materialization.

## Demo render smoke

A real FFmpeg run completed after a synthetic experiment summary existed.
Observed output:

```text
items/demo_demo1/render/official.mp4
```

No second song output tree or duplicate alias video was created. The review
profile used one H.264 encode, 24 fps, CRF 28 and AAC 96 kbps.

## Summary and bounded evidence smoke

The follow-up summarizer generated:

```text
followup_analysis_summary.json
followup_analysis_summary.md
```

The collector included both summaries and excluded rendered video/ASS. A 1 MiB
cap smoke completed in `full` mode with an archive of approximately 3 KiB.

## Validation limits

The archive container does not contain the server Qwen snapshot, R2 checkpoint,
M4Singer corpus, MIR-1K subset or real Demo media. Therefore this validation
does not claim:

- successful CUDA/model inference;
- local-realign accuracy improvement;
- stable-window cursor improvement;
- future-text expansion stability;
- Demo listening improvement.

Those are the explicit outputs of the server smoke/formal pipeline.

## Safety boundary

Automatic writeback remains disabled. GT-oracle cases, automatic cases,
constructed incomplete outputs, Demo listening results and M4Singer synthetic
seams are stored and summarized separately.
