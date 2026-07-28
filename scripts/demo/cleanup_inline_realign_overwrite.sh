#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:?usage: $0 EXPERIMENT_ROOT [all|analysis|visual|render|stale]}"
MODE="${2:-analysis}"
ROOT="$(python - <<'PY' "$ROOT"
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
case "$ROOT" in
  /|/home|/root|/mnt|/mnt/data|/home/hyan/Data) echo "refusing dangerous path: $ROOT" >&2; exit 2 ;;
esac
[[ -d "$ROOT" ]] || { echo "nothing to clean: $ROOT"; exit 0; }

remove_stage_state() {
  for stage in "$@"; do rm -f -- "$ROOT/state/stages/$stage.json"; done
}

case "$MODE" in
  all)
    echo "remove complete experiment root: $ROOT"
    rm -rf -- "$ROOT"
    ;;
  stale)
    python - <<'PY' "$ROOT"
import json, shutil, sys
from pathlib import Path
root=Path(sys.argv[1]); manifest=root/'experiment_manifest.jsonl'
valid={str(json.loads(line)['item_id']) for line in manifest.read_text(encoding='utf-8').splitlines() if line.strip()} if manifest.is_file() else set()
for path in sorted((root/'items').glob('*')):
    if path.is_dir() and path.name not in valid:
        print(f'remove stale item: {path}'); shutil.rmtree(path)
for path in sorted((root/'state/items').glob('*.json')):
    if path.stem not in valid:
        print(f'remove stale item state: {path}'); path.unlink()
PY
    ;;
  render)
    echo "remove only video outputs and render state; keep experiment and static diagnostics"
    rm -f -- "$ROOT/demo_render_summary.json" "$ROOT/render_complete.json" "$ROOT/demo_publish_summary.json"
    rm -rf -- "$ROOT/renders" "$ROOT/published_demo" "$ROOT/state/render_items"
    find "$ROOT/items" -mindepth 2 -maxdepth 2 -type d -name renders -print0 2>/dev/null | xargs -0r rm -rf --
    remove_stage_state render publish
    ;;
  visual)
    echo "remove static diagnostics and videos; keep model/metric results"
    rm -f -- "$ROOT/visualization_summary.json" "$ROOT/demo_render_summary.json" "$ROOT/render_complete.json" \
      "$ROOT/demo_publish_summary.json" "$ROOT/analysis_complete.json" "$ROOT/pipeline_complete.json"
    rm -rf -- "$ROOT/renders" "$ROOT/published_demo" "$ROOT/state/render_items" "$ROOT/state/visual_items"
    find "$ROOT/items" -mindepth 2 -maxdepth 2 -type d \
      \( -name visuals -o -name renders \) -print0 2>/dev/null | xargs -0r rm -rf --
    remove_stage_state visualization render publish collection
    ;;
  analysis|derived)
    echo "remove all v4 derived/shadow/visual/render outputs; preserve only branch inference caches"
    rm -f -- "$ROOT/complete.json" "$ROOT/pipeline_complete.json" "$ROOT/pipeline_failure.json" \
      "$ROOT/analysis_complete.json" "$ROOT/render_complete.json" "$ROOT/experiment_summary.json" \
      "$ROOT/followup_analysis_summary.json" "$ROOT/followup_analysis_summary.md" \
      "$ROOT/visualization_summary.json" "$ROOT/demo_render_summary.json" "$ROOT/demo_publish_summary.json" \
      "$ROOT/inline_realign_evidence.tar.gz" "$ROOT/live_status.json" "$ROOT/experiment_live_status.json" \
      "$ROOT/run_status.jsonl" "$ROOT/pipeline_status.jsonl"
    rm -rf -- "$ROOT/renders" "$ROOT/published_demo" "$ROOT/evidence_staging" "$ROOT/logs" \
      "$ROOT/state/stages" "$ROOT/state/items" "$ROOT/state/visual_items" "$ROOT/state/render_items"
    # Keep state/run_state.json only when deliberately reusing the identical v4 run.
    # For a code/schema upgrade, use mode=all or a new OUT_ROOT instead.
    if [[ -d "$ROOT/items" ]]; then
      find "$ROOT/items" -mindepth 2 -maxdepth 2 -type d \
        \( -name visuals -o -name renders -o -name render -o -name experimental_alignments \) -print0 | xargs -0r rm -rf --
      find "$ROOT/items" -mindepth 2 -maxdepth 2 -type f \
        \( -name 'inline_realign_shadow.json' -o -name 'stable_window_assistance*.json' \
           -o -name 'text_dosage_trials.json' -o -name 'forced_expansion_trials.json' \
           -o -name 'pending_confirmation_shadow.json' -o -name 'deferred_realign_shadow.json' \
           -o -name 'tail_two_window_rollback_shadow.json' -o -name 'item_summary.json' \
           -o -name 'failure.json' -o -name 'raw_decoder_ablations.json' \) -print0 | xargs -0r rm -f --
    fi
    ;;
  *) echo "unknown mode: $MODE (expected all|analysis|visual|render|stale)" >&2; exit 2 ;;
esac
