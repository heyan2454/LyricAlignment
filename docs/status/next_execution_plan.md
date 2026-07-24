# Next Execution Plan

**Date:** 2026-07-24  
**Goal:** explain and mitigate the long-context collapse before expanding LoRA scope.

## N1 — controlled dominant-outlier evaluation

Use the frozen selected R2 checkpoint and the Tenor-6 `寻人启事` approximately
150-second sequence. Evaluate:

```text
full sequence
0–90 s
90–120 s
120–140 s
140 s–end
overlapping windows with timestamp re-offsetting
```

Keep lyrics and GT slicing deterministic. Record window boundaries, overlap,
recombination policy, and whether each character is evaluated once or merged.

Decision question:

> Does the 120–140-second collapse disappear when the same local region is
> evaluated without the preceding long context?

## N2 — distinguish likely causes

Depending on N1:

- **windowed succeeds, full context fails:** investigate attention/context-length
  accumulation and use chunked inference;
- **both fail on the same region:** inspect repeated lyrics, local vocal quality,
  weak labels, and transcript ambiguity;
- **failure follows absolute timestamp:** inspect timestamp class decoding and
  late-position calibration;
- **failure follows synthetic joins:** compare with a natural long-song example.

## N3 — optional evidence completion

Only if needed for a formal appendix:

- export seed2 validation reference rows and recompute v3 auxiliary metrics;
- export the exact seed3407 R2 M4Singer test recomputation input;
- run a second full R1 seed to estimate cross-seed R2-minus-R1 variability.

## Deferred

Do not start bottom-half LoRA, larger rank, longer training, or new datasets until
the long-context failure mechanism is better isolated. More capacity may hide or
amplify the failure without explaining it.
