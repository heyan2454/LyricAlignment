# Patch Notes — 2026-08-10 Real-GT Review and Next-Round Handoff

This patch is documentation/planning only. It is designed to overlay the current
`LyricAlignment_202608100405_20260810_second_supplement_realgt` work directory.

## Added

- `docs/research_transition_recovery_detector_20260808_correction/14_SESSION_RECORD_REALGT_REVIEW_AND_NEXT_ROUND_20260810.md`
- `.../15_CURRENT_RESULTS_REALGT_AND_RISK_REASSESSMENT_20260810.md`
- `.../16_GT_CONTAMINATION_AUDIT_AND_DATA_EXPANSION_CODEX_PROTOCOL_20260810.md`
- `.../17_NEXT_ROUND_RAW_CATASTROPHIC_RECOVERY_EXPERIMENT_PLAN_20260810.md`
- `.../18_CODEX_OPENCODE_HANDOFF_NEXT_REALGT_ROUND_20260810.md`
- `.../20_PRETRANSITION_GT_LINEAGE_AUDIT_AND_RERUN_PLAN_20260810.md`

## Modified

- `AI_SESSION_ENTRY.md` is updated with a new 2026-08-10 stage override pointing to Documents 14–18.

## Important session-folder rule

Applying this patch **does not create the next run/session folder**.

The next round must create a fresh session/OUT_ROOT when OpenCode begins implementation/experiments.
Document 17 and the Codex-reviewed plans must then be copied into that new session.

## Main decisions captured

- synthetic-uniform long-timeline correctness GT is superseded by the real M4Singer pinyin/slur overlay for timing evaluation;
- Raw-only detector research is the next priority, focused on catastrophic false confidence rather than pooled AUC;
- recovery remains on the mainline and must be reevaluated on real-GT-confirmed errors;
- historical GT contamination must be audited and dynamically classified as KEEP/REAGGREGATE/RERUN/RETIRE;
- data scale should be expanded to the largest safe source-song-disjoint real-GT cohort determined by Codex, not hard-coded at 9 or 60 songs.
