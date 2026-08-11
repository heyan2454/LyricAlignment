# 16. GT Contamination Audit and Data-Expansion Protocol for Codex

**Purpose:** provide Codex with a decision framework rather than a pre-decided rerun list. Codex must verify provenance in code/artifacts and then determine what to keep, reaggregate, rerun, or retire.

---

# 1. Required output from Codex

Before implementing the next experimental round, Codex must create a review document that contains two machine-checkable inventories:

1. **GT lineage / historical experiment inventory**;
2. **data capacity / split / leakage inventory**.

Recommended outputs:

```text
docs/research_transition_recovery_detector_20260808_correction/
  19_CODEX_GT_LINEAGE_AND_DATA_CAPACITY_REVIEW_20260810.md
  20_CODEX_NEXT_ROUND_IMPLEMENTATION_PLAN_20260810.md
```

The exact numbering may be adjusted if another document is inserted, but these must remain in the current documentation tree. They are not run/session outputs.

---

# 2. Historical GT lineage table

Codex must trace each historical conclusion to the actual GT/evaluation source used by the script/artifact, not infer from document wording.

Required columns:

```text
experiment_id / artifact
research question
code entry point
prediction source
GT source
GT transformation / clock mapping
GT use: label | metric | selection | trigger | recovery-improvement | none
source-song split
current risk level
Codex evidence for classification
action = KEEP | REAGGREGATE | RERUN | RETIRE | PROVENANCE_UNKNOWN
required rerun scope
notes
```

## 2.1 Action definitions

### KEEP
No affected correctness conclusion depends on the synthetic-uniform timing axis, or the result is purely structural/runtime and still valid.

### REAGGREGATE
Predictions/evidence are valid and already stored; only GT labels/metrics/selection need to be recomputed with real GT.

### RERUN
The wrong GT affected execution-time behavior (e.g. detector-triggered route/recovery decisions), training labels that generated model artifacts, or request selection in a way that cannot be corrected post hoc.

### RETIRE
The historical experiment answers a superseded question or cannot be made comparable without disproportionate work. Preserve it for history but do not cite its quantitative conclusion.

### PROVENANCE_UNKNOWN
Codex cannot prove the GT path from repository/artifacts. This is not an acceptable final state if the experiment is load-bearing; continue tracing until resolved or explicitly retire it.

---

# 3. Mandatory high-risk historical groups to audit

The following groups are presumed **high risk** until Codex proves otherwise.

## 3.1 Transition T0/T1/T2/T3/full-song comparisons

Audit:

- exact GT used for 100/250/500/1000-ms metrics;
- candidate selection;
- wrong-committed counts;
- song-level paired comparisons;
- any mechanism/product candidate decision.

Expected action if stored predictions exist: **REAGGREGATE with real GT**.

Do not retain old synthetic-uniform deltas as final results.

## 3.2 Correctness detector generations

Audit all generations, including legacy/unit assessor/Detector V2/V3/V4 branches where applicable:

- training labels;
- validation/model-selection labels;
- threshold labels;
- interval labels;
- AUC/AUPRC;
- SA60/SA80/R95;
- cross-domain evaluations.

If a detector was trained on synthetic-uniform Safe/Unsafe labels, its model artifact cannot be corrected by metric-only relabeling. Mark **RERUN** if the detector is still needed; otherwise **RETIRE**.

For the current next round, only R/raw needs to be retained/retrained under real GT.

## 3.3 Recovery / oracle recovery

Audit:

- how recovery windows were selected;
- whether GT influenced the retry request itself or only evaluation;
- how “improved/worsened/recovered” was defined;
- how O0/O1/O2 oracle results were scored;
- whether writeback/next-state execution was conditioned on old detector labels.

Expected actions may differ:

- stored before/after predictions -> **REAGGREGATE**;
- detector-triggered route under wrong labels -> **RERUN**;
- old retry set not representative of real errors -> **RETIRE as capability estimate**, preserve as harm/control evidence.

## 3.4 Propagation / PR

Trace whether episode labels such as:

```text
persistent
amplifying
occurrence_jump
recovered
high/medium/low risk
```

were determined from:

- injected state/cursor identity only;
- model-native structural state;
- synthetic-uniform timing correctness;
- a mixture.

If timing correctness materially defines the episode target, old PR target/model metrics are contaminated and require **RERUN or RETIRE**.

If the episode target is independent of GT, the negative result may be **KEEP**, but state this explicitly.

## 3.5 Slot / sparse-slot / full-slot vs non-slot comparisons

Separate:

- structural validity/coverage/query ownership -> may be KEEP;
- timing accuracy/Unsafe rates -> REAGGREGATE or RERUN depending execution;
- route decisions based on detector -> RERUN if labels changed execution.

This area is important because slot/sparse-query may become a future main method; do not let contaminated old metrics silently support it.

## 3.6 Invalid-input / mutation experiments

For extra/missing/replace/repeated/no-match/crop/cursor perturbations:

