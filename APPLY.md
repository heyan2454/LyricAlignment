# Apply the repaired archive

This archive is rooted at `LyricAlignment/`. Apply it over the repository root
only after preserving local modifications.

```bash
cd /home/hyan/LyricAlignment
git status --short

# Extract/copy the archive over this directory while preserving relative paths.

conda activate lyricalign-qwen
python -m compileall -q src scripts tests
pytest -q \
  tests/test_character_metrics.py \
  tests/test_recompute_character_metrics.py \
  tests/test_qwen_fa_training_entrypoint.py \
  tests/test_qwen_fa_followup_entrypoint.py \
  tests/test_qwen_fa_finalize_entrypoint.py \
  tests/test_qwen_fa_labels.py \
  tests/test_qwen_fa_model.py \
  tests/test_smoke_helpers.py

bash -n scripts/training/run_full_r2_mir1k_ood_fixed_once.sh
bash -n scripts/training/run_qwen_fa_r2_missing_evaluations.sh
bash -n scripts/training/collect_qwen_fa_followup_supplement.sh
```

Do not rerun completed test/OOD evaluations merely to apply this archive.

The next planned experiment is described in:

```text
docs/status/next_execution_plan.md
```
