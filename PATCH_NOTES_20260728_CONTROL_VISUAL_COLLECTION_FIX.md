# Inline realign v4 control / visualization / collection repair

Date: 2026-07-28

## Scope

This patch repairs two failures observed during a smoke run and four control-plane issues found during review. It does not change the trained weights or the normal model inference algorithm.

Observed failures:

1. Static visualization failed for a Japanese Demo item with `KeyError: 'start_sec'`.
2. Evidence collection failed while copying `state/items/<item_id>.json` because the nested staging directory did not exist.

Requested control-plane repairs:

1. An item must not be marked `complete` when an expected output is missing or empty.
2. `--force --resume` and `--invalidate-stage experiment` must actually re-enter item/branch execution.
3. A missing Demo root must fail before the smoke/formal wrapper launches the pipeline.
4. Smoke selects one Demo item per discovered language.

## Failure interpretation

`RENDER_MODE=skip` skips only MP4 rendering. It intentionally still runs:

- summary generation;
- static visualization;
- bounded evidence collection;
- `analysis_complete.json` generation.

Therefore both reported exceptions are implementation bugs, not expected effects of `RENDER_MODE=skip`.

## Implemented changes

### Visualization timing schema compatibility

`src/lyricalign/demo/visual_diagnostics.py` now projects supported stage-specific global timing pairs to canonical `start_sec/end_sec` before plotting:

- `start_sec/end_sec`;
- `selected_start_sec/selected_end_sec`;
- `fixed_global_start_sec/fixed_global_end_sec`;
- `official_fixed_global_start_sec/official_fixed_global_end_sec`;
- `raw_global_start_sec/raw_global_end_sec`.

`analyze_inline_realign_visuals.py` applies the same normalization to context-trial rows used by immediate and pending realign case pages. It also preserves a valid boundary value of `0.0` instead of treating it as missing.

### Evidence collection nested paths

`collect_inline_realign_evidence.py` now creates each destination parent directory before `shutil.copy2`. This covers paths such as:

```text
state/items/demo_Cantonese_乙女解剖_0aca89e7.json
state/stages/visualization.json
```

### Complete-output gate

`RunState.finish_item(status="complete")` now raises before writing a complete state when any expected output is missing or empty. The surrounding experiment item error handler then records the item as failed instead of counting it as complete.

### Force and experiment invalidation

- `--resume --force` can no longer skip a complete item.
- Pipeline `--invalidate-stage experiment` now forwards `--force` to the experiment controller, so item and branch caches are recomputed rather than only invalidating the top-level stage record.

### Demo root and smoke selection

- Missing `DEMO_ROOT` is now an immediate input-validation error because smoke/formal wrappers always require Demo input.
- Smoke config now uses one Demo item per discovered language.

## Validation performed

```text
Focused original mechanism tests + new regression tests: 98 passed
Repository tests excluding three modules blocked by missing pypinyin in the review container: 217 passed
Python compileall: passed
All shell scripts bash -n: passed
```

The ten remaining test warnings are the existing direct-test Matplotlib DejaVu Sans CJK warnings; the production font preflight remains separate.

## Recommended deployment

Extract the archive over `/home/hyan/LyricAlignment`.

Because the pipeline freezes implementation hashes, replacing these source files changes run identity. The safest validation is a fresh smoke output root:

```bash
OUT_ROOT=/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v4_control_fix_20260728 \
RENDER_MODE=skip \
bash scripts/demo/run_inline_realign_smoke.sh
```

## Reuse existing completed inference outputs

For the specific run that already completed experiment inference and failed only in visualization/collection, the existing output can be repaired without rerunning the model. Preserve the old identity record, adopt the patched implementation identity, and force the downstream stages:

```bash
SMOKE_ROOT=/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v4_full_20260728

cp "$SMOKE_ROOT/state/run_state.json" \
   "$SMOKE_ROOT/state/run_state.before_control_visual_collection_fix.json"
rm "$SMOKE_ROOT/state/run_state.json"

OUT_ROOT="$SMOKE_ROOT" \
RESUME=1 \
FROM_STAGE=visualization \
INVALIDATE_STAGE=visualization,collection \
RENDER_MODE=skip \
bash scripts/demo/run_inline_realign_smoke.sh
```

This is an explicit one-time implementation-identity migration. The backed-up old run state should remain in the output directory for audit. `FROM_STAGE=visualization` prevents model inference from being rerun; all static pages are regenerated and collection is rebuilt.

After success, expected terminal state includes:

```text
analysis_complete.json: status complete or partial_failure
render_complete.json: status deferred
inline_realign_evidence.tar.gz: present and non-empty
```
