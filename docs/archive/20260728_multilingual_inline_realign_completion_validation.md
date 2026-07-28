# 2026-07-28 Multilingual Inline-Realign Completion Validation

## Scope

This validation covers the source/config/documentation implementation for:

- dynamic all-discovered formal Test Demo selection;
- one-per-discovered-language smoke selection;
- per-item multilingual parsing, model language identity and grouped reporting;
- canonical central outputs plus adjacent/directory link-only publishing;
- repaired local-rerun prediction schema;
- isolated stable-window and future-text expansion trials;
- automatic detector versus GT case/unit precision and recall;
- GT-oracle and GT-clean local-realign cases;
- exact, +2 and +4 context pairwise consensus;
- stable-prefix expansion guard;
- cross-window pending-confirmation shadow;
- severe-tail two-window rollback shadow;
- automatic incomplete shadow;
- legacy R2 behavioral comparison;
- M4Singer 60/120/180-second synthetic-long buckets and seam-near/far metrics;
- bounded evidence and archive construction without media, weights or caches.

All newly added repair/writeback mechanisms remain shadow-only.

## Static and regression validation

```text
python -m compileall -q src scripts tests       passed
bash -n for every scripts/**/*.sh               passed
inline + archive focused tests                  38 passed
all locally runnable tests                      181 passed
```

Locally runnable command:

```bash
PYTHONPATH=src pytest -q \
  --ignore=tests/test_audio_contract.py \
  --ignore=tests/test_m4singer_preparation.py \
  --ignore=tests/test_mir1k_partial_align.py
```

A full collection attempt stopped before execution because this local container
lacks `pypinyin`. The three blocked modules are the existing audio/M4Singer/
MIR-1K preparation tests listed above. No test that was collected and executed
failed.

## Archive-builder validation

The archive builder now supports both:

1. a normal Git checkout using `git ls-files`; and
2. a portable source snapshot without `.git`, using a conservative filesystem
   scan that excludes caches, local paths, media, model artifacts, generated
   archives and backup files.

A dedicated fallback regression verifies that required dataset source modules
remain included while `.wav`, `__pycache__` and `*.bak_prearchive` are excluded.
The generated ZIP is independently checked for duplicate members, unexpected
members, size/hash mismatches and required modules.

## Input and output contract

Formal does not encode current Test Demo counts. It discovers every original
media/lyrics pair with a reusable prepared vocal and records the resulting
language counts in `input_audit.json`. Smoke samples one item per discovered
language unless an explicit temporary cap is given.

Canonical outputs remain under the run root. `adjacent` and `directory` publish
layouts create relative symlinks and small manifests, not duplicate videos or
alignment JSON. Rendering remains globally ordered after all alignment/shadow
experiments finish.

## Validation limits

This local archive environment does not contain the server Qwen snapshot, R2
checkpoint or real M4Singer/MIR-1K/Test Demo assets. Therefore this validation
does not claim that the newly implemented shadow experiments improve model
quality. In particular, the following still require server evidence:

- multilingual Qwen inference and Japanese Nagisa execution;
- automatic detector precision/recall values;
- GT-clean harm values;
- exact/+2/+4 accepted repair yield;
- stable-prefix rejection of dangerous transcript expansion;
- pending-confirmation recovery;
- two-window rollback benefit;
- automatic incomplete downstream behavior;
- historical R2 versus B0/B1/B2/B3 listening comparisons;
- M4Singer duration/seam trends.

The production path still does not automatically write local repairs, hold a
real serial pending span, roll back real cursors, or replace B2 with incomplete.
