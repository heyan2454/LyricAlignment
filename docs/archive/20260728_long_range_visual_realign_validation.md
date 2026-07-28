# 2026-07-28 Long-Range Visual / Detector / Stable / Deferred Validation

## Scope

This archive implements the next executable experiment suite for extending a
short-range Qwen Forced Aligner to full songs. It covers:

- dynamic formal discovery of every prepared multilingual Test Demo;
- path-derived short-hash Demo identities;
- RAW/B0/B1/B2/B3 long-serial baselines;
- corrected S1/S2/S3 stable-anchor shadow alignments;
- R0/R1/R2/R3 immediate/deferred/combined realign shadow alignments;
- all-item timeline, signed-error, duration-distribution and inconsistency plots;
- all-Demo multi-way K-song comparison videos and current-behavior videos;
- YAML-backed one-click smoke/formal execution and resolved configuration;
- live terminal/status-page monitoring;
- manifest-bounded total/grouped summaries and compact evidence;
- clean-control counterfactual production-gate analysis;
- layered inference/evaluation cache identities;
- overwrite cleanup and stale-item removal helpers;
- complete session rationale, accepted/deferred/rejected ideas and E1–E7 plans.

Canonical B2 is not overwritten. Stable and realign variants remain shadow
experiments.

## Static and regression validation

```text
python -m compileall -q src scripts tests                         passed
bash -n for every scripts/**/*.sh                                passed
all locally runnable tests                                      186 passed
CLI --help smoke for pipeline/manifest/visual/render/status      passed
cleanup derived/stale synthetic smoke                            passed
synthetic all-item visual/summary/collector/status workflow      passed
synthetic FFmpeg generation of all four Demo video types         passed
```

Locally runnable test command:

```bash
PYTHONPATH=src pytest -q \
  --ignore=tests/test_audio_contract.py \
  --ignore=tests/test_m4singer_preparation.py \
  --ignore=tests/test_mir1k_partial_align.py
```

The three ignored existing collection targets require `pypinyin`, which is not
installed in the archive container. Every collected and executed test passed.

## Cache validation

The baseline inference request excludes GT and metric state. It includes audio,
lyrics, model/revision/checkpoint, variant and the full resolved serial behavior
configuration.

Evaluation identity is separate and contains:

- inference request hash;
- GT content hash and availability;
- boundary metric schema;
- stable-segment metric schema.

Changing GT therefore refreshes GT-derived fields and artifact summaries without
calling model inference again. Changing serial behavior invalidates inference.
Auxiliary detector/stable/realign stages retain their own request identities.

## Result-identity validation

- Every summary and evidence pass starts from the frozen
  `experiment_manifest.jsonl`.
- Item directories not in the manifest are reported as stale and excluded.
- `gt_available` means a GT file was available, independently of whether any GT
  error span exceeded the configured threshold.
- Clean controls are reported separately from automatic and GT-oracle cases.
- Clean controls remain ineligible for actual writeback, while
  `would_pass_non_gt_gate` and counterfactual false accepts are still measured.
- Reports include total and grouped rows for dataset/profile/language/unit mode/
  duration bucket/variant.

## Demo validation contract

Formal does not hard-code 17+6+6+6. It discovers all currently prepared Demo at
runtime and freezes the discovered inventory. Every Demo is intended to receive:

```text
comparison_main_2x2.mp4     RAW / B0 / B1 / B2
comparison_stable_2x2.mp4   B2 / S1 / S2 / S3
comparison_realign_2x2.mp4  R0 / R1 / R2 / R3
behavior_current.mp4        B2 karaoke plus window/model behavior
```

No ordinary unpaired individual raw/baseline/current video is generated. The
pipeline does not impose human labels; it only creates an optional
`visuals/HUMAN_REVIEW.md` entry.

## One-click and monitoring validation

Entrypoints:

```bash
bash scripts/demo/run_inline_realign_smoke.sh
bash scripts/demo/run_inline_realign_formal.sh
```

Status:

```bash
python scripts/demo/watch_inline_realign_status.py <OUT_ROOT>
```

The pipeline tees child-process output live to the terminal and stage logs.
`live_status.json` tracks pipeline stages; `experiment_live_status.json` tracks
current item and branch.

## Evidence-size validation

The canonical collector defaults to an 8 MiB cap and four cases per item from
the pipeline. It uses:

```text
full → anomaly → severe → minimal
```

It does not include audio, video, model weights, complete logs or full alignment
payloads. It retains configuration, manifests, status, total/grouped summaries,
bounded diagnostic cases, visual/video indexes and compact experimental branch
summaries. Large item-specific evidence should be collected separately only
when a later review identifies a concrete need.

## Validation limits

This archive environment does not contain the server Qwen snapshot, intended R2
checkpoint or the real 35-song Test Demo/MIR-1K/M4Singer assets. Therefore this
validation does not claim model-quality improvement and does not provide a real
GPU smoke/formal result.

The following remain server experiments:

- complete discovery of the current 17+6+6+6 Demo inventory;
- multilingual Qwen inference and Japanese tokenization;
- readability and storage cost of all full-length comparison videos;
- RAW/B0/B1/B2/B3 GT metrics;
- zero/short-duration distributions and detector performance;
- S1/S2/S3 benefit and frozen-anchor seam risk;
- R1/R2/R3 benefit and production-gate false accepts;
- whether multi-scale inconsistency predicts timing drift;
- whether bounded final sweep handles only a small residual set.

R1/R2/R3 are reproducible shadow simulations over a completed serial trace.
They do not yet write corrections into the live online serial cursor. The target
algorithm remains immediate bounded repair, anchor-recovered delayed repair and
a final sweep over only unresolved bounded intervals—not whole-song Qwen
realignment.
