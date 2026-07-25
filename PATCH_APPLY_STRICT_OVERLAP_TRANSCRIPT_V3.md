# Strict serial overlap-transcript hotfix

## Problem fixed

The previous strict-core patch started window 1's transcript at the first
uncommitted character near the 60 s core boundary while still supplying audio
from 50 s. A forced aligner must account for the 50--60 s vocals, so it could
attach that first new character to the 50 s input boundary and raise:

```text
first uncommitted character aligned inside the left context
```

## Correct policy

For a 60 s core with 10 s extensions:

- window 0: core 0--60, input 0--70;
- window 1: core 60--120, input 50--130;
- window 2: core 120--180, input 110--190.

The preceding window determines the next transcript start at the next window's
**audio input boundary** (50 s, 110 s, ...), not at its core boundary.

- If that audio cut falls inside a character, that cut character is omitted and
  the next complete character starts the new transcript.
- Complete lyrics in the 10 s left overlap are re-input to the forced aligner.
- Those overlap characters are context-only because they were already hard
  committed by the preceding core.
- Only the continuous uncommitted prefix whose character starts fall inside the
  current 60 s core is appended to final output.
- A character crossing a core end remains wholly owned by the preceding core.

The output identity changes to `hard_core_overlap_transcript_v3`, so old v2
windowed results are not reused.

## Apply

```bash
unzip -o LyricAlignment_strict_overlap_transcript_v3_hotfix_20260726.zip -d /home/hyan
cd /home/hyan/LyricAlignment
```

## Re-run full demo alignment and rendering

```bash
FORCE_ALIGN=1 STAGE=align bash scripts/demo/run_yessoda_serial_demo.sh

KARAOKE_FONT='Noto Sans CJK SC' \
FORCE_RENDER=1 STAGE=render \
bash scripts/demo/run_yessoda_serial_demo.sh
```

## Re-run 03:05 / 03:12 tail cases

```bash
FORCE_ALIGN=1 STAGE=align bash scripts/demo/run_yessoda_tail_windowed.sh

KARAOKE_FONT='Noto Sans CJK SC' \
FORCE_RENDER=1 STAGE=render \
bash scripts/demo/run_yessoda_tail_windowed.sh
```

## Trace fields

Each window now records separately:

- `next_window_input_character_start`: transcript start used by the next input;
- `next_uncommitted_character_start`: first character not yet hard committed;
- `input_boundary_cut_character`: character cut by the next acoustic input start;
- `core_boundary_character`: character crossing the current core end and owned by
  the current core;
- `left_context_character_count`: number of already committed overlap characters
  re-input as context.

## Validation

Validated on a clean overlay of the original demo package plus the Spleeter,
tail-case and strict-core patches:

```text
16 passed
```

Also passed Python compilation and shell syntax checks. Real R0/R1/R2 inference
must be run on the server where the model and checkpoints exist.
