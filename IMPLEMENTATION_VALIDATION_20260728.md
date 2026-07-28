# Inline Realign v4 implementation validation — 2026-07-28

## Scope

Validated source implementation, configuration wiring, metric aggregation, resume identities, static visualization primitives and shell entry syntax in the archive environment.

## Results

### Static checks

```text
python -m compileall -q src scripts tests: passed
bash -n for every scripts/**/*.sh: passed
```

### Focused Inline Realign regression

```text
90 passed
```

Covered:

- strict silence planning and active-span contract;
- silence compression time mapping;
- negative/zero/positive duration PMF;
- canonical tolerant missing-unit penalty;
- full-reference metric aggregation;
- YAML/variant registry consistency;
- resolved primary variant handling;
- run-state output mutation detection;
- visual source identity invalidation;
- existing pipeline, strict artifact, font and diagnostic regressions.

### Synthetic static-visualization integration

A synthetic item was passed through the actual `render_item()` entry rather than only primitive plotting functions. It generated 24 non-empty outputs covering grouped duration PMFs, decoder/commit/window inconsistency, branch-specific timeline pages and visual analysis metadata.

The archive sandbox does not contain Noto CJK, so this integration used DejaVu Sans and emitted expected Chinese glyph warnings. Exact SC behavior is separately fail-closed in the server verification script.

### Broad repository tests

```text
209 passed
```

Command excluded only three collection modules whose optional dependency `pypinyin` is absent from the archive validation environment:

```text
tests/test_audio_contract.py
tests/test_m4singer_preparation.py
tests/test_mir1k_partial_align.py
```

A full unfiltered test invocation stops during collection with exactly those three `ModuleNotFoundError: pypinyin` errors. This is an environment limitation, not a claim that the three tests passed.

### Warnings

Ten glyph warnings occur only in a local synthetic plotting test because this sandbox does not have the server's Noto CJK font. The implementation does not accept this fallback in production. Server preflight must run:

```bash
bash scripts/demo/verify_inline_realign_v4.sh
```

and must report both fontconfig and Matplotlib family as:

```text
Noto Sans CJK SC
```

## Not executed in this environment

- Real Qwen3 ForcedAligner model loading;
- R2 adapter loading;
- CUDA inference;
- real Demo/MIR-1K/M4Singer smoke;
- full multi-song FFmpeg rendering;
- server-specific TTC index extraction.

These require the user's server paths and assets. Therefore this archive is implementation-complete and locally regression-tested, but real experimental correctness remains subject to server smoke/formal evidence.

## Required server acceptance

1. `verify_inline_realign_v4.sh` passes with exact SC face and no glyph warnings.
2. Smoke analysis reaches `analysis_complete.json` with zero failed items.
3. Representative static pages visibly show characters, windows, negative/zero durations and realign execution.
4. Smoke render produces five non-empty videos per Demo.
5. Interrupt/resume is tested once during experiment and once during render.
6. Only after these checks should formal start.
