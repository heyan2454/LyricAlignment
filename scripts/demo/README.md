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
