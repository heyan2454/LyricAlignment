# 17. Next-Round Experiment Plan — Expanded Real-GT Raw Catastrophic Analysis and Recovery

**Status:** planning document only; this patch does **not** create the next run/session directory.  
**Execution chain:** current archive + this patch -> Codex provenance/data review + reviewed implementation plan -> OpenCode creates a new session/OUT_ROOT and executes.  
**Primary focus:** Raw catastrophic-error reliability and real-GT recovery.  
**Non-priority:** further H/P/V/S/O/RO feature-family expansion.

---

# 1. Next-session rule

When implementation/experiment execution begins, OpenCode must create a **new session folder / OUT_ROOT**. Do not write new run artifacts into the 2026-08-08/09/10 supplement runs.

Suggested semantic name (timestamp may differ):

```text
runs/research_transition_recovery_detector_20260810_realgt_raw_catastrophic_recovery/
```

Before any experiment starts, copy into that new session's metadata/plans area:

- this experiment plan;
- Codex's GT-lineage/data-capacity review;
- Codex's reviewed implementation plan;
- exact git commit / working-tree diff identity;
- frozen dataset/split manifest hashes.

The new session directory should be created **during the next execution round**, not by this documentation patch.

---

# 2. High-level questions

The next round must answer four questions.

## Q1 — Data scale

How large can the real-GT experiment be expanded while remaining source-song-disjoint, provenance-clean, and within the compute budget?

## Q2 — Raw catastrophic reliability

Raw has high pooled separability under real GT. Does it also detect the **rare very large errors**, or can the aligner be confidently wrong when it jumps to the wrong occurrence or collapses over a long interval?

## Q3 — Recovery capability

If a window is genuinely wrong under real GT, can a small set of mechanistically distinct recovery interventions repair it without using GT as input?

## Q4 — System recovery

Once recovery capability is established, can the frozen Raw detector trigger recovery while avoiding harmful retries/writebacks on clean windows?

---

# 3. Stage 0 — Codex audits decide the actual scope

Before OpenCode execution, Codex must complete Document 16's audits.

The implementation plan must freeze:

- maximum safe real-GT cohort;
- R2 train-overlap exclusion policy;
- development/formal split;
- required historical experiments to reaggregate/rerun;
- cache reuse plan;
- exact Raw feature schema to retain;
- real-GT canonical mapping and denominator policy;
- total runtime budget.

## Stop condition

OpenCode must not begin detector/recovery experiments if:

- evaluation songs overlap R2 training and are still being presented as held-out;
- real-GT mapping provenance is unknown;
- unlabeled units are silently assigned correctness labels;
- the new session's split manifests are not frozen.

---

# 4. Experiment A — Expand and finalize real-GT baseline

## 4.1 Reason

The 9-song real-GT correction is decisive but small. The exploratory ~60-song result strongly suggests the dataset can support a much larger evaluation. Before studying rare failures, their prevalence must be measured on the largest safe cohort.

## 4.2 Design

Using the capacity audit, build the largest safe real-GT evaluation cohort(s).

For each source song and each relevant baseline route, record:

- total canonical units;
- real-GT labeled units;
- unlabeled units;
- <=50 ms (optional precision diagnostic);
- <=100 ms;
- <=250 ms;
- <=500 ms;
- <=1 s;
- >1 s, >2 s, >5 s, >10 s counts;
- MAE / median / p90 / p99 error;
- invalid/inversion/zero-duration if applicable;
- source-song identity and split role.

### Required baseline routes

At minimum, if predictions exist or can be cheaply reproduced:

```text
T1
T2
T3
full-song
```

If historical GT audit shows a route is no longer meaningful, Codex may remove it with a written reason.

## 4.3 Purpose

- obtain publication-credible normal-case performance;
- estimate catastrophic-error prevalence;
- re-evaluate old Transition conclusions under real GT;
- identify the correct baseline for subsequent Raw/recovery experiments.

## 4.4 Expected results and interpretation

### Outcome A1 — serial remains clearly better than full-song

Supports a real long-form/serial benefit independent of the old GT mistake.

### Outcome A2 — T1/T2 become indistinguishable

Supports simplifying the transition policy; T2 may remain nominal baseline without claiming mechanism superiority.

