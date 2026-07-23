# Session Archive: Qwen FA LoRA Full R2

**Date:** 2026-07-23  
**Scope:** archive the completed first-round LoRA experiment and provide a safe manual finalization entry

## Completed

- accepted-only M4Singer song-level split, label construction and round-trip were reported complete by Codex;
- overfit, R0, R1, R2 and R3 pilot runs were reported complete;
- pilot metrics show R2 top-half audio LoRA + projector is better than R0/R1 and R3 does not add benefit at the tested budget;
- full R2 completed 1,110 optimizer steps;
- full R2 validation reached 46.634 ms song-macro boundary MAE at final step 1110;
- periodic selector recorded step 1000 as best at 46.734 ms;
- full R2 M4Singer sealed test produced a metrics file;
- existing MIR-1K result is a pilot OOD result, not final full-R2 OOD.

## Evidence included in this archive

- `results/comparisons/20260723_qwen_fa_lora_summary.json`;
- `reports/progress/20260723_qwen_fa_lora_results.md`;
- original supplied `metrics.json` files for full sealed test, pilot sealed test and pilot MIR-1K OOD;
- full-R2 config and current training/evaluation entrypoints already present in the project;
- `scripts/training/finalize_qwen_fa_r2_manual.sh` for the missing final OOD step.

## Evidence limitations

- pilot and validation values copied from the user's server console are preserved with that provenance; the corresponding external run directories are not duplicated;
- the supplied full sealed-test metrics do not carry checkpoint path/hash;
- no full-R2 MIR-1K OOD metrics were supplied;
- checkpoint binaries, audio, manifests and predictions remain external;
- the archive does not claim to have rerun GPU evaluation locally.

## Manual continuation

On the server, merge/pull this archive and use the existing Conda environment:

```bash
cd /home/hyan/LyricAlignment
conda activate lyricalign-qwen
bash scripts/training/finalize_qwen_fa_r2_manual.sh inspect
bash scripts/training/finalize_qwen_fa_r2_manual.sh run-ood
bash scripts/training/finalize_qwen_fa_r2_manual.sh summarize
```

`inspect` is read-only. `run-ood` refuses to overwrite the final OOD output and does not run sealed test. It records checkpoint/data/config hashes beside the new OOD metrics.

## Remaining work

1. run final full-R2 MIR-1K OOD using the program validation-best checkpoint;
2. retain the existing sealed-test output without rerunning it;
3. inspect the generated evaluation identity and metrics;
4. update the final experiment report/session record;
5. push the repository commits if the server branch remains ahead of `origin/main`.
