# Demo local-realignment quick execution

## Stage meaning

This entry implements the **quick scientific diagnostic** stage.

```text
quick review
  -> discuss and freeze/revise overnight design
  -> separate smoke of the frozen overnight entry
  -> overnight launch
```

Quick is not smoke.  Quick results may change the overnight hypotheses, case
matrix, anchor policies, repair modes, or analysis plan.  The later smoke only
checks that the already-decided overnight entry can execute, resume, write its
artifacts, and survive one failed case.

This patch does not implement or launch overnight.

## Implemented quick phases

### Evidence

For every selected development item, audio variant and core length:

- run current v6 serial alignment;
- retain all accepted-window candidate rows as `shadow_rows`;
- preserve raw, processor-decoded, selected and final fields;
- automatically mine natural collapse/conflict/disagreement intervals;
- derive anchor features and GT analysis rows.

The normal demo does not retain `shadow_rows` unless
`--capture-shadow-rows` is explicitly enabled.

### Q1

- scan A0–A4 anchor policies;
- sweep confidence-margin quantiles and overlap tolerances;
- report individual-anchor and natural-candidate anchor-pair precision/coverage;
- write a 2–4 policy shortlist for Q2/Q3 review.

### Q2

Q2 is no longer restricted to one hard-coded `geniusturtle_1` character.  It
runs every automatically mined natural structural candidate.  Candidate mining
does not use GT.  GT is used only after mining for evaluation.

For each candidate it runs:

- selected rollback + bounded local remerge baseline;
- best/strict automatic anchors when available;
- GT-oracle anchors as a diagnostic upper bound;
- 0.5 s and 1.5 s crop padding;
- local raw and processor-decoded candidates;
- direct-trust and bounded-remerge splice candidates;
- non-GT anomaly gate diagnostics;
- two-crop agreement diagnostics.

The recorded `constraint_dependency_trace` means only that a predecessor's
final end supplied a forward-compression floor.  It does not claim that the
predecessor is GT-wrong.

### Q3

Q3 uses an independent case structure and includes:

- real Qwen cursor `-4` and `+4` window inference;
- commit-end replay at `+0.48 s` and `+0.96 s`;
- unchanged detector controls;
- forced-repair clean controls;
- local raw/decoded repair candidates.

Q3 defaults to three development songs and two seams per song.

## External output contract

Default root:

```text
/home/hyan/Data/lyricalign/demo_diagnostics/realign_quick_v1
```

Top-level files:

```text
plan.json
resolved_inputs.json
run_status.jsonl
summary.json
failure_summary.json
repair_candidates.csv
command.sh
return_code.txt
```

Main phase artifacts:

```text
evidence/core_30s/<audio>/<item>.json
q1_anchor_scan/rows.jsonl
q1_anchor_scan/natural_candidates.jsonl
q1_anchor_scan/precision_coverage.csv
q1_anchor_scan/aggregate.json
q1_anchor_scan/recommended_shortlist.json
q2_natural_realign/cases/*.json
q2_natural_realign/comparison.json
q2_natural_realign/trace.md
q3_injection_matrix/plan.resolved.json
q3_injection_matrix/cases/*.json
q3_injection_matrix/detector_summary.json
q3_injection_matrix/repair_summary.json
q3_injection_matrix/failures.jsonl
```

Every evidence/case request has a canonical identity hash.  An identity-matched
complete result is skipped.  A failed case writes its own failure/status JSON
and later cases continue unless `--fail-fast` is used.

## Recommended launch

Set the external R2 checkpoint and run the launcher from the server:

```bash
cd /home/hyan/LyricAlignment
export R2_CHECKPOINT=/home/hyan/Data/lyricalign/runs/<R2_RUN>/<CHECKPOINT>
export SUBSET_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1
export OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/realign_quick_v1
export PYTHON_BIN=/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python
bash scripts/demo/run_demo_realign_quick.sh
```

The launcher uses:

```text
Demucs + official vocal
30 s core + 10 s left/right context
0.5 s + 1.5 s local crop padding
all Q1/Q2/Q3 phases
```

It logs through `tee`, so closing the SSH terminal will still terminate the
process.  Use the server's existing detached execution method (`nohup`, systemd
run scope, or an already available terminal multiplexer) when disconnection is
possible.  Example with `nohup`:

```bash
mkdir -p "$OUT_ROOT/logs"
nohup bash scripts/demo/run_demo_realign_quick.sh \
  > "$OUT_ROOT/logs/nohup.log" 2>&1 < /dev/null &
echo $! > "$OUT_ROOT/launcher.pid"
```

## Resume and phase-specific execution

Rerun the same launcher to resume all identity-matched work:

```bash
bash scripts/demo/run_demo_realign_quick.sh
```

Run phases separately:

```bash
PHASES="evidence q1" bash scripts/demo/run_demo_realign_quick.sh
PHASES="q2" bash scripts/demo/run_demo_realign_quick.sh
PHASES="q3 collect" bash scripts/demo/run_demo_realign_quick.sh
```

Do not run `q2` or `q3` before evidence and Q1 have completed.  Q1 is cheap and
does not load another model when included in the same `all` process.

## Progress checks

```bash
tail -f "$OUT_ROOT/logs/quick_controller.log"
tail -n 30 "$OUT_ROOT/run_status.jsonl"
find "$OUT_ROOT/q2_natural_realign/cases" -name '*.status.json' | wc -l
find "$OUT_ROOT/q3_injection_matrix/cases" -name '*.status.json' | wc -l
```

Inspect failures without stopping completed work:

```bash
cat "$OUT_ROOT/failure_summary.json"
find "$OUT_ROOT" -name '*.failure.json' -print
```

## Automatic collection

The launcher automatically runs the collector.  It writes summaries and a
lightweight archive that omits the large evidence files:

```text
$OUT_ROOT/realign_quick_handoff_without_evidence.tar.gz
```

Run collection manually after an interruption:

```bash
python scripts/demo/collect_demo_realign_quick.py \
  --out-root "$OUT_ROOT" \
  --archive "$OUT_ROOT/realign_quick_handoff_without_evidence.tar.gz" \
  --exclude-evidence
```

For a complete archive including window evidence:

```bash
python scripts/demo/collect_demo_realign_quick.py \
  --out-root "$OUT_ROOT" \
  --archive "$OUT_ROOT/realign_quick_complete.tar.gz"
```

## Files to return for review

Preferred first upload:

```text
realign_quick_handoff_without_evidence.tar.gz
```

Also provide these evidence files only when a reviewed case needs the full
window trace:

```text
evidence/core_30s/<audio>/<item>.json
```

After quick-result review, update the overnight design.  Only after that design
is frozen should a separate overnight smoke entry be implemented and run.