### Outcome A3 — old serial advantage disappears or reverses

The old Transition story was largely a GT artifact. Freeze the best real-GT baseline and retire the old comparison.

### Outcome A4 — catastrophic failures are concentrated in a few songs

Strengthens the rare-collapse framing and motivates song/window-level evaluation rather than only pooled unit metrics.

---

# 5. Experiment B — Raw score versus real error magnitude

## 5.1 Reason

High pooled AUROC can hide failures in the far error tail. A catastrophic occurrence jump may produce a sharp, confident posterior at the wrong time.

## 5.2 Inputs

Use only the frozen **Raw feature family R** from the corrected committed observation.

Do not add H/P/V/S/O/RO in this round unless Codex finds that the current R artifact itself depends on a missing component.

## 5.3 Error-magnitude bins

Pre-register bins on labeled units:

```text
<=100 ms
100-250 ms
250-500 ms
0.5-1 s
1-2 s
2-5 s
5-10 s
>10 s
```

If a bin is too sparse, report it and merge only in an auxiliary view; preserve the original counts.

For each bin report:

- units;
- songs;
- windows;
- R score median / p10 / p25 / p75 / p90;
- ACCEPT / UNCERTAIN / REJECT fractions under frozen working points;
- recall for >1 s / >2 s / >5 s / >10 s.

## 5.4 Score–severity relationship

Produce both pooled and per-song analyses of:

```text
R score vs absolute GT error
```

The goal is not to assume linearity. Explicitly inspect whether the rightmost error tail becomes **lower-confidence-to-detector** (dangerous false-confidence collapse).

Suggested summaries:

- monotonic trend by bins;
- Spearman correlation as auxiliary only;
- fraction of catastrophic errors below Safe-accept threshold;
- worst catastrophic false negatives.

## 5.5 Purpose

Determine whether Raw is merely good at ordinary boundary uncertainty or is actually a reliable safeguard against the largest product failures.

## 5.6 Interpretations

### Outcome B1 — Raw risk rises monotonically and almost all >5s errors are caught

Strong evidence that the detector can be simplified to Raw only. Focus later work on recovery, not more feature engineering.

### Outcome B2 — Raw catches 0.25–2s errors but misses >5s confident jumps

Critical scientific result: **confident catastrophic misalignment**. Mine these cases and let their failure mechanism determine any future complementary signal.

### Outcome B3 — Raw is weak across all rare bins once source-song leakage is removed

The high pooled AUROC was caused by concentration/leakage. Do not deploy the current Raw detector; redesign evaluation before adding features.

---

# 6. Experiment C — Catastrophic event/window/song decomposition

## 6.1 Reason

Unit-level AUC and unit recall are not aligned with product risk. A song can be unusable even if only a small percentage of all dataset units are wrong.

## 6.2 Frozen event definitions

Codex should verify thresholds against data scale, but use simple pre-registered definitions such as:

### Catastrophic unit

Separate reports for:

```text
>1s
>2s
>5s
>10s
```

### Catastrophic run

Contiguous same-song canonical units satisfying a chosen large-error threshold. Report run length and time span.

### Catastrophic window

A 60-s decision window satisfying one or more frozen conditions, e.g.:

- >=N units >1s;
- >=M units >5s;
- very large median/max error;
- a long contiguous catastrophic run.

Use one primary definition and auxiliary sensitivity checks; do not grid search definitions.

### Catastrophic song

Song-level real-GT accuracy/error falls below a frozen threshold or contains a catastrophic run/window.

## 6.3 Detector metrics

For each event level:

- event recall: did R flag at least one unit/window?
- 25/50/75/100% run coverage;
- first-alert latency relative to catastrophic onset;
- clean-window false alarm rate;
- maximum accepted catastrophic run;
- catastrophic-song early-warning rate after first 1/2/3 windows.

## 6.4 Purpose

Decide whether the product should use a unit detector, window veto, song-level safeguard, or a combination.

---

# 7. Experiment D — High-confidence catastrophic false-negative mining

## 7.1 Reason

These cases are the most valuable failures if they exist.

## 7.2 Selection

After predictions and scores are frozen, select cases satisfying conditions such as:

```text
GT error > 1s / 2s / 5s
AND detector decision = ACCEPT
```

