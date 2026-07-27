#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-python}"
MANIFEST="${MIR1K_OOD_MANIFEST:-/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood/mir1k_vocal_ood_manifest.jsonl}"
CHARACTERS="${MIR1K_OOD_CHARACTERS:-/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood/mir1k_vocal_ood_characters.jsonl}"
MIR1K_ROOT="${MIR1K_ROOT:-/home/hyan/Data/datasets/mir1k/raw/MIR-1K}"
SUBSET_ROOT="${SUBSET_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1}"
QUICK_V2_EXTRA_COUNT="${QUICK_V2_EXTRA_COUNT:-4}"
DEMUCS_COMMAND="${DEMUCS_COMMAND:-}"

cd "$REPO_ROOT"
"$PYTHON_BIN" scripts/demo/prepare_mir1k_demo_subset.py \
  --manifest "$MANIFEST" \
  --characters "$CHARACTERS" \
  --mir1k-root "$MIR1K_ROOT" \
  --out-dir "$SUBSET_ROOT" \
  --development-count 8 \
  --heldout-count 4 \
  --quick-v2-extra-count "$QUICK_V2_EXTRA_COUNT" \
  --seed 20260727 \
  --units-per-line 12

separator_args=(
  "$PYTHON_BIN" scripts/demo/prepare_mir1k_separator_variants.py
  --subset-root "$SUBSET_ROOT"
  --roles quick_v2_extra
  --separators demucs
  --continue-on-error
)
if [[ -n "$DEMUCS_COMMAND" ]]; then
  separator_args+=(--demucs-command "$DEMUCS_COMMAND")
fi
"${separator_args[@]}"

"$PYTHON_BIN" - "$SUBSET_ROOT" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
rows = [json.loads(line) for line in (root / "selection.jsonl").read_text(encoding="utf-8").splitlines() if line]
summary = {}
for role in ("development", "quick_v2_extra", "heldout", "spare"):
    summary[role] = [str(row["item_id"]) for row in rows if row.get("selection_role") == role]
missing = []
for item_id in summary["development"] + summary["quick_v2_extra"]:
    item = root / "items" / item_id
    for relative in (
        "lyrics.txt", "ground_truth.characters.jsonl", "audio/official_vocal.wav",
        "audio/demucs_htdemucs_ft_vocals.wav",
    ):
        if not (item / relative).is_file():
            missing.append(f"{item_id}/{relative}")
print(json.dumps({"roles": summary, "missing_required_files": missing}, ensure_ascii=False, indent=2))
if missing:
    raise SystemExit(1)
PY