- mutation identity and severity construction can often be KEEP;
- timing degradation measured against synthetic-uniform GT is contaminated;
- detector capture rates trained/labeled by old GT are contaminated;
- purely mutation-known “was the expected text changed?” labels are independent of timing GT.

Codex should split each conclusion rather than mark the whole experiment valid/invalid.

## 3.7 Demo and multilingual evidence

No-GT Demo visual/objective structural evidence should remain separate from GT-backed timing claims.

Audit whether any Demo score silently borrowed the synthetic timeline. Do not force incomparable Japanese-word, English-word, and Chinese-character units into a single timing metric without explicit unit schema.

---

# 4. Lower-risk groups to verify and likely KEEP

Codex should still verify, but these are expected to be lower risk:

- original R2 LoRA validation if it directly used original M4Singer annotations;
- model-forward correctness, cache identity, runtime, memory and deterministic-equivalence tests;
- raw/official decoder structural differences independent of GT;
- hidden/posterior extraction correctness;
- mutation construction metadata independent of timing quality;
- H0/H1 structural head/query pollution counts that do not use GT;
- silence planner structural behavior independent of timing-error labels.

Any claim that these structural changes **improve alignment quality** still requires real-GT evaluation.

---

# 5. Data-capacity and split audit

The user believes the current dataset should support further expansion. Codex must verify and quantify this rather than hard-code the existing 9/60-song subsets.

## 5.1 Required source inventories

Locate and record:

1. M4Singer original source-song inventory;
2. 2026-07-23 pinyin/slur real-GT overlay inventory;
3. accepted/rule-validated/review-required units per source song;
4. long-form/serial manifest source-song inventory;
5. cached T1/T2/T3/full-song prediction inventory;
6. current Raw evidence/cache inventory;
7. R2 training/validation/test source-song split and checkpoint-selection provenance;
8. MIR-1K/OOD and Test Demo inventories, kept separate from M4 real-GT formal metrics.

## 5.2 Required counts

For every candidate source song, compute:

```text
source_song_id
R2_train_overlap: yes/no/unknown
real_gt_units
canonical_units
real_gt_coverage
serial_prediction_available
full_song_prediction_available
raw_evidence_available
natural_or_synthetic_long
seam_count / seam proximity if synthetic-long
language/unit_type
```

## 5.3 Expansion cohorts

Codex should derive, not assume, the cohorts.

Recommended hierarchy:

### Cohort A — strict held-out formal

- source-song-disjoint from R2 fine-tuning train;
- valid real-GT coverage above a frozen threshold;
- predictions can be produced/reused within budget;
- no GT-derived case selection except for evaluation after predictions are generated.

### Cohort B — development / mechanism

- source-song-disjoint if possible;
- can include more songs used for model/threshold development;
- must remain disjoint from Cohort A.

### Cohort C — diagnostic catastrophic set

- mined **only after predictions exist** using real GT;
- used for decomposition/recovery diagnostics, not for unbiased overall performance claims;
- keep source-song identities explicit.

### Cohort D — training-overlap diagnostic (optional)

If some songs overlap R2 training and are scientifically useful, keep them separate and label them clearly. Never merge them into held-out generalization numbers.

## 5.4 Maximum safe expansion rule

Codex should choose the largest safe cohort satisfying:

```text
real GT valid
source-song provenance known
split leakage controlled
compute budget <= project ceiling
prediction/cache provenance recorded
```

Do not subsample to 60 merely because the exploratory file used 60. If hundreds of safe songs are available and the compute/cache budget supports them, expand.

Conversely, do not expand by including training-overlap or low-coverage songs merely to increase N.

---

# 6. Deliverable decision matrix

Codex's review must conclude with a table like:

```text
Historical experiment / conclusion | Action | Why | Existing artifacts reusable? | GPU rerun? | Priority
Transition real-GT                | REAGGREGATE | wrong GT metric | yes | no | P0
Raw detector real-GT              | RERUN/EXPAND | needed next | partial | maybe | P0
Old H/P/V/S expansions            | RETIRE/KEEP negative | not next priority | yes | no | P3
Recovery capability               | RERUN | trigger/eval contaminated | partial | yes | P0
Oracle recovery                   | REAGGREGATE/RERUN | verify GT path | ? | ? | P1
PR                                | KEEP/RETIRE/RERUN | lineage-dependent | ? | ? | P2
Slot/non-slot                     | REAGGREGATE/RERUN | metric-dependent | ? | ? | P2
Invalid-input timing degradation  | REAGGREGATE/RERUN | metric-dependent | ? | ? | P2
```

The example actions above are hypotheses only. Codex must replace them with verified decisions.

---

# 7. Failure policy

If Codex cannot prove a load-bearing result's GT provenance:

1. search scripts, run metadata, manifests, hashes, report input paths, and artifact schemas;
2. compare timestamps/values to identify which GT axis was used;
3. if still unresolved, mark the historical quantitative conclusion **not citable** and either rerun minimally or retire it.

Do not preserve a result merely because it appears in an older Markdown report.

