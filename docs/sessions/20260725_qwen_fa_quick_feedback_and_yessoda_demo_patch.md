# 2026-07-25 quick feedback and 夜苏打 demo patch

## Added

- dense short-sample absolute-position probe around 120s;
- fixed-target total-input-length probe using trailing silence;
- strict validation-best checkpoint resolution in new launchers;
- request-hash-aware resume for the new diagnostic and demo tasks;
- standalone Spleeter two-stem preparation;
- R0/R1/R2 serial full and 60s-core windowed alignment;
- occurrence-aware character mapping for repeated lyrics;
- ASS KTV renderer with alternating two-line per-character progression;
- 12 individual, four 3-way and three 4-way videos.

## Boundaries

- No training is added.
- Demo outputs are metric-free and cannot select checkpoints.
- Windowed demo inference does not read full-context predictions.
- Four-way composites use original mix audio as a single shared timeline; vocal-only audio remains in individual vocal videos.

## Verification in patch environment

- Python compileall passed.
- Shell syntax checks passed.
- New and directly affected unit tests passed.
- FFmpeg prefix/tail silence on 44.1kHz stereo input passed.
- ASS Chinese KTV render passed.
- 3-panel and 4-panel xstack rendering passed at 1920×1080.

GPU/model execution and Spleeter separation cannot be performed in the patch-build environment because the server assets are not present.
