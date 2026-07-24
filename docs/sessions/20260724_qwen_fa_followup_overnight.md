# Qwen FA follow-up overnight entry

Date: 2026-07-24

## Goal

Complete the next fixed follow-up without using test or OOD results for model selection:

1. evaluate R0 raw on the frozen M4Singer test and MIR-1K OOD;
2. train a matched-budget full R1 projector-only ablation at seed 3407;
3. evaluate full R1 on the same frozen test and OOD sets;
4. construct test-only synthetic-long examples at 20/30/60/180-second levels and evaluate R0/R1/R2;
5. run paired 100-step R1/R2 pilots at seed 20260724 and write a validation-only decision on whether a full second R2 seed is justified.

The main entry is:

```bash
scripts/training/run_qwen_fa_followup_overnight.sh
```

The detached process wrapper is:

```bash
scripts/training/launch_qwen_fa_followup_detached.sh
```

## Smoke gate

The formal chain starts only after all mandatory smoke paths pass:

- Python/CUDA/dependency and offline model cache checks;
- targeted unit tests and compile checks;
- one-item raw M4Singer evaluation;
- one-item raw MIR-1K evaluation;
- R1 planned stop at step 1 followed by exact checkpoint resume to step 2;
- two-step R2 LoRA training;
- one test-only synthetic-long construction and label-generation path when a qualifying 20-second source sequence exists.

A lack of a qualifying synthetic-long source is recorded as data-limited, not as a code failure.

## Resumability

Each training run keeps immutable config/data/execution identity. On rerun, the orchestrator:

- skips a run only if its runtime summary, final evaluation, best checkpoint and checkpoint files validate;
- resumes from the numerically latest `step-*` checkpoint;
- retains an incomplete pre-checkpoint directory under an `.incomplete.<timestamp>.<pid>` name and restarts that stage;
- writes per-stage logs and a pipeline event JSONL;
- never overwrites a validated final evaluation directory.

A machine loss can discard progress since the latest configured checkpoint. Full R1 and optional full seed-2 R2 retain the matched 250-step save cadence used by full R2 seed 3407, so the worst replay window is below 250 optimizer steps. The pilot saves every 25 steps.

## Fairness

Full R1 and full R2 seed 3407 share:

- all accepted training items;
- seed 3407;
- micro batch 4;
- gradient accumulation 8;
- projector LR `5e-5`;
- weight decay `0.01`;
- warmup ratio `0.05`;
- 1,110 optimizer steps;
- evaluation/save cadence 250;
- the same validation metric and tolerant character metric path.

The intended difference is only that R1 keeps the audio tower frozen while R2 trains top-half audio-attention LoRA.

## Synthetic-long interpretation

Synthetic-long examples are diagnostic, not a new independent benchmark:

- sources are restricted to the frozen M4Singer `test` split;
- only adjacent segments from one song and one singer are concatenated;
- source order, ranges, hashes, join points and shifted character GT are retained;
- no train/validation source is admitted;
- each bucket uses at most one formal window per song/singer;
- 60- and 180-second levels use the existing availability thresholds of 45 and 150 seconds, while exact achieved durations are reported;
- metrics are reported both on all characters and after excluding characters whose GT interval lies within 0.5 seconds of a join.

A bucket with zero qualifying sequences is explicitly reported as data-limited and does not stop R0/R1 or seed-2 work.

## Second-seed decision

The second seed is fixed before the run as `20260724`. R1 and R2 use the same seed, 2,000-item song-aware pilot selection, 100 optimizer steps and training order rules.

The gate uses validation only. A full second R2 seed is recommended when all hold:

- R2 improves song-macro boundary MAE over R1 by at least 5 ms;
- relative improvement is at least 10%;
- invalid prediction rate does not increase by more than 1 percentage point;
- item coverage does not fall by more than 1 percentage point;
- all decision values are finite.

The default overnight chain writes the decision but does not automatically start full seed-2 training. Set `AUTO_RUN_FULL_SEED2=1` before launch to continue automatically only when the gate passes.

## Commands

After activating the known environment:

```bash
cd /home/hyan/LyricAlignment
conda activate lyricalign-qwen

bash scripts/training/launch_qwen_fa_followup_detached.sh start
bash scripts/training/launch_qwen_fa_followup_detached.sh status
bash scripts/training/launch_qwen_fa_followup_detached.sh tail
```

`Ctrl+C` while running `tail` stops only log viewing. To interrupt the pipeline process group:

```bash
bash scripts/training/launch_qwen_fa_followup_detached.sh stop
```

To rerun or resume after a stopped process:

```bash
bash scripts/training/launch_qwen_fa_followup_detached.sh resume
```

Main outputs:

```text
/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_followup_overnight/
  pipeline_events.jsonl
  seed2_decision.json
  final_summary.json
  smoke.complete
  pipeline.complete
```

The formal model/evaluation run directories remain siblings under `/home/hyan/Data/lyricalign/runs`, while generated long data remains under `/home/hyan/Data/lyricalign/derived`.

## Post-execution outcome and review note

The pipeline completed with return code `0`; full R2 seed `20260724` later completed according to the user-provided event log. The exact supplied summary is archived as provisional evidence. Do not treat its `valid_only_boundary_mae_sec` or `song_coverage` as final, and do not infer missing full seed2 or final R2 OOD values. Continue from `20260724_qwen_fa_followup_review_archive.md`.
