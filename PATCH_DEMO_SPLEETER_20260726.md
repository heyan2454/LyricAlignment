# Demo Spleeter strict-failure patch — 2026-07-26

## Problem

The first Spleeter model download may fail, while a later invocation can still
produce WAV files that are effectively copies rather than valid separated
stems.  The previous demo entrypoint treated the existence of `vocals.wav` as
success and reused it indefinitely when the mix hash matched.

## Changes

- Set an explicit external `MODEL_PATH` through `SPLEETER_MODEL_ROOT`.
- Preserve both `vocals.wav` and `accompaniment.wav`.
- Require Spleeter's completed-model `.probe` marker.
- Add resumable, checksum-verified official model download helper.
- Add waveform diagnostics that reject:
  - a near-copy of the original mix as the vocal stem;
  - near-identical vocal and accompaniment stems;
  - silent mix or stems.
- Save `separation_quality.json` with RMS, correlation, gain-fit residual, and
  reconstruction diagnostics.
- Reuse outputs only when the v2 identity, audio hashes, model root, and a
  passing quality-report hash all match.
- Add `FORCE_SEPARATE=1` and `FORCE_SPLEETER_MODEL_REDOWNLOAD=1` controls.

## Apply

The patch ZIP contains a top-level `LyricAlignment/` directory.  Apply from the
project parent directory:

```bash
cd /home/hyan
unzip -o LyricAlignment_demo_spleeter_strict_fix_20260726.zip
cd /home/hyan/LyricAlignment
```

## Recommended recovery command

```bash
export SPLEETER_MODEL_ROOT=/root/autodl-tmp/AST_storage/Data/lyricalign/models/spleeter
bash scripts/demo/download_spleeter_model_resumable.sh
FORCE_SEPARATE=1 STAGE=prepare bash scripts/demo/run_yessoda_serial_demo.sh
```

Expected outputs:

```text
夜苏打/qwen_fa_demo_serial/work/audio/mix.wav
夜苏打/qwen_fa_demo_serial/work/audio/vocals.wav
夜苏打/qwen_fa_demo_serial/work/audio/accompaniment.wav
夜苏打/qwen_fa_demo_serial/work/audio/separation_quality.json
夜苏打/qwen_fa_demo_serial/work/audio/vocals.identity.json
```

`separation_quality.json` must contain `"passed": true` before alignment or
rendering should proceed.

## Validation performed here

- `bash -n` passed for both modified/new shell scripts.
- Seven targeted demo tests passed.
- The quality-check CLI passed on a synthetic reconstructable two-stem example.
- The full repository test suite could not be collected in this sandbox because
  the optional/runtime dependency `pypinyin` is not installed; this is unrelated
  to the demo patch.
