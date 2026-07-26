# Next Execution Plan

**Date:** 2026-07-27  
**Goal:**冻结当前 v6 demo 作为基线，使用 MIR-1K 字符级 GT 分离“额外歌词上下文、分离器和串行传播”三类影响，再决定是否设计新的级联方案。

## E0 — Environment and evidence preflight

1. deploy pinned `demucs==4.1.0` in an isolated environment;
2. retain Spleeter as the current baseline;
3. verify Qwen model/revision/checkpoint hashes;
4. run `check_qwen_fa_processor_equivalence.py` on short Chinese, English and
   Japanese samples in the real Qwen environment;
5. do not change `hard_core_forward_overlap_compression_v6` during the
   development comparison.

Guide:

```text
docs/manual/demucs_deployment.md
```

## E1 — Materialize the MIR-1K subset

Run:

```text
scripts/demo/prepare_mir1k_demo_subset.py
```

Frozen split:

```text
8 development
4 held-out
5 spare
seed 20260727
```

Selection uses only duration, character rate, gap structure, annotation
coverage and singer diversity.  Model outputs are forbidden from selection.

## E2 — Prepare separator variants on development only

Run:

```text
scripts/demo/prepare_mir1k_separator_variants.py
```

Inputs:

```text
mix
official MIR-1K vocal channel
Spleeter vocals
Demucs htdemucs_ft vocals
```

The official vocal channel is a diagnostic upper bound, not a deployable
candidate.

## E3 — Independent-window context experiment

Run `run_mir1k_demo_diagnostics.py --experiment context` with:

```text
30 s core
10 s left acoustic context
10 s right acoustic context
future text: 0 / 5 / 15 / 30 s
no serial state propagation
```

GT timestamps define only transcript coverage and evaluated core ownership.
They are never passed to Qwen.

Primary question:

```text
Does extra future text alter raw/processor-decoded timestamps before propagation?
```

After choosing a finite future-text condition, compare matched left-context
lyrics against omitted left-context lyrics.

## E4 — Independent-window separator experiment

Run `--experiment separator` using the frozen context condition.

Primary metrics:

- character onset/offset MAE, median and P90;
- onset and joint tolerance rates at 0.08/0.16/0.24/0.5/1.0 s.

Auxiliary evidence:

- raw confidence/margin/entropy;
- processor adjustment;
- separator structural quality;
- blind listening;
- wall time and peak GPU memory.

Select at most one deployable separator on development data.

## E5 — Current v6 propagation diagnosis

Run `--experiment serial` on the surviving input candidates.

Compare stages:

```text
raw
processor-decoded
selected
final committed
```

Decision patterns:

- independent poor -> model/audio/context dominates;
- independent good, serial raw poor -> cursor/candidate feedback dominates;
- selected good, final poor -> forward overlap compression is damaging;
- Demucs helps independent but not serial -> local evidence improves while
  propagation remains the main limitation.

Do not add a new cascade rule before this attribution is available.

## E6 — Freeze and held-out confirmation

Write a frozen decision JSON containing all model, separator, context and
window identities.  Then prepare and run exactly one held-out configuration.
Do not retune after viewing held-out results.

Canonical detailed protocol:

```text
docs/sessions/20260727_mir1k_demo_diagnostic_experiment.md
```

## Deferred

Until E3–E6 are complete, do not:

- use full-song confidence as a segmentation oracle;
- add confidence anchors without calibration evidence;
- redesign soft commit or overlap reconciliation;
- expand LoRA scope or retrain based on demo listening;
- make multilingual singing claims from Chinese MIR-1K results;
- use MIR-1K development or held-out songs for training/checkpoint selection.
