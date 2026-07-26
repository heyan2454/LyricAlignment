# Demo local-realignment quick experiment handoff — 2026-07-27

## Purpose

This document is the immediate implementation contract for the next session.
It defines three bounded quick experiments that must run before the larger
local-realignment overnight. Their role is to catch conceptual or engineering
errors early and narrow the overnight matrix.

Do not use the 4-song held-out split.

## Existing inputs

Repository:

```text
/home/hyan/LyricAlignment
```

MIR-1K subset root:

```text
/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1
```

Existing first-pass outputs are expected under external roots similar to:

```text
/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_runs_v1
/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_followup_v2
```

The implementation must accept these roots as arguments rather than silently
hard-code them.

Model identity must be explicit:

- local Qwen base snapshot path;
- pinned revision;
- R2 checkpoint path;
- checkpoint/base hashes when already available;
- `local_files_only` behavior;
- Demucs input identity.

## Proposed new code placement

Preserve the repository architecture. Suggested additions:

```text
scripts/demo/analyze_demo_realign_anchors.py
scripts/demo/run_demo_local_realign_probe.py
scripts/demo/run_demo_realign_quick.sh
src/lyricalign/demo/realign_diagnostics.py
tests/test_demo_realign_diagnostics.py
```

Names may be refined if an existing module is a clearly better fit, but do not
create a new top-level directory.

## Shared artifact contract

All quick experiments must write lightweight JSON/JSONL artifacts under an
external output root, for example:

```text
/home/hyan/Data/lyricalign/demo_diagnostics/realign_quick_v1/
```

Required top-level files:

```text
plan.json
resolved_inputs.json
run_status.jsonl
summary.json
failure_summary.json
```

Each case must preserve:

- song/item ID;
- source window IDs and lyric-index ranges;
- experiment family and condition;
- source audio variant;
- model/revision/checkpoint identity;
- original raw/decoded/selected/final rows;
- GT rows;
- trigger features;
- chosen left/right anchors and rejected candidates;
- local crop start/end and padding;
- local raw and local decoded rows;
- direct-trust and gated replacement candidates;
- before/after metrics;
- wall time, return status and failure reason.

Never overwrite an existing completed case with a different identity. Use a
condition hash or explicit identity check. Write each case atomically through a
temporary file and rename on success.

## Shared metric separation

Keep these result layers separate:

1. **Detector metrics**: interval-level precision, recall and false alarms.
2. **Anchor metrics**: per-anchor and anchor-pair GT accuracy/coverage.
3. **Repair metrics**: local before/after character boundaries.
4. **Global impact**: whole-song metrics after replacement.
5. **Engineering metrics**: calls, wall time, GPU memory, failures.

Do not mix detector F1 with character alignment F1/MAE.

## Q1 — Anchor accuracy and coverage scan

### Goal

Test the central pseudo-correct-boundary hypothesis without new model inference.

### Data

Use the existing 8-song development outputs for:

- official vocal;
- Demucs;
- 30-second serial windows;
- independent oracle-window outputs when available.

### Candidate boundary features

For every boundary with GT, derive:

- raw probability;
- top-1/top-2 margin;
- entropy;
- raw-to-decoded movement;
- neighboring-window onset/offset/midpoint disagreement;
- whether compressed in final;
- duration and short/collapse status;
- lyric-line boundary flag if available;
- acoustic-gap feature only if already available without heavy preprocessing.

### Rule families

Evaluate progressively stricter, clearly named rules:

```text
A0 confidence-only
A1 overlap-agreement-only
A2 overlap-agreement + confidence
A3 A2 + raw/decoded stability
A4 A3 + no compression/collapse
```

Do not fix a single confidence threshold. Sweep development quantiles, for
example 50/60/70/80/90 percentiles, and overlap tolerances based on timestamp
steps, for example 1/2/3/4/6 steps.

### Metrics

For individual anchors:

- `anchor@80ms`;
- `anchor@160ms`;
- `anchor@240ms`;
- coverage.

For anchor pairs around candidate intervals:

- both anchors within tolerance;
- correct lyric-index order;
- interval correctly enclosed;
- pair coverage;
- distance from target interval;
- audio interval length.

### Required output

```text
q1_anchor_scan/rows.jsonl
q1_anchor_scan/aggregate.json
q1_anchor_scan/precision_coverage.csv
q1_anchor_scan/recommended_shortlist.json
```

The shortlist is not a frozen production rule. It selects 2–4 anchor policies
for Q2/Q3 and the overnight.

### Entry criterion for Q2/Q3

At least one policy should have meaningful coverage and high pair accuracy. If
all policies have poor pair accuracy, local realignment must still be tested on
GT-oracle anchors as a diagnostic upper bound, and the overnight anchor plan
must be revised.

## Q2 — Real natural-collapse local realignment

### Goal

Verify the end-to-end local crop and replacement implementation on the known
`geniusturtle_1` Demucs seam collapse.

### Required case

Character `代` around the observed seam:

```text
GT approximately:       29.22–30.17 s
raw/selected:            29.20–30.16 s
v6 final:                30.16–30.16 s
```

The implementation must locate the case from artifacts/indices rather than only
hard-coding times.

### Anchor modes

