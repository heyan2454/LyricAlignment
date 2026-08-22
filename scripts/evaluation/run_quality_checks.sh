#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export PYTHONPATH="src:.readline_stub"

echo "== pytest =="
python -m pytest -q \
  tests/evaluation/test_evaluation_v1_split.py \
  tests/test_split.py \
  tests/research_v7/test_detector_v2_contract.py \
  tests/research_v7/test_detector_v2_metrics.py \
  tests/research_v7/test_detector_v2_gt_split.py \
  tests/research_v7/test_detector_v2_evidence.py

echo "== compileall =="
python -m compileall -q src scripts tests/evaluation

echo "== git diff --check =="
git diff --check

echo "== cleanup report audit =="
python - <<'PY'
from pathlib import Path
root = Path("/home/hyan/Data/lyricalign/runs")
missing = []
for p in sorted(root.glob("20260816_evaluation_v1_*")):
    if p.is_dir() and not (p / "cleanup_report.md").exists():
        missing.append(p.name)
if missing:
    print("MISSING:", missing)
else:
    print("All evaluation_v1 batches have cleanup_report.md")
PY

echo "ALL_CHECKS_OK"
