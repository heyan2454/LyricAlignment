# Immediate Qwen FA diagnostics patch

Primary run:

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_all \
bash scripts/training/run_qwen_fa_immediate_all.sh
```

Evidence collection:

```bash
ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_all \
bash scripts/maintenance/collect_qwen_fa_immediate_all_review.sh
```

See `docs/sessions/20260725_qwen_fa_immediate_all_plan.md` for scope and `APPLY.md` for validation commands.
