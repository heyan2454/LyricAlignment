# Demo GPU Decoder Smoke/Overnight Patch — 2026-07-27

## Implemented decisions

- The patch is based directly on the original Quick v2.1 overnight handoff.
- Two trainable GPU decoders are implemented: residual TCN and bidirectional
  Transformer encoder.
- Both architectures share the same Qwen/M4Singer feature cache, training
  targets, residual/gate heads, monotonic projection, and validation split.
- Official, TCN, and Transformer are first-class MIR-1K baseline and realign
  branches.
- Paired spans are the anomaly union from all three baseline scans.
- All paired spans run exact. Only missing, unsuccessful, or decoder-disagreeing
  cases advance to +2, then +4.
- M4Singer is counted by item, song, singer, character, and split; no fixed
  claim of 1,000 independent natural anomalies is made.
- Demucs/30 seconds remains the main large-run scope. Audio source, window size,
  and context are not fully multiplied.

## Acceptance checks

1. Run `bash scripts/demo/run_demo_realign_smoke.sh`.
2. Confirm all stage statuses are `complete` or `complete_empty_plan`.
3. Confirm both `decoder_training/tcn/summary.json` and
   `decoder_training/transformer/summary.json` report `gpu_first_contract`.
4. Confirm both evaluation files contain raw, official, and decoder metrics.
5. Confirm exact realign roots for official, TCN, and Transformer contain the
   same planned case IDs.
6. Review parameter count, slots/s, peak CUDA memory, validation MAE, baseline
   anomaly counts, and paired realign outcomes before launching or freezing a
   larger run.
