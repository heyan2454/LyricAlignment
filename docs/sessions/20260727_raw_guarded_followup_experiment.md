# Raw + guarded realignment follow-up experiment

## Scope

The current best initial timestamp output is the R2 Qwen raw timestamp argmax.
The next question is not whether a global decoder can improve every boundary;
it is whether a non-GT detector can identify the rare harmful regions and a
strict verifier can repair them without damaging correct regions.

This document freezes the next development protocol. MIR-1K development data
may tune it. MIR-1K held-out is run once after all thresholds are frozen.

## Context-range definition

`exact`, `+2`, and `+4` refer to extra lyric units around the same anchored
repair interval. They are not seconds.

The current `matched_context` implementation expands **both** sides together:

- text input changes from the exact anchor span to the anchor span plus 2/4
  lyric units;
- audio crop changes to the predicted start/end of those same added units.

Therefore it is not a text-only mismatch experiment. However, the expanded
audio endpoints are derived from baseline predictions. If nearby baseline
boundaries are inaccurate, the expanded audio/text pair can still be poorly
matched. Every local trial now records `context_audit` with text indices, audio
crop anchor indices, and whether audio/text were expanded together.

`+4` stays outside the production demo. It may be retained only as an offline
mechanism diagnostic.

## Metrics

For tolerances 80, 160, and 240 ms, report separately:

1. **Detector PRF**
   - positive prediction: a unit belongs to a naturally detected region;
   - positive truth: max onset/offset absolute error exceeds the tolerance.
2. **False detection without modification**
   - affects compute and warning rate, but not alignment accuracy.
3. **False detection with modification**
   - the important safety failure.
4. **Intervention correction PRF**
   - TP: an erroneous unit is meaningfully modified and becomes correct;
   - FP: a meaningful modification does not correct an erroneous unit;
   - FN: an erroneous unit remains uncorrected.
5. **Harm metrics**
   - previously correct units modified;
   - previously correct units made incorrect or worsened;
   - erroneous units worsened.
6. **Runtime**
   - detected cases per song minute;
   - exact/+2 calls per song minute;
   - incremental wall time and RTF.

Accuracy over all units is not a useful detector metric because the raw error
prevalence is low.

## Experiment sequence without a Cartesian product

### E0 — Raw baseline census

Run all MIR-1K development songs with one frozen input configuration:

- Demucs vocals;
- 30 s core;
- R2 step 750;
- raw timestamp decoder;
- no realignment.

Record per-unit GT errors, structural flags, cross-window disagreement,
first-failure time, and recovery distance.

### E1 — Detector trigger ablation

Using E0 outputs only, evaluate each trigger independently and cumulatively:

- zero/negative duration;
- severe duration compression;
- frozen-prefix conflict;
- boundary stacking;
- cross-window disagreement peak;
- raw/official movement, retained only as a diagnostic feature;
- confidence margin and entropy thresholds.

Report PRF and unique-error discovery for each trigger. Do not run the model
again for this stage.

### E2 — Repair and verifier ablation

Run only detected development cases:

- A: no modification;
- B: exact local inference + structural safety gate;
- C: exact local inference accepted only when matched `+2` inference agrees;
- D: C plus maximum boundary-change cap.

The production candidate is D. `+2` is a verifier, not an automatic fallback.
The exact output is the only output eligible for writing back.

### E3 — Candidate upper bound

Use GT only after inference to calculate:

- exact oracle improvement rate;
- matched +2 oracle improvement rate;
- best-of-exact/+2 oracle rate;
- automatic verifier rate.

If the oracle is weak, the local inference mechanism is the limitation. If the
oracle is strong but the automatic verifier is weak, improve selection rather
than adding a larger model.

### E4 — Clean-control harm

Sample GT-correct regions from the same songs:

- normal detector path;
- forced local inference with all safety gates active;
- forced write-back with gates bypassed, diagnostic only.

This separates harmless false alarms from actual false modification.

### E5 — Long-sequence propagation

Use natural MIR-1K songs and M4Singer same-song 60/120/240 s sequences. Report:

- first severe error;
- recovery time/units;
- cursor skip/repeat;
- overlap compression and zero duration;
- whether guarded repair shortens recovery distance.

Synthetic seams must be marked and excluded from the primary internal metric.

### E6 — External-data decision

Do not add a dataset only to increase item count. Add one only if E0–E5 show a
missing error type or insufficient positive cases.

Preferred order:

1. OpenCPOP character-aligned material, if the available annotation can be
   converted without ambiguous syllable-to-character mapping;
2. additional manually checked MIR-1K songs for real demo-domain positives;
3. M4Singer mechanism-matched corruptions derived from observed MIR-1K errors.

M4Singer has many items but few raw errors and strong within-song dependence.
Sampling and confidence intervals should use song as the grouping unit. English
or DALI data should not be mixed into the primary Chinese detector experiment.

## Freeze rule

Choose detector triggers, agreement tolerance, and boundary-change cap on
MIR-1K development only. Write a configuration identity before held-out. Run
held-out once; no threshold changes after seeing it.

## Implemented entries

The protocol is executable through:

```bash
bash scripts/demo/run_raw_guarded_experiment_suite.sh
```

Analysis outputs:

```text
mir1k/analysis/e0_raw_baseline_census.json
mir1k/analysis/e1_detector_trigger_ablation.json
mir1k/analysis/e2_guard_ablation.json
mir1k/analysis/e3_repair_oracle.json
mir1k/analysis/e4_clean_control.json
mir1k/analysis/experiment_suite_summary.{json,md}
m4singer_long/bucket_{60,120,240}/e5_long_propagation.json
```

E2 reports both independent-case evaluation and a severity-first global
non-overlap replay. Only the latter matches the production intervention policy.
E4 `clean_forced_repair` now genuinely bypasses anomaly reduction and context
agreement while still requiring a spliceable non-GT candidate; it is a harm
upper-bound diagnostic and must never be enabled in the demo.