Run:

1. best automatic anchor policy from Q1;
2. strict automatic policy from Q1;
3. GT-oracle anchors as a diagnostic upper bound.

### Crop conditions

```text
padding 0.5 s
padding 1.5 s
```

Input exact lyric units from left anchor through right anchor. Do not inherit
serial cursor, previous committed end or hard-forward compression.

### Candidate outputs

- local raw;
- local processor-decoded;
- direct-trust replacement;
- anomaly-gated replacement;
- two-crop-consensus replacement if both runs complete.

### Questions

- Does independent local alignment recover the collapsed character?
- Are the two anchors reproduced within 80/160/240 ms?
- Is raw or decoded better?
- Do two crop paddings agree?
- Does direct replacement improve the local and full-song result?
- Would a non-GT acceptance rule accept the best candidate?

### Required output

```text
q2_natural_collapse/case.json
q2_natural_collapse/candidates.jsonl
q2_natural_collapse/comparison.json
q2_natural_collapse/trace.md
```

`trace.md` must include the original cause chain, not only final metrics.

## Q3 — Small controlled injection matrix

### Goal

Test detection, anchors and repair on enough controlled cases to expose obvious
failure modes before overnight.

### Sample selection

Select 3 development songs with:

- at least two effective seams;
- different character rates/durations;
- valid Demucs outputs;
- no selection using repair outcomes.

Use two seams per song where possible.

### Injections

#### Cursor state

```text
cursor -4 units
cursor +4 units
```

Negative means repeated already-sung units; positive means missing units that
are acoustically present.

#### Commit/collapse replay

Shift the previous committed end by:

```text
+0.48 s
+0.96 s
```

Replay the merge so one or more following units are shortened/collapsed.

#### Clean controls

For every selected seam, include the unchanged condition. Clean controls are
mandatory for measuring false alarms and repair harm.

Expected scale is approximately 24 injected conditions plus clean controls,
subject to resolved seam availability. Record the resolved count; do not fake a
requested count if a song has insufficient seams.

### Detector families

At minimum:

- zero-duration;
- consecutive one-step short units;
- selected-to-final compression;
- overlap median shift;
- overlap residual/warp;
- cursor-index disagreement.

### Repair modes

At minimum:

```text
R0 no repair
R1 local result direct trust
R2 trigger-corresponding anomaly gate
R3 two-crop consensus gate
```

Include local raw and decoded candidates. GT oracle choice may be reported as an
upper bound, never as deployable output.

### Metrics

Per experiment family and severity:

- detector interval precision/recall;
- anchor-pair accuracy and coverage;
- repair win rate;
- harm rate;
- severe-harm rate;
- local and whole-song MAE/tolerance changes;
- non-target characters changed;
- extra Qwen calls and failures.

### Required output

```text
q3_injection_matrix/plan.resolved.json
q3_injection_matrix/cases.jsonl
q3_injection_matrix/detector_summary.json
q3_injection_matrix/repair_summary.json
q3_injection_matrix/failures.jsonl
```

## Quick-stage completion gate

Do not launch the full overnight merely because scripts run. The next session
must review:

1. whether automatic anchors are accurate enough at usable coverage;
2. whether the natural collapse is repaired by local alignment;
3. whether direct trust produces unacceptable severe harm on clean/injected
   controls;
4. whether anomaly-gated or two-crop acceptance adds substantial value;
5. whether cursor injections require multi-cursor search rather than only local
   timing repair;
6. whether artifacts are sufficient to diagnose each failure.

Possible decisions:

- proceed with the planned overnight largely unchanged;
- narrow the overnight to collapse-only repair;
- add multi-cursor candidates;
- use GT-oracle anchors only to measure local-alignment upper bound while
  redesigning automatic anchor selection;
- stop if local alignment fails even with GT-oracle anchors.

## Quick-run failure recovery

- per-case execution must be resumable;
- one failed case must not prevent later cases;
- case status values should include `planned`, `running`, `complete`, `failed`,
  `skipped_identity_match`;
- rerun must skip identity-matched complete cases;
- stderr/stdout should be retained per failed case or summarized with exact
  log paths;
- final summary must distinguish requested and resolved case counts.

## 2026-07-27 implementation clarification

The quick stage is a scientific diagnostic, not an execution smoke test.

```text
quick results
  -> review and revise/freeze overnight design
  -> separate smoke of the frozen overnight entry
  -> overnight run
```

Accordingly, quick results may change the overnight matrix.  The later smoke
only guarantees that the frozen overnight entry runs, resumes and collects
correctly; smoke is not expected to establish scientific value.

The implemented quick patch also changes Q2 from one hard-coded natural case to
all automatically mined collapse/conflict/disagreement intervals in the chosen
development outputs.  Candidate mining does not use GT.  The known
`geniusturtle_1` collapse remains an expected case when it is present in the
resolved evidence, not a special time-coded branch.

Implemented entries and execution guide:

```text
scripts/demo/run_demo_realign_quick.py
scripts/demo/run_demo_realign_quick.sh
scripts/demo/collect_demo_realign_quick.py
src/lyricalign/demo/realign_diagnostics.py
docs/manual/demo_realign_quick_execution.md
```
