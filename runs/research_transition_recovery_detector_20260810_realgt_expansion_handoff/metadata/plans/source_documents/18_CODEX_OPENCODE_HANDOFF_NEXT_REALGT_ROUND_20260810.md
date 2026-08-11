# 18. Codex / OpenCode Handoff Contract for the Next Real-GT Round

## 1. This patch does not create the next session

The documentation added by this patch belongs to the **current archived work directory**.

Do not create a new experiment output/session directory merely by applying this patch.

The next new session is created only when the next implementation/experiment round begins.

---

## 2. Codex responsibilities before execution

Codex must:

1. read Documents 14–17 and the previous second-supplement plan/results;
2. verify the GT contamination claims against code/artifacts;
3. build the historical GT-lineage decision table;
4. build the data-capacity/split/leakage inventory;
5. determine the maximum safe real-GT cohort;
6. verify R2 train-song overlap status;
7. decide exactly which old experiments need KEEP/REAGGREGATE/RERUN/RETIRE;
8. specify the Raw-only next-round implementation;
9. specify the real-error recovery interventions and transaction-safe writeback;
10. list exact files to modify, tests to add, commands to run, caches to reuse, and expected runtime.

Codex may add/modify the plan when repository facts contradict assumptions here. It must record every material deviation and the evidence for it.

Codex must **not** preserve an old experiment solely because a previous report called it authoritative.

---

## 3. Required Codex implementation-plan structure

For each task:

```text
Problem / reason
Verified root cause or data fact
Experiment purpose
Implementation changes
Inputs / GT / split
Cache reuse
Exact output artifacts
Tests
Execution command
Expected runtime
Failure / resume behavior
Expected possible outcomes
What each outcome would support or refute
```

For dynamic historical reruns, include a generated rerun manifest rather than a hard-coded large matrix.

---

## 4. OpenCode responsibilities

After Codex review is accepted, OpenCode must:

1. create a fresh next-round session/OUT_ROOT;
2. copy Document 17 and Codex's two review/implementation documents into the session metadata;
3. freeze manifests/hashes before experimental execution;
4. implement and test before formal runs;
5. run mandatory stages to completion without stopping after an early positive/negative result;
6. reuse existing predictions/caches whenever identity-equivalent;
7. keep raw formal, diagnostic mined sets, and historical reruns separate;
8. keep source-song-disjoint roles intact;
9. record all failures and continue independent tasks where safe;
10. generate a compact evidence pack that can reproduce all reported metrics.

---

## 5. Priority order

```text
P0  GT/data/split audit + real-GT baseline + Raw catastrophic decomposition
P0  real-error recovery capability
P1  Raw-triggered recovery if capability exists
P1  load-bearing historical corrections selected by audit
P2  slot/head/invalid-input corrections if they affect next research direction
P3  optional sub-grid precision / non-load-bearing old feature families
```

Do not spend the next run rebuilding H/P/V/S/PR unless the Codex audit shows a specific load-bearing dependency.

---

## 6. Scientific boundary

The next round is intended to test:

> **A usually accurate long-form forced aligner can still fail rarely and catastrophically. Can Raw confidence reliably identify those failures, and can targeted recovery fix genuine errors without damaging correct alignment?**

It is not intended to optimize a broad detector-feature leaderboard.