This is a **diagnostic mined set**, not an unbiased formal set.

## 7.3 Automatic decomposition fields

For each case save:

- source song / window / canonical unit;
- GT and predicted time;
- absolute/signed error;
- R score and all component R features;
- top1 probability;
- entropy;
- margin;
- duration/gap/overlap/compression features;
- serial cursor/head context;
- window-relative position;
- query unit range;
- whether the wrong prediction resembles an approximately constant temporal shift;
- whether neighboring units form a coherent jump/run;
- repeated-lyric/occurrence metadata if objectively derivable;
- silence/seam proximity;
- preceding error state.

## 7.4 Simple failure-shape taxonomy

Keep the first taxonomy intentionally small and objective:

```text
isolated local shift
coherent local/global shift
occurrence-like large jump
startup/head failure
tail/query-range failure
compression/inversion
other
```

Codex may refine definitions if repository evidence supports a better objective rule, but must freeze rules before counting prevalence.

## 7.5 Purpose

Identify exactly where Raw's apparent sufficiency breaks. Only these blind spots should motivate future extra signals.

---

# 8. Experiment E — Leave-one-catastrophic-song-out Raw validation

## 8.1 Reason

If most Unsafe units come from a few songs, random or ordinary source-song splits can still make pooled AUC look deceptively strong.

## 8.2 Design

For each catastrophic song with enough labeled errors:

1. remove the entire source song from train/model/threshold selection;
2. fit/calibrate R on the remaining development songs;
3. evaluate the held-out catastrophic song;
4. repeat across catastrophic songs.

If the number of catastrophic songs is too small, use grouped bootstrap / leave-one-out diagnostic rather than pretending statistical power exists.

Report:

- >250 ms, >1 s, >2 s, >5 s recall;
- catastrophic-window recall;
- clean-unit/window false reject;
- threshold transfer stability;
- macro across held-out catastrophic songs.

## 8.3 Interpretation

Strong held-out performance supports Raw as a general safeguard. Collapse on unseen catastrophic songs means the pooled score was learning song/failure-family identity rather than universal uncertainty.

---

# 9. Experiment F — Recovery capability on real-GT-confirmed errors

## 9.1 Reason

Previous recovery evaluation was contaminated by wrong GT and by retrying windows that may have been correct. Recovery therefore needs a clean capability experiment before detector-triggered closed loop is judged.

## 9.2 Oracle trigger boundary

GT may be used **only to select real error windows and evaluate before/after results**.

GT must not be used as:

- recovery input;
- cursor/head supplied to the algorithm, except in a separately named oracle upper-bound control;
- feature;
- route decision at deployment-like evaluation.

## 9.3 Case sampling

Prioritize genuine severe errors from the expanded real-GT cohort:

```text
>1s
>2s
>5s
catastrophic runs/windows
catastrophic songs
```

Include a smaller clean-window control cohort to measure harm.

Use all available severe cases if they are rare rather than arbitrary case caps.

## 9.4 Minimal recovery intervention set

Avoid Cartesian search. Freeze one implementation per mechanism.

### F0 — same-input retry control

Purpose: show whether repeating an equivalent deterministic request can ever help.

### F1 — head/cursor local search

Small bounded alternatives around current cursor/head, e.g. a few unit offsets. Exact offsets should be selected once by Codex based on the existing serial contract, not tuned per song.

### F2 — query-dosage adjustment

One smaller-query and one larger-query alternative around the baseline request.

### F3 — audio-context shift/expand

One left-context and one right-context/window adjustment preserving causality/lookahead constraints.

### F4 — sparse/slot local recovery (conditional)

Include if the current slot/sparse implementation is sufficiently mature and Codex confirms it can be executed without opening a large new engineering branch. It should localize responsibility to the suspect units rather than realign the whole query.

Codex may replace one intervention if it proves redundant/unimplementable, but must preserve mechanistic diversity.

## 9.5 Metrics

For every error window and intervention:

- before/after <=100/250/500/1000ms;
- before/after MAE/median/max;
- catastrophic-unit/run counts;
- recovered-to-<=250ms fraction;
- severe->mild transition rate;
- worsened rate;
- invalid/no-solution rate;
- runtime / additional forwards.

