# Immediate Qwen FA diagnostics patch

## Added files

```text
scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py
scripts/evaluation/collect_qwen_fa_immediate_suite.py
scripts/evaluation/analyze_qwen_fa_time_coverage.py
scripts/evaluation/summarize_qwen_fa_immediate_diagnostics.py
scripts/training/run_qwen_fa_immediate_diagnostics.sh
tests/test_qwen_fa_immediate_diagnostics.py
docs/sessions/20260725_qwen_fa_long_diagnostic_plan.md
```

## Apply

Copy the files into the same relative paths under `/home/hyan/LyricAlignment`.

## Verify before server inference

```bash
cd /home/hyan/LyricAlignment
python -m compileall -q \
  scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py \
  scripts/evaluation/collect_qwen_fa_immediate_suite.py \
  scripts/evaluation/analyze_qwen_fa_time_coverage.py \
  scripts/evaluation/summarize_qwen_fa_immediate_diagnostics.py
bash -n scripts/training/run_qwen_fa_immediate_diagnostics.sh
pytest -q tests/test_qwen_fa_immediate_diagnostics.py
```

## Smoke

```bash
MIR_MAX_ITEMS=8 LONG_MAX_ITEMS=3 \
OUT_ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_diagnostics_smoke \
bash scripts/training/run_qwen_fa_immediate_diagnostics.sh
```

## Formal diagnostic

```bash
bash scripts/training/run_qwen_fa_immediate_diagnostics.sh
```

The script performs no training. Reruns skip task directories that already contain all four required outputs.
