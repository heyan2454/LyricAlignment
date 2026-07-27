# 2026-07-27 Realign Demo Silence-aware Window Archive Validation

## Scope

Validated the `realigndiag1` worktree after integrating:

- shared raw serial planner;
- official/raw timestamp replay;
- whole-song silence-aware window planning;
- leading-silence removal from ownership with retained anchors;
- silence-boundary snapping;
- short-tail merge or two-window redistribution;
- silence-promoted realign anchors;
- default 2×2-only rendering;
- bounded-size evidence collection;
- session/manual/status documentation.

## Test results

Focused decoder/realign/window tests:

```text
60 passed
```

Repository tests excluding three modules that cannot be collected in the current
archive environment because `pypinyin` is not installed:

```text
147 passed
```

Excluded only:

```text
tests/test_audio_contract.py
tests/test_m4singer_preparation.py
tests/test_mir1k_partial_align.py
```

The exclusion is an environment dependency limitation, not a passing result for
those modules.

## Additional checks

- Python syntax compilation passed for all modified modules.
- `collect_decoder_realign_evidence.sh --help` works from outside the repository
  because it resolves the repository root from its own path.
- Batch CLI exposes silence-aware planning, tail threshold, prepared-audio reuse,
  and optional pairwise rendering.
- Default rendering remains 2×2 only.
- Archive cleanup removes `.pytest_cache`, `__pycache__`, `.pyc`, and historical
  `.patch_backups`; implementation history is preserved in session documents.

## Not validated

The archive environment does not contain the real Qwen/R2 GPU model runtime.
Therefore this validation does not claim:

- improved listening quality;
- successful natural-collapse repair;
- correct final silence thresholds for weak vocals;
- superiority of official or raw decoder.

Those require the server run and compact evidence described in
`docs/status/next_execution_plan.md`.