Primary recovery success should be a frozen window-level criterion such as:

> severe/catastrophic window becomes overwhelmingly <=250ms without creating a new large-error run.

Codex should define the exact threshold before execution and report continuous metrics regardless.

## 9.6 Purpose

Answer the pure capability question:

> If we know a real error exists, can a deployment-compatible intervention fix it?

## 9.7 Interpretation

### Outcome F1 — at least one targeted intervention reliably repairs severe errors

Proceed to detector-triggered recovery with that intervention.

### Outcome F2 — same retry fails but cursor/query/context interventions help

Confirms that recovery must alter the conditioning state rather than simply repeat inference.

### Outcome F3 — all interventions usually fail on catastrophic occurrence jumps

Recovery is an aligner limitation for that failure family; consider slot/occurrence search or safe abstention rather than blind writeback.

### Outcome F4 — interventions frequently damage clean controls

Recovery needs strict gating and rollback semantics even if capability on errors is good.

---

# 10. Experiment G — Detector-triggered real-GT recovery

Run this only after Experiment F identifies at least one recovery intervention with non-trivial real-error capability.

## 10.1 Pipeline

```text
serial baseline
 -> frozen Raw score
 -> ACCEPT / UNCERTAIN / REJECT or window trigger
 -> selected recovery intervention
 -> score recovered output again
 -> guarded writeback or abstain
 -> continue serial state
```

## 10.2 Required comparisons

- baseline without recovery;
- oracle-triggered recovery capability (Experiment F reference);
- Raw-triggered recovery;
- clean controls.

## 10.3 Metrics

- true catastrophic trigger recall;
- clean-window trigger rate;
- recovery attempt count;
- successful real-error recovery;
- false-positive retry harm;
- harmful writeback count;
- rollback count;
- final whole-song <=100/250/500/1000ms;
- catastrophic-song success/failure;
- additional inference cost.

## 10.4 Safety invariant

A failed/no-solution/worse retry must not overwrite a better serial state. Implement and test fallback/transaction semantics before closed-loop evaluation.

---

# 11. Experiment H — Historical GT correction reruns selected by Codex

This is a **dynamic stage**. Do not pre-run every historical experiment.

After Document 16 audit, Codex will populate a rerun manifest containing only load-bearing contaminated results.

Priority rule:

### P0

Results that directly determine the new baseline or Raw/recovery interpretation:

- real-GT T1/T2/T3/full-song;
- current Raw training/thresholds on expanded real GT;
- recovery capability/closed loop.

### P1

Historical results likely to affect next-stage method choices:

- slot/non-slot real-GT comparison if old evidence was contaminated;
- head/cursor strategy if its claimed alignment benefit used wrong GT;
- oracle recovery if still useful as a capability bound.

### P2

Invalid-input/mutation or propagation experiments whose quantitative conclusions will be cited in future work.

### P3

Old H/P/V/S/PR feature experiments that are no longer load-bearing. Prefer RETIRE/KEEP-negative over rerunning unless provenance audit shows a key conclusion must be repaired.

---

# 12. Optional low-cost experiments after P0/P1

These may run only if mandatory stages are complete and budget remains.

## 12.1 H1 head strategy under real GT

Structural exploration suggested H1 reduces head/query pollution. Evaluate baseline vs H1 with real GT on identical songs. Do not infer accuracy from pollution counts alone.

## 12.2 Sub-grid timestamp precision

Use existing posterior caches to compare grid argmax vs one frozen local posterior interpolation/expectation rule. Primary metrics should be <=25/50/100ms on already non-catastrophic regions. This is a precision experiment, not a catastrophic-failure fix.

## 12.3 Sparse/slot main comparison

If Codex's historical audit shows the existing slot/non-slot conclusion is contaminated and implementation is mature, run a small real-GT paired comparison on:

- normal songs;
- catastrophic songs;
- repeated/ambiguous difficult cases.

This can become a future mainline only if it reduces catastrophic failure, not merely average error by a few milliseconds.

---

# 13. Metrics and denominator rules

## 13.1 Frame/unit/event distinction

Do not mix:

- per-unit timing correctness;
- contiguous catastrophic-event capture;
- window trigger/recovery success;
- song-level usability.

Every table must state its denominator.

## 13.2 Real-GT missingness

