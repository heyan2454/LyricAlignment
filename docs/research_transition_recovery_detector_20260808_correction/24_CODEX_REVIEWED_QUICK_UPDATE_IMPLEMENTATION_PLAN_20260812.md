# Codex-reviewed OpenCode implementation plan: 2026-08-12 quick correction

## 0. Status, authority, and scope

**Status:** implementation-ready after the preflight audit below; this is a low-risk
correction/archive pass, not a new experiment stage.

**Input handoff:** `23_QUICK_UPDATE_HANDOFF_20260812.md`.
**Historical context:** `21_SECOND_SUPPLEMENT_PLAN_20260809.md` and
`22_SECOND_SUPPLEMENT_IMPLEMENTATION_PLAN_20260809.md` are immutable imported
records.  They explain why historical synthetic-GT and detector results require
careful labeling; do not reopen their broad reimplementation matrix in this pass.

**Current-stage boundary:** Documents 14--20 remain the active real-GT next-round
planning source.  This pass may correct their references and historical labels, but
must not create a next-round experiment session, change the real-GT split, execute
GPU work, retrain a detector, or run closed-loop recovery.

All generated delivery artifacts go to:

```text
/home/hyan/LyricAlignment_20260812_quick_correction/
```

Make only the approved low-risk source/document changes in the repository, then
copy their diff and changed documentation into this delivery directory.  Do not
place generated reports in `results/` until their input-artifact identity has been
recorded and their status is unambiguously retrospective or exploratory.

## 1. Codex preflight findings

| Area | Verified fact | Required interpretation |
|---|---|---|
| `light_merge` | `src/lyricalign/research_v7/detector_v2_intervals.py` now only fills one-unit `ACCEPT` islands and expands `REJECT` edges to `UNCERTAIN`; tests cover isolated and cascaded `REJECT` islands. | A same-score/same-threshold re-evaluation is a valid **retrospective bug-fixed evaluation**, never a new untouched formal test. |
| Oracle recovery | `scripts/research_transition_recovery_detector/run_oracle_recovery.py` builds `gt` directly from `timeline_manifest` `canonical_units`; it uses `start_sec` for error finding/scoring and for O0/O1/O2 query construction. | Existing O0/O1/O2 numbers are `historical_synthetic_gt_oracle_diagnostic`, not real-GT or no-GT recovery capability. |
| Semantic windows | `PlannedWindow.to_dict()` rounds boundary values independently to four decimals; request serialization in `build_long_timeline_manifest.py` also rounds `audio_end_sec`. | Clamp must occur against the exact source duration before serialization, and serialized values must be clamped again. |
| Second supplement | The 2026-08-09 run contains a historical report/evidence pack, but the supplied plan documents were not previously archived in the documentation tree. | Imported as Documents 21--22 with source-identical SHA-256 contents. |

The exact corrected Detector values in the handoff (including 0.9567/0.9628) are
not independently verified merely by the code review.  OpenCode must derive them
from identified before/after source artifacts or mark the affected cell
`not_reproduced_source_missing`; it must never fill a missing value from prose.

## 2. Guardrails and execution contract

1. Use the `lyricalign-qwen` conda environment and `PYTHONPATH=src`.
2. Start with `git rev-parse HEAD` and `git status --short`; record both verbatim in
   `00_meta/REPO_STATE.json`.  Preserve unrelated existing dirty changes.
3. No GPU command, model loading, training, threshold search, manifest rebuilding,
   or recovery execution is permitted.  All calculation commands must accept only
   existing files and must fail rather than silently substitute an approximate input.
4. Every JSON/CSV/Markdown result must contain its inputs (absolute path, SHA-256,
   schema/version if present), command, UTC timestamp, repository HEAD, and a
   `result_status` field.
5. A test-tuned gate threshold may appear only as
   `exploratory_test_tuned_threshold=true` and `formal_threshold=false`; it cannot
   change a configuration file or frozen working point.
6. Retain historical artifacts unchanged.  Corrections are new files/fields or
   explicit deprecation notes, not destructive rewriting.

## 3. Work packages

### WP0 — provenance inventory and archive integrity (CPU)

