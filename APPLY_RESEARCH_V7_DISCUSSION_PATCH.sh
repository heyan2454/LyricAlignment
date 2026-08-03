#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$SCRIPT_DIR}"

if [[ ! -f "$REPO/README.md" || ! -d "$REPO/docs/research_v6" ]]; then
  echo "[error] REPO does not look like the expected LyricAlignment base: $REPO" >&2
  echo "Extract this patch over the original LyricAlignment_202608010232_beforehierchange tree." >&2
  exit 2
fi

required=(
  "$REPO/docs/research_v7_align_behavior/README.md"
  "$REPO/docs/research_v7_align_behavior/00_EXECUTION_PLAN.md"
  "$REPO/docs/research_v7_align_behavior/01_USER_DECISIONS_AND_RATIONALE.md"
  "$REPO/docs/research_v7_align_behavior/08_AGENT_HANDOFF.md"
  "$REPO/configs/research_v7/mutation_catalog.example.yaml"
)

for path in "${required[@]}"; do
  [[ -f "$path" ]] || { echo "[error] missing patch file: $path" >&2; exit 3; }
done

echo "[ok] Research v7 discussion patch is present at: $REPO"
echo "Read: $REPO/docs/research_v7_align_behavior/README.md"