Always report:

```text
total canonical units
real-GT labeled units
unlabeled units
```

Unlabeled units do not enter Safe/Grey/Unsafe correctness denominators.

## 13.3 Source-song macro

Report both pooled unit metrics and source-song macro/paired results. Rare catastrophic songs must not be diluted by easy songs.

## 13.4 Thresholds

Use validation-only discrete thresholds/order statistics. Report achieved numerator/denominator rather than nominal labels such as R95 when the finite sample cannot meet them exactly.

---

# 14. Reproducibility and runtime requirements

The implementation plan must freeze:

- source manifests and hashes;
- GT overlay and clock mapping version;
- R2 checkpoint identity;
- raw feature schema;
- split manifests;
- random seeds;
- cache keys;
- overwrite/append policy;
- resume behavior;
- per-stage logs;
- failure manifests;
- exact commands.

Prefer cache/reaggregation. Do not recompute model forwards when existing evidence is identity-equivalent.

Maintain the project-wide bounded runtime discipline and avoid Cartesian products. If the safe expanded cohort is too large for one run, use deterministic staged expansion with identical frozen settings rather than tuning on partial formal results.

---

# 15. Suggested next-session artifact layout

Create this only when the next execution begins:

```text
<NEW_SESSION_ROOT>/
  00_meta/
    SESSION_META.json
    copied_plan_17_NEXT_ROUND_...md
    CODEX_GT_LINEAGE_AND_DATA_CAPACITY_REVIEW.md
    CODEX_REVIEWED_IMPLEMENTATION_PLAN.md
    DATA_CAPACITY_AUDIT.json
    GT_LINEAGE_AUDIT.json
    SPLIT_MANIFESTS/
    RUNTIME_BUDGET.json
    FAILURES.jsonl

  01_realgt_baseline/
    REALGT_TRANSITION_SUMMARY.json
    REALGT_PER_SONG.json
    REALGT_PER_WINDOW.json

  02_raw_catastrophic/
    RAW_MAGNITUDE_DECOMPOSITION.json
    RAW_SCORE_SEVERITY.jsonl
    CATASTROPHIC_EVENTS.jsonl
    CATASTROPHIC_FALSE_NEGATIVES.jsonl
    CATASTROPHIC_LOSO.json

  03_recovery_capability/
    REAL_ERROR_WINDOWS.jsonl
    RECOVERY_INTERVENTIONS.jsonl
    RECOVERY_CAPABILITY_SUMMARY.json
    CLEAN_HARM_CONTROLS.json

  04_recovery_closed_loop/
    RAW_TRIGGERED_RECOVERY.jsonl
    WRITEBACK_STATE_AUDIT.json
    CLOSED_LOOP_REALGT_SUMMARY.json

  05_historical_corrections/
    RERUN_MANIFEST.json
    ... only Codex-selected load-bearing corrections ...

  09_reports/
    NEXT_ROUND_REPORT.md
    NEXT_ROUND_REPORT.json
    NEGATIVE_RESULTS.md
    EVIDENCE_PACK_INDEX.json
```

---

# 16. Completion conditions

The next round is complete only when:

1. data capacity and R2 train-overlap are known;
2. real-GT baseline is expanded to the largest safe cohort chosen by the audit;
3. T1/T2/T3/full-song load-bearing comparisons are corrected or explicitly retired;
4. Raw is decomposed by error magnitude and catastrophic event/window/song;
5. high-confidence catastrophic false negatives are enumerated;
6. catastrophic-song held-out/generalization analysis is completed as far as the data support;
7. recovery capability is evaluated on real-GT-confirmed errors;
8. detector-triggered recovery is run only if capability is demonstrated;
9. harmful retry/writeback is explicitly measured and transaction-safe fallback is verified;
10. Codex-selected high-risk historical conclusions are corrected, rerun, or retired;
11. all reports use labeled/unlabeled denominators correctly.

The round may legitimately conclude that:

- Raw is sufficient for catastrophic detection;
- Raw is confidently wrong on a specific failure family;
- recovery works only for some error families;
- recovery cannot repair occurrence-level collapse and should abstain;
- old Transition/slot/propagation conclusions change after real-GT correction.

Negative results are valid. Silent use of the old GT is not.

