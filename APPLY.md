# Apply and run

Copy the patch contents into the repository root, preserving paths.

```bash
cd /home/hyan/LyricAlignment
conda activate lyricalign-qwen

python -m compileall -q \
  scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py \
  scripts/evaluation/collect_qwen_fa_240_cliff_probe.py \
  scripts/evaluation/collect_qwen_fa_repeat_probe.py \
  scripts/evaluation/prepare_qwen_fa_immediate_all_selection.py \
  scripts/evaluation/analyze_qwen_fa_error_blocks.py \
  scripts/evaluation/summarize_qwen_fa_immediate_all.py

bash -n scripts/training/run_qwen_fa_immediate_all.sh
bash -n scripts/maintenance/collect_qwen_fa_immediate_all_review.sh

pytest -q \
  tests/test_qwen_fa_immediate_diagnostics.py \
  tests/test_qwen_fa_240_cliff_probe.py \
  tests/test_qwen_fa_immediate_all.py
```

Run all immediate diagnostics:

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_all \
bash scripts/training/run_qwen_fa_immediate_all.sh
```

Collect upload evidence:

```bash
ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_all \
bash scripts/maintenance/collect_qwen_fa_immediate_all_review.sh
```
