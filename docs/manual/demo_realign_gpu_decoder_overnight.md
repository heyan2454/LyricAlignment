# GPU TCN/Transformer Decoder + Paired Realignment Smoke / Overnight

## Purpose

The experiment separates two questions while sharing expensive Qwen inference:

1. can a GPU trainable decoder improve `raw timestamp slots -> initial alignment`;
2. does local realignment remain useful under the official, TCN, and Transformer
   initial decoders?

The patch implements two new decoder families:

- `gpu_tcn`: six-layer residual dilated TCN by default;
- `gpu_transformer`: four-layer bidirectional Transformer encoder by default.

Both consume the same cached M4Singer slot evidence and use the same residual,
repair-gate, loss, and GPU monotonic-projection contract. Therefore the decoder
comparison does not rerun Qwen and does not mix incompatible metric schemas.

## GPU contract

Production smoke and overnight require CUDA. Feature extraction, TCN or
Transformer refinement, masking, residual application, and `torch.cummax`
projection are PyTorch tensor operations. CPU execution requires explicit
`--allow-cpu-test` and is intended only for unit/synthetic tests.

The Transformer is deliberately lightweight but more GPU-intensive than the
TCN. Its default batch size is 32 rather than 64 because attention memory grows
with sequence length. The controller length-buckets cached items before
batching. An untrained decoder starts near raw argmax: residual heads are zero
and repair gates start nearly closed.

## Non-Cartesian data flow

```text
M4Singer Qwen R2 inference, once and resumable
  -> compact shared float16 feature shards
  -> CUDA TCN training/evaluation
  -> CUDA Transformer training/evaluation

MIR-1K official baseline scan
MIR-1K TCN baseline scan
MIR-1K Transformer baseline scan
  -> union of natural-anomaly spans
  -> exact realign on all three decoders
  -> only unresolved/missing/disagreeing cases receive +2
  -> only remaining cases receive +4
```

The cache stores compact features, raw classes, official-decoder classes, GT
classes, and identities. It does not store copied audio or full logits.

## Dataset counting

`input_audit.json` reports M4Singer item, unique-song, unique-singer, character,
and split counts. The workflow never assumes 1,000 independent natural
anomalies. `--realign-max-cases 1000` is only an upper bound after the MIR-1K
baseline scans and anomaly union.

## Default scope

- M4Singer: all available train and validation items for overnight;
- MIR-1K: development + quick-v2-extra roles;
- audio: Demucs only;
- core window: 30 seconds;
- automatic anchor policies: one;
- decoder training: 2,500 steps each unless overridden;
- realign: exact for the union, then selective +2 and +4 escalation.

Official-vocal, 60-second windows, additional anchor policies, and alternative
training sizes are targeted follow-up slices, not axes multiplied into the main
run.

## Required assets

```bash
export REPO_ROOT=/home/hyan/LyricAlignment
export R2_CHECKPOINT=/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750
export M4_LABELS=/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl
export M4_AUDIO_ROOT=/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer
export MIR1K_SUBSET_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1
export MODEL_SOURCE=/path/to/complete/Qwen3-ForcedAligner-snapshot
```

The wrapper accepts either `processor_config.json` or
`preprocessor_config.json`.

## Smoke

```bash
cd /home/hyan/LyricAlignment
bash scripts/demo/run_demo_realign_smoke.sh
```

Smoke defaults:

- 16 M4Singer items;
- 8 TCN steps and 8 Transformer steps;
- one MIR-1K development song;
- one Demucs input;
- at most four paired spans;
- official, TCN, and Transformer exact/+2/+4 controller paths.

Smoke verifies execution and artifacts only. Its metrics must not freeze a
scientific choice.

## Overnight

```bash
cd /home/hyan/LyricAlignment
nohup bash scripts/demo/run_demo_realign_overnight.sh \
  > /home/hyan/Data/lyricalign/demo_realign_overnight_launcher.log 2>&1 &
```

Bounded overrides:

```bash
# Same number of optimization steps for both trainable decoders.
bash scripts/demo/run_demo_realign_overnight.sh --decoder-steps 1200

# Different budgets while retaining the same cache and validation split.
bash scripts/demo/run_demo_realign_overnight.sh \
  --tcn-steps 1800 --transformer-steps 1200

# Reduce Transformer memory pressure without changing TCN.
bash scripts/demo/run_demo_realign_overnight.sh \
  --transformer-batch-size 16

# Limit the initial M4Singer cache for an intermediate run.
bash scripts/demo/run_demo_realign_overnight.sh --m4-max-items 4000
```

Do not run two controllers against the same `OUT_ROOT` concurrently.

## Resume semantics

- cache shards resume by completed item IDs;
- each architecture resumes independently from its own `last.pt`, including
  optimizer, scheduler, and AMP scaler;
- baseline evidence and realign cases reuse matching request hashes;
- controller stages reuse matching command identities;
- scientific metric values never terminate the overnight early.

## Outputs

```text
OUT_ROOT/
  input_audit.json
  decoder_cache/shards/*.pt
  decoder_training/{tcn,transformer}/{best.pt,last.pt,summary.json,...}
  decoder_evaluation/{tcn,transformer}/metrics.json
  baselines/{official,gpu_tcn,gpu_transformer}/
  plans/{exact,plus2,plus4}.jsonl
  realign/{exact,plus2,plus4}/{official,gpu_tcn,gpu_transformer}/
  stage_status/*.json
  logs/*.log
  overnight_summary.json
  demo_realign_{smoke|overnight}_compact.tar.gz
```

The compact archive excludes checkpoints, full caches, audio, complete evidence,
and full per-case traces.

## Interpretation and fairness

Report separately:

1. M4Singer raw/official/TCN/Transformer boundary metrics on the same split;
2. decoder parameter count, wall time, slots/s, peak CUDA memory, and batch size;
3. MIR-1K baseline anomaly structure for each decoder;
4. paired realign outcomes on identical target spans and escalation stages;
5. deployment-triggered realign counts for each decoder.

Do not claim that Transformer or TCN is better merely from training loss. Compare
frozen validation metrics and paired MIR-1K behavior. Do not combine M4Singer
boundary MAE with MIR-1K serial metrics into one headline score. Held-out MIR-1K
remains outside the default overnight until settings are frozen.

## Small-cache split safety

Limited caches are selected per split rather than by truncating the merged
train/validation list. Smoke reserves at least four items from every requested
non-empty split, so the default 16-item cache cannot silently become train-only.
For a cache produced by the earlier implementation, rerunning the same Smoke
with this revision re-enters the cache stage because its command identity now
contains `--min-items-per-split 4`; missing validation items are appended without
deleting completed train shards.

As an additional Smoke-only recovery path, decoder training can derive a
deterministic song-disjoint holdout when an old cache truly has no validation
rows. This is written to `resolved_data.json` as `split_fallback=true` with the
held-out song IDs. Overnight does not enable this fallback automatically and
continues to require the canonical M4Singer validation split.