**Reason:** the correction statements are useful only if every result can name its
input evidence and all planning references resolve.

**Implement:** add a small read-only utility under
`scripts/research_transition_recovery_detector/` (for example
`quick_correction_audit.py`) with subcommands, rather than embedding parsing logic
in shell scripts.  It must:

- scan the current Transition/Recovery documentation and session entry for referenced
  repository-relative paths;
- classify each as present, absent, or external; never infer/recreate an absent file;
- scan the current-session scripts for `canonical_units`, timeline-manifest,
  `gt_start`, `gt_end`, `oracle`, and recovery correctness usage;
- write `SYNTHETIC_GT_USAGE_AUDIT.md` and `ARCHIVE_REFERENCE_CHECK.md` using the
  prescribed columns and a machine-readable JSON companion where practical.

**Outputs:** `00_meta/REPO_STATE.json`, `SYNTHETIC_GT_USAGE_AUDIT.md`,
`ARCHIVE_REFERENCE_CHECK.md`, `updated_docs/changed-files.txt`.

**Tests:** temporary-directory fixtures for a present reference, a missing reference,
and a synthetic-GT code hit.  No large result files may be scanned into memory.

### WP1 — metric schema audit and safe semantic naming

**Reason:** a start-only one-second score cannot share the name `hit100` with a
start-and-end 100-ms score.

**Implement in this order:**

1. Use the audit utility to produce `METRIC_SCHEMA_AUDIT.md`, classifying each live
   code/document/result occurrence as `both_boundaries_100ms`, `start_only_1s`,
   `other`, or `unknown`; report path and surrounding field/definition.
2. Change only locations proven by source to be start-only `<= 1.0` seconds:
   emit canonical `start_hit_1s`.  If a legacy reader requires `hit100`, also emit
   `legacy_hit100` with `deprecated=true`, never a silent alias.
3. Preserve genuine 100-ms two-boundary fields under an explicit name such as
   `boundary_hit_100ms`; do not rename unknown fields until classified.
4. Update the specific affected README/session/report wording found by the audit;
   add an explicit synthetic/exploratory disclaimer rather than bulk-editing every
   historical document.

**Tests:** exact truth-table tests that distinguish a good start/bad end pair from a
two-boundary 100-ms hit; compatibility test for the deprecated alias; audit test
that flags an unclassified `hit100` occurrence.

### WP2 — semantic/fixed request-boundary clamp

**Reason:** round-to-four-decimals can move a legal exact endpoint beyond the
audio duration.

