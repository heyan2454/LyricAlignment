# Apply and run

This is a relative-path patch for `/home/hyan/LyricAlignment`.

```bash
cd /home/hyan/LyricAlignment

git status --short
# Copy/extract this patch over the repository root, preserving relative paths.

conda activate lyricalign-qwen
python -m compileall -q src scripts tests
pytest -q \
  tests/test_synthetic.py \
  tests/test_qwen_fa_followup_entrypoint.py \
  tests/test_qwen_fa_training_entrypoint.py \
  tests/test_qwen_fa_finalize_entrypoint.py \
  tests/test_qwen_fa_labels.py \
  tests/test_character_metrics.py \
  tests/test_smoke_helpers.py \
  tests/test_qwen_fa_model.py

bash scripts/training/launch_qwen_fa_followup_detached.sh start
bash scripts/training/launch_qwen_fa_followup_detached.sh status
```

The default writes a second-seed recommendation but does not launch full seed-2 R2. To permit automatic continuation when the validation-only gate passes:

```bash
export AUTO_RUN_FULL_SEED2=1
bash scripts/training/launch_qwen_fa_followup_detached.sh start
```
