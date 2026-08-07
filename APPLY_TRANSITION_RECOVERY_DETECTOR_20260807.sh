#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$SCRIPT_DIR}"

if [[ ! -f "$REPO/README.md" || ! -d "$REPO/docs/research_v7_align_behavior" ]]; then
  echo "[error] REPO does not look like the expected LyricAlignment tree: $REPO" >&2
  exit 2
fi

required=(
  "$REPO/docs/research_transition_recovery_detector_20260807/README.md"
  "$REPO/docs/research_transition_recovery_detector_20260807/00_FACTOR_MODEL_AND_FREEZE.md"
  "$REPO/docs/research_transition_recovery_detector_20260807/01_MASTER_EXPERIMENT_PLAN.md"
  "$REPO/docs/research_transition_recovery_detector_20260807/02_TRANSITION_RECOVERY_MAINLINE.md"
  "$REPO/docs/research_transition_recovery_detector_20260807/03_LEGACY_GAP_COMPLETION.md"
  "$REPO/docs/research_transition_recovery_detector_20260807/04_DETECTOR_RESEARCH_PLAN.md"
  "$REPO/docs/research_transition_recovery_detector_20260807/05_DATA_METRICS_BUDGET.md"
  "$REPO/docs/research_transition_recovery_detector_20260807/06_AGENT_EXECUTION_CONTRACT.md"
  "$REPO/docs/sessions/20260807_transition_recovery_detector_discussion_record.md"
  "$REPO/configs/research_transition_recovery_detector_20260807/session_defaults.yaml"
  "$REPO/TRANSITION_RECOVERY_DETECTOR_20260807_PATCH_MANIFEST.json"
)

for path in "${required[@]}"; do
  [[ -f "$path" ]] || { echo "[error] missing patch file: $path" >&2; exit 3; }
done

grep -q '20260807_transition_recovery_detector_discussion_record.md' "$REPO/docs/sessions/SESSION_INDEX.md" \
  || { echo "[error] SESSION_INDEX was not updated" >&2; exit 4; }

echo "[ok] Transition–Recovery–Detector 20260807 planning patch is present."
echo "[next] Read: $REPO/docs/research_transition_recovery_detector_20260807/README.md"
echo "[contract] $REPO/docs/research_transition_recovery_detector_20260807/06_AGENT_EXECUTION_CONTRACT.md"
