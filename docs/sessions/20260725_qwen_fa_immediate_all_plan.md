# Qwen FA immediate diagnostic all-in-one plan (2026-07-25)

## Purpose

Collect every no-training result that can immediately change the explanation and design of the long-audio follow-up.

## Included

1. Timestamp-class coverage for M4Singer train/test, synthetic b180 and MIR-1K.
2. R0/R1/R2 full b180 raw-vs-fixed, seam-distance and input-mask audit.
3. R0/R1/R2 natural MIR-1K long-audio audit.
4. Three deterministic 5–15 s, 15–40 character samples shifted to 0, 60, 120, 180, 220, 232, 236 and 240 s.
5. Full-vs-crop audit for the three worst archived R2 b180 items plus one normal control.
6. Dense raw and key tuned-model scans around the ~240 s cliff.
7. Equal-total A/B controls:
   - silence(240)+A+B
   - silence(180)+A+silence(60)+B
   - A+silence(240)+B
8. Repeated-content controls for gaps 0, 0.5, 1, 2, 4 and 8 s:
   - A+silence+A
   - A+silence+B
9. CPU summaries of raw backward jumps, repair blocks, entropy, margin and signed class error.

## Excluded

- New training.
- LoRA scale/layer ablation.
- Full hard/crossfade/silence join augmentation sweep.
- Homophone or near-repeat augmentation.

## Primary entry

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_all \
bash scripts/training/run_qwen_fa_immediate_all.sh
```

The pipeline is resumable. Completed task directories with identity, item summary, input audit and diagnostic rows are skipped.

## Evidence collection

```bash
ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_all \
bash scripts/maintenance/collect_qwen_fa_immediate_all_review.sh
```

The staged evidence excludes audio and ensures every staged file is no larger than 500 KiB (512000 bytes).
