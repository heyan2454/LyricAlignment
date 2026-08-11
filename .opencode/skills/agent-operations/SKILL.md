---
name: agent-operations
description: General-purpose multi-agent orchestration methodology for long-running, multi-module technical work. Use whenever work involves parallel subagents, development/review/testing/runtime concurrently, batch pipelines, multi-hour runs that must survive disconnects, resumable caching, free-form exploration after a mainline is done, or rules about when a run may stop. Covers parallel task dispatch, stage-level parallelism, review discipline, layered testing, no-midway-stop execution, frozen-parameter discipline, and post-mainline exploration workflow. Trigger this skill whenever the user mentions overnight runs, multi-agent batches, subagent review, resuming a run, parallel development, exploration phases, or completing a long experiment without stopping.
---

# Agent Operations

A topic-agnostic playbook for orchestrating long-running, multi-module work with
subagents. It was distilled from research-project experience and applies to any
technical domain (experiments, builds, data pipelines, migrations, etc.). Strip
the nouns of your project onto the roles below; the *mechanics* do not change.

## 1. Multi-agent orchestration

### 1.1 Task-level parallelism

- Dispatch independent tasks in parallel, one isolated workspace each, to avoid
  file conflicts.
- The main agent only schedules, dispatches, and merges acceptance. It does not
  duplicate the subagents' work.
- Subagents return short structured reports (changes / tests / artifacts /
  next steps); long code and results go to files, not into the reply.

### 1.2 Stage-level parallelism

Development, review, testing, and runtime are **separate stages that run
concurrently**, not a strict pipeline:

- While part A is still being developed, part B's finished code is already
  under review, part C's tests are running, and part D's long task is running in
  the background.
- Assign different agents to different stages; no stage waits for the whole
  batch to finish.

### 1.3 Batch pipeline overlap

- As soon as batch N's artifacts are produced, hand them to review while the
  main agent dispatches batch N+1.
- P0/P1 findings from review come back as incremental patches; they do not block
  new batches.

### 1.4 Different parts start simultaneously

- As long as module boundaries and interfaces are fixed in advance, multiple
  parts (modules / topics / experiment branches) start at the same time.
- Only hard dependencies are serialized.

### 1.5 Subagent constraints

- Give each subagent an explicit step budget; at the budget it must summarize
  (done / not done + reason / artifacts / next steps) instead of looping.
- Never allow infinite retry. On failure, restart automatically (at most 2
  times); before restarting, read the previous run's summary to avoid rework.
- Task prompts must require: no final summary until all sub-steps complete;
  small single operations (avoid huge single commands); spend steps on minimal
  necessary context, no repeated exploration.

### 1.6 Layered acceptance

- Fast tests (seconds, mandatory for every subagent)
- Module tests (when crossing modules, ~minutes)
- Full suite (only at merge/stage close-out)
- Plus syntax/compile check and `git diff --check`.
- A failed test blocks only the affected part, never the whole batch.

### 1.7 Review discipline

- After each batch, run two independent reviews: one for code correctness and
  contracts, one for data consistency and cross-module wiring.
- Reviews focus only on P0/P1 (bugs, contract violations, data inconsistency,
  conclusions-polluting issues). MINOR goes to a backlog and never blocks.
- Review overlaps with the next batch's development.

### 1.8 State tracking

Maintain a single state file. Update it atomically as each unit completes. It
must record, per part: status (in-progress / under-review / testing / running /
blocked), budget used, and a resume command. The main agent uses it to schedule.

## 2. Long-running task execution

### 2.1 Stage layering

- Run a small exploratory/pre-flight pass first; its results **may** change the
  design.
- Then freeze the design.
- Then a smoke run that only verifies executability (and resume).
- Then the formal long run.
- The three layers have distinct semantics; do not confuse them.

### 2.2 Detachment

- Long runs must survive a disconnected terminal: use `nohup`/systemd/terminal
  multiplexer, redirect output to a log file, and record the PID.
- A launcher that just `tee`s output dies with the SSH session.

### 2.3 Resume semantics

- Cache every intermediate artifact by identity hash (same inputs → skip).
- Each component resumes from its own checkpoint/state (including optimizer,
  scheduler, etc. where relevant).
- Never run two controllers against the same output root concurrently.

### 2.4 No Cartesian explosion

- Fix the vast majority of dimensions up front; escalate only a few dimensions
  in graded stages (conservative → aggressive).
- Add experiments only via a deviation log: why the plan is insufficient, what
  the experiment answers, the extra cost, and which low-priority item it
  replaces.

### 2.5 Small-sample safety

- Sample stratified per subset (every subset keeps representatives); never
  truncate a merged list.
- When data is genuinely insufficient, fall back explicitly, record it, and do
  not silently enable the fallback in formal runs.

### 2.6 Frozen-parameter discipline

- Freeze every hyperparameter before the formal stage.
- During formal, only fix bugs (and schema/identity bugs that invalidate
  results). After a fix, invalidate affected results and rerun only the
  affected identities. No on-the-fly tuning.

## 3. Completion without premature stop

- A negative result / no gain / single-item failure is **not** a reason to stop
  the whole run. Write an authoritative failure/negative-result artifact
  (status, real denominator, cause), then continue every stage that does not
  depend on it.
- Only a global blocker may stop the run: dependency/data/environment missing,
  disk unwritable, or a severe identity/split error that poisons all results.
  Even then, write a complete blocker doc (done-stages list, last successful
  artifact, failed command/log, a copy-paste resume command). Never leave only
  "the run failed / ran out of time".
- A run is complete only when every item has an explicit status (complete /
  bounded-insufficient / blocked / abandoned-with-reason). Do not mark the whole
  run failed early and exit.

## 4. Science/reporting boundaries

- Define and freeze metric semantics up front (e.g. exact definition of recall /
  safe rate); do not change them mid-way.
- Report numbers must be generated from structured data (JSON), never hand
  copied.
- Comparisons must be same-standard (same split / same identity); never merge
  scores across incompatible metrics.
- Never claim superiority from training loss; use frozen validation metrics and
  paired behavior.

## 5. Post-mainline exploration

- When the mainline is done, run a controlled free-exploration phase: the main
  agent orchestrates, multiple explore/review subagents probe different angles
  in parallel. Goal: find worthwhile research questions, latent defects, and
  cleanable artifacts.
- Structure: numbered exploration entries (finder + finding). Classify each:
  immediately actionable improvement, backlog item, or P0 escalation.
- Escalation path for findings that may overturn the main conclusion:
  data confirmation → independent counter-check (review + reverse verification)
  → impact-boundary assessment (affected / unaffected lists) → root-cause
  trace → highest-priority todo.
- Sediment: exploration reports as separate documents, backlog into a
  persistent list, cleanup items graded by safety (safe to do / needs
  confirmation / keep).

## Usage

Apply this skill when starting a multi-agent batch, planning a long run, writing
a resume-safe runner, or launching an exploration phase. Map the generic
mechanics onto your project's concrete naming; do not let project-specific
vocabulary change the mechanics.
