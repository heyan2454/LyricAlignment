# AI Session Entry

## Read in this order

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/status/next_execution_plan.md`
4. `docs/sessions/20260728_multilingual_inline_realign_completion_archive.md`
5. `docs/sessions/20260728_inline_realign_followup_experiments.md`
6. `docs/manual/inline_realign_smoke_formal.md`
7. `docs/sessions/20260727_inline_realign_smoke_formal_archive.md`
8. `docs/sessions/20260727_inline_realign_discussion_and_experiment_plan.md`
9. `docs/archive/20260727_inline_realign_archive_validation.md`
10. `docs/sessions/20260727_realign_demo_silence_aware_window_archive.md`
11. `docs/sessions/20260727_mir1k_demo_diagnostic_experiment.md`
12. `docs/principles.md`

## Current stage

```text
first Qwen FA LoRA cycle archived
-> shared-raw four-way Demo exposed official/raw, anchor and tail problems
-> GT-oracle showed local realign can repair some errors; direct stable-cursor replacement was negative
-> multilingual all-discovered Test Demo and the complete shadow suite are implemented
-> current focus: server smoke/formal for detector P/R, clean harm, exact/+2/+4, expansion guard, pending and rollback
-> all alignments finish before batch rendering and optional link-only publishing
-> do not enable automatic writeback before GT-backed follow-up evidence
```

## Current executable entry

```bash
bash scripts/demo/run_inline_realign_smoke.sh
bash scripts/demo/run_inline_realign_formal.sh
```

The pipeline runs:

```text
manifest/input audit
→ B0-B3 or B2-only alignment according to bounded variant_set
→ localized precommit detector + GT-oracle local-realign capability test
→ stable segments actively propose/re-run next-window transcript starts
→ forced +25%/+50% future-text expansion
→ all Demo align first, then one-directory official rendering
→ compact result summary and evidence capped at 8 MiB
```

## Canonical facts

- official timestamps are structurally better than raw in the current six-Demo evidence;
- current O0 is not equivalent to the old R2 vocal-window path because shared raw planning controls lyric ownership and cursor;
- current post-hoc realign wrote almost nothing, mainly due to anchor filtering and late insertion;
- fixed 16-character, fixed 12-second, fixed line-count and hard two-window-observation anchor rules are rejected;
- stable references are contiguous segments searched within one or two adjacent windows;
- future-lookahead text is not treated as a true repeated acoustic observation;
- strong silence no longer bypasses confidence/context checks;
- current inline realign is shadow-only and cannot change serial ownership/cursor;
- MIR-1K held-out is excluded unless explicitly requested after rules are frozen;
- M4Singer defaults to validation; synthetic-long and natural full-song results remain separate;
- formal uses every discovered+prepared Test Demo by default; current song counts are input metadata, never hard-coded limits; smoke samples one item per discovered language;
- MIR-1K development/spare and M4Singer remain bounded development datasets; M4 synthetic-long is stratified at 60/120/180 seconds and synthetic seams are reported separately;
- evidence excludes audio/video/weights/full logs and automatically shrinks full→anomaly→severe; partial item failure still proceeds to bounded collection when the experiment summary exists;
- Demo is required by the wrappers; rendering starts only after every item finishes alignment and uses only `items/<id>/render/official.mp4`.
- follow-up summaries keep automatic candidates, GT oracle, stable-window assistance, expansion, planner divergence and constructed incomplete results separate.

## Current unknowns

- whether 30 seconds itself is weaker than 60 seconds;
- whether silence-aware boundary movement is beneficial;
- how much shared raw planning causes official degradation;
- whether selected→final compression is the dominant secondary collapse;
- stable-segment GT precision and clean harm;
- whether stable-prefix failure predicts propagation early enough;
- whether exact/+2/+4 consensus improves the accepted repair set without clean harm;
- automatic detector case/unit precision and recall;
- whether stable-prefix failure rejects dangerous future-text expansion early enough;
- whether cross-window pending confirmation and severe-tail two-window rollback improve GT;
- whether current B1/B2 differences remain after excluding text-expansion failures;
- whether multilingual Test Demo exposes language-specific unit/tokenizer failures.

## Constraints

- no automatic local writeback before shadow evidence;
- no threshold selection from Demo listening or structural metrics alone;
- no MIR-1K held-out tuning;
- no mixing M4 synthetic seams with natural MIR-1K conclusions;
- no unconditional tail commit as a future repair strategy;
- checkpoints, audio, video and large runtime outputs stay external.
