#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:?usage: $0 EXPERIMENT_ROOT [derived|stale|all]}"
MODE="${2:-derived}"
ROOT="$(python - <<'PY' "$ROOT"
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

case "$ROOT" in
  /|/home|/root|/mnt|/mnt/data) echo "refusing dangerous path: $ROOT" >&2; exit 2 ;;
esac
[[ -d "$ROOT" ]] || { echo "nothing to clean: $ROOT"; exit 0; }

case "$MODE" in
  all)
    echo "removing complete experiment root: $ROOT"
    rm -rf -- "$ROOT"
    ;;
  stale)
    python - <<'PY' "$ROOT"
import json, shutil, sys
from pathlib import Path
root = Path(sys.argv[1])
manifest = root / "experiment_manifest.jsonl"
valid = {json.loads(line)["item_id"] for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()} if manifest.is_file() else set()
for path in sorted((root / "items").glob("*")):
    if path.is_dir() and path.name not in valid:
        print(f"remove stale item: {path}")
        shutil.rmtree(path)
PY
    ;;
  derived)
    echo "removing derived summaries, visualizations, renders and shadow experiments; preserving baseline branch caches"
    rm -f -- \
      "$ROOT"/complete.json "$ROOT"/pipeline_complete.json "$ROOT"/pipeline_failure.json \
      "$ROOT"/experiment_summary.json "$ROOT"/followup_analysis_summary.json \
      "$ROOT"/followup_analysis_summary.md "$ROOT"/visualization_summary.json \
      "$ROOT"/demo_render_summary.json "$ROOT"/demo_publish_summary.json \
      "$ROOT"/inline_realign_evidence.tar.gz "$ROOT"/live_status.json \
      "$ROOT"/experiment_live_status.json
    rm -rf -- "$ROOT"/published_demo "$ROOT"/evidence_staging
    if [[ -d "$ROOT/items" ]]; then
      find "$ROOT/items" -mindepth 2 -maxdepth 2 -type d \
        \( -name visuals -o -name render -o -name experimental_alignments \) -print0 | xargs -0r rm -rf --
      find "$ROOT/items" -mindepth 2 -maxdepth 2 -type f \
        \( -name 'inline_realign_shadow.json' -o -name 'stable_window_assistance*.json' \
           -o -name 'forced_expansion_trials.json' -o -name 'pending_confirmation_shadow.json' \
           -o -name 'tail_two_window_rollback_shadow.json' -o -name 'item_summary.json' \
           -o -name 'failure.json' \) -print0 | xargs -0r rm -f --
    fi
    ;;
  *) echo "unknown mode: $MODE (expected derived|stale|all)" >&2; exit 2 ;;
esac