**Implement:** introduce one pure helper at the serialization boundary (do not alter
the planner's segmentation strategy):

```text
serialize_window(start, end, exact_duration) -> (start_4dp, end_4dp)
```

It must validate finite values and `0 <= start < end <= exact_duration`, clamp on
the exact duration first, round, then clamp again using a representation that cannot
produce `end > exact_duration`.  If rounding would collapse a valid ultra-short
window (`start >= end`), retain a valid representable endpoint where possible;
otherwise fail with a structured reason, never emit an invalid request.

Thread the exact audio duration from the manifest/planner source into semantic and
fixed request serialization.  Update `PlannedWindow.to_dict()` only if its API can
receive the exact duration without breaking other callers; otherwise clamp in the
manifest builder immediately before the request dict is emitted.

**Tests:** non-integer 181.34975 duration; fixed tail; semantic tail; an upward
four-decimal rounding case; very short valid tail; and serialize/decode round trip.
Assert the final serialized request, not merely an intermediate object.

### WP3 — synthetic-GT provenance in historical diagnostics

**Reason:** `run_oracle_recovery.py` demonstrably uses synthetic timeline timing as
both correctness reference and oracle routing input.  Similar scripts must say so
at runtime and in output data.

**Implement:** centralize a small provenance payload, then add it to each script
confirmed by WP0 to use `LONG_TIMELINE_MANIFEST.canonical_units` for correctness:

```json
{
  "gt_kind": "synthetic_uniform_timeline",
  "valid_for_realgt_correctness": false,
  "result_status": "historical_synthetic_gt_diagnostic"
}
```

Print the warning from the handoff to stderr.  For oracle modes, also record
`gt_used_for_routing=true` and the precise mode (`O0`, `O1`, or `O2`).  Do not claim
all scripts use synthetic GT: only update those demonstrated by the audit.

**Tests:** a no-model dry-run/unit test checks JSON provenance and stderr warning;
existing normal output schema fields remain present.

### WP4 — reproduce read-only summaries

**Reason:** the corrected narrative needs source-backed tables rather than manually
copied numbers.

**Implement:** extend the audit utility or add a dedicated read-only reporter which
requires explicit `--before`, `--after`, and input records/predictions.  It must
produce exactly:

```text
results/corrected_detector_summary.json
results/corrected_detector_summary.md
results/light_merge_before_after.md
results/song_failure_concentration.csv
results/song_failure_concentration.md
results/window_gate_score_summary.json
results/window_gate_threshold_sweep.csv
results/window_gate_exploratory.md
```

The reporter must verify: same cohort identity, same score/model identity, same
threshold values, same label/metric schema, and only a postprocess version change
before labeling a comparison `retrospective_after_light_merge_fix`.  A failed
comparison is an error/status record, not a result.

For per-song and interval values, preserve source-song boundaries.  For gate sweeps,
report score definition, all denominators, per-song counts, and that the sweep is
exploratory.  Do not manufacture a 90-request score input from a high-level report.

**Tests:** fixture inputs with two songs, a rejected island, and known threshold
counts; mismatched threshold/cohort test must fail closed; deterministic CSV order
by route then decreasing unsafe share.

### WP5 — precise documentation corrections and delivery pack

**Reason:** later users must not read synthetic diagnostics or pre-fix results as
formal real-GT conclusions.

**Implement:** use WP0 search results to make the smallest supported documentation
changes.  Required wording is:

- Detector: bug-fixed retrospective Raw/Official protection figures, if reproduced;
  lower safe-accept tradeoff; not a clean formal test.
- Recovery: historical synthetic-GT oracle diagnostic; not real-GT/no-GT capability.
- Semantic planning: mechanism evidence only while accuracy scoring is synthetic.
- Enhanced features: `unresolved_after_bugfix`, not disproved, if the cited negative
  result predates the confirmed postprocess fix.

Copy the changed documentation and `git diff --binary` into `updated_docs/` and
`patches/`.  Write `IMPLEMENTATION_CHANGELOG.md` with repository paths, HEAD before
and after, input sources, and all intentional deviations.

Package only the delivery directory as
`/home/hyan/LyricAlignment_20260812_quick_correction.tar.gz`; exclude model caches,
audio, checkpoints, and existing large prediction artifacts.  Validate the archive
by listing it and checking every required path.

## 4. Execution order and gates

```text
WP0 inventory
  -> WP1 classification / WP3 provenance (independent after inventory)
  -> WP2 clamp and tests
  -> WP4 source-backed reports
  -> WP5 focused doc updates, test record, package
```

Do not begin WP4 until a source-artifact map exists.  Do not publish a corrected
detector value until its comparison gate passes.  WP5 may still deliver audits and
unavailable-source statuses if a historical artifact is missing.

Run, at minimum:

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export PYTHONPATH=src
python -m pytest -q tests/research_v7/test_detector_v2_intervals.py \
  tests/research_v7/test_semantic_window_planning.py \
  tests/research_v7/test_semantic_window_planning_wiring.py \
  <new-targeted-tests>
python -m compileall -q src scripts
git diff --check
```

Record commands, environment, pass/fail/skip counts, and runtime in
`tests/test_summary.md`.  Expected runtime is CPU-only and should be minutes, not
hours.  On resume, reuse completed audit/report outputs only when their declared
input SHA-256 values and repository HEAD match; otherwise regenerate them.

## 5. Completion criteria

The pass is complete only when the delivery directory contains the five audit/review
documents, all source-backed or explicitly unavailable result slots, patches,
changed-file list, and test summary; the repository contains only the approved
low-risk fixes/document corrections; and the validated tarball exists in
`/home/hyan`.  A missing historical input is an acceptable documented outcome; an
invented reconstruction is not.
