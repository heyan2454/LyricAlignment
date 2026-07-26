# Demo multilingual input patch validation — 2026-07-26

## Scope

This validation covers the reusable demo path after adding explicit language
selection and English/Japanese alignment units. It does not evaluate
multilingual singing accuracy.

## Implemented interfaces

```bash
scripts/demo/run_qwen_fa_batch.sh <file-or-folder> --language English
scripts/demo/run_qwen_fa_batch.sh <file-or-folder> --language Japanese
scripts/demo/run_qwen_fa_batch.sh <file-or-folder> --language Cantonese
```

Common aliases such as `en`, `ja`, `zh` and `yue` are canonicalized before the
request identity is built.

## Unit rules checked

- English punctuation example: `Hello, world!` -> `Hello | world`.
- Chinese-English mixed example: `今晚 sing with me` ->
  `今 | 晚 | sing | with | me`.
- Japanese example uses a deterministic Nagisa-compatible tokenizer stub and
  preserves punctuation outside timestamp slots.
- ASS rendering reconstructs exact visible word text from display fields.
- Language and alignment-unit mode are included in plan, lyrics identity,
  alignment identity and summary.

## Commands executed

```bash
python -m compileall -q \
  src/lyricalign/demo scripts/demo \
  tests/test_qwen_fa_serial_demo.py \
  tests/test_qwen_fa_batch_demo.py \
  tests/test_qwen_fa_tail_windowed_demo.py

for f in scripts/demo/*.sh; do bash -n "$f"; done

pytest -q \
  tests/test_qwen_fa_serial_demo.py \
  tests/test_qwen_fa_batch_demo.py \
  tests/test_qwen_fa_tail_windowed_demo.py \
  tests/test_audio_separation_quality.py
```

Result:

```text
25 passed
```

English and Japanese alias dry-runs also produced canonical plan identities.
The build environment intentionally lacked `nagisa`; Japanese production parsing
therefore produced the expected explicit dependency error. Japanese unit mapping
was tested with an injected deterministic tokenizer.

## Full-suite limitation

A full `pytest -q` was attempted but stopped during collection because the
archive build environment lacks the pre-existing project dependency `pypinyin`:

```text
tests/test_audio_contract.py
tests/test_m4singer_preparation.py
tests/test_mir1k_partial_align.py
```

This is unchanged from the earlier archive environment and is unrelated to the
demo multilingual patch.

## Not executed here

- real R0/R2 English song inference;
- real R0/R2 Japanese song inference;
- server-side Nagisa installation verification;
- multilingual GT metrics.

The patch is validated for deterministic text-unit mapping, cache identity,
window compatibility and subtitle reconstruction. Accuracy claims require
server runs and labeled data.
