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

`windowed` uses `hard_core_overlap_transcript_v3`:

- adjacent 60-second trusted cores;
- 10 seconds of acoustic context on both sides when available;
- the preceding window determines the next transcript at the next acoustic-input boundary;
- a character cut by that boundary is excluded and input begins with the following complete character;
- complete lyrics in the 10-second left overlap are re-input as context only;
- character ownership is determined by start time;
- a character crossing a core end belongs wholly to the preceding core;
- committed characters are immutable;
- no cross-window candidate competition or large cumulative monotonic flattening.

Important trace fields:

- `next_window_input_character_start`;
- `next_uncommitted_character_start`;
- `input_boundary_cut_character`;
- `core_boundary_character`.

Demo output is diagnostic-only and cannot select checkpoints.
