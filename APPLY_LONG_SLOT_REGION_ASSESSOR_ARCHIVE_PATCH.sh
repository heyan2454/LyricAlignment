#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$SCRIPT_DIR}"

if [[ ! -f "$REPO/README.md" || ! -d "$REPO/docs/research_v7_align_behavior" ]]; then
  echo "[error] REPO does not look like the expected LyricAlignment tree: $REPO" >&2
  exit 2
fi

required=(
  "$REPO/docs/research_v7_align_behavior/13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md"
  "$REPO/docs/research_v7_align_behavior/14_AGENT_EXECUTION_CONTRACT_12H.md"
  "$REPO/docs/sessions/20260804_align_behavior_slot_region_assessor_archive.md"
  "$REPO/docs/research_v7_align_behavior/11_STAGE_B_FORMAL_REPORT.md"
  "$REPO/docs/research_v7_align_behavior/12_COMPLETION_AUDIT.md"
)

for path in "${required[@]}"; do
  [[ -f "$path" ]] || { echo "[error] missing patch file: $path" >&2; exit 3; }
done

grep -q 'fixed 60s' "$REPO/docs/research_v7_align_behavior/13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md" || {
  echo "[error] reviewed plan marker missing" >&2; exit 4;
}
grep -q '人工结果与标签已存在' "$REPO/docs/research_v7_align_behavior/12_COMPLETION_AUDIT.md" || {
  echo "[error] human-review correction marker missing" >&2; exit 5;
}

echo "[ok] reviewed 2026-08-04 long-timeline slot/region-assessor archive is present: $REPO"
echo "[read] $REPO/docs/research_v7_align_behavior/13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md"
