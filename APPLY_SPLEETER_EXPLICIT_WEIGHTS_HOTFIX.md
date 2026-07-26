# Spleeter explicit weights hotfix

This patch removes the incorrect hard dependency on `2stems/.probe`.
It validates actual TensorFlow checkpoint or SavedModel files instead.

Apply from the directory containing the archive:

```bash
unzip -o LyricAlignment_spleeter_explicit_weights_hotfix_20260726.zip -d /home/hyan
cd /home/hyan/LyricAlignment
chmod +x scripts/demo/run_qwen_fa_batch.sh scripts/demo/validate_spleeter_model.py
```

Validate existing weights:

```bash
python scripts/demo/validate_spleeter_model.py \
  --model-root /root/.cache/spleeter_models
```

Then rerun the original batch command. `--spleeter-model-root` accepts either
the parent model root or the explicit `2stems` directory.
