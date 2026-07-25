# 夜苏打 03:05 / 03:12 tail-windowed supplement

This supplement is independent from the original 12-alignment demo matrix.

## Behavior

- source: validated `夜苏打/qwen_fa_demo_serial/work/audio/vocals.wav`;
- case A: audio after `03:05` with the supplied 10 lyric lines;
- case B: audio after `03:12` with the supplied 9 lyric lines;
- inference: separated vocals only, serial-window mode only, R0/R1/R2 loaded one at a time;
- default window: 60 s core + 15 s left/right context;
- output: `夜苏打/qwen_fa_tail_windowed_0305_0312/`;
- products: six individual videos and two three-model comparison videos.

## Apply

Extract this patch over `/home/hyan/LyricAlignment`.

## Run all stages

```bash
cd /home/hyan/LyricAlignment
KARAOKE_FONT='Noto Sans CJK SC' \
  bash scripts/demo/run_yessoda_tail_windowed.sh
```

## Resume by stage

```bash
STAGE=prepare bash scripts/demo/run_yessoda_tail_windowed.sh
STAGE=align bash scripts/demo/run_yessoda_tail_windowed.sh
KARAOKE_FONT='Noto Sans CJK SC' STAGE=render \
  bash scripts/demo/run_yessoda_tail_windowed.sh
```

## Force regeneration

```bash
FORCE_PREPARE=1 FORCE_ALIGN=1 FORCE_RENDER=1 \
KARAOKE_FONT='Noto Sans CJK SC' \
  bash scripts/demo/run_yessoda_tail_windowed.sh
```

The default source validation is strict. It requires `separation_quality.json` to have `passed=true` and the vocal SHA-256 to match `vocals.identity.json` schema `yessoda_spleeter_v2`.
