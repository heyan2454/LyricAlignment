# Archive Report: M4Singer Rule Review

**Archive date:** 2026-07-23
**Output archive:** `LyricAlignment_20260723_m4singer_rule_review_archive.zip`
**Stable extracted root:** `LyricAlignment/`  
**Source archive:** `LyricAlignment_202607221709_manual2beforeslur.zip`

## Purpose

整理当前 M4Singer 规则映射与 MIR-1K vocal-only OOD 状态，清除顶层文档中的旧 canonical 口径，并保留旧结果作为明确标注的历史记录。此次归档不重新运行服务器上的 20,896 条全量数据处理，也不开展训练、评测或新的数据规则实现。

## Current canonical recorded

### M4Singer

- source records: 20,896;
- accepted `rule_validated` candidates: 20,298;
- review required: 598;
- rejected/failed: 0;
- character annotations: 193,666;
- manifest SHA-256: `22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a`;
- character annotation SHA-256: `ba28f0e0c5f5d6c850b47632808ccc60052f3be397f3316ee95bc95678ca613d`.

The accepted records are rule-validated candidates, not a claim of full manual high-confidence confirmation.

### MIR-1K

- zero-based channel index 1 manually confirmed as vocal on 2026-07-22;
- 17 vocal-only songs / 2,035 character annotations;
- fixed usage: `test` / `ood_test_only`;
- manifest SHA-256: `bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f`.

## Key document updates

- rewrote `README.md`, `AI_SESSION_ENTRY.md` and `docs/status/project_current.md` around the 20,298/598 canonical;
- added `docs/sessions/20260723_m4singer_rule_review.md`;
- added `reports/progress/20260723_dataset_mapping_progress.md`;
- added lightweight machine-readable inventory at `runs/data_preparation/20260723_canonical_inventory/run_summary.json`;
- updated dataset registry and 20/30/60/180-second long-audio terminology;
- marked 6,051/14,845, 66 items and 18,057/2,839 as historical, invalid or superseded according to the supplied record;
- retained dated historical reports, adding a superseded-status notice where they could otherwise be mistaken for current state.

## Evidence boundary

The archive keeps only the information needed to identify and reproduce the current external artifacts: paths, counts, role, key processing identity and SHA-256 values. It does not duplicate large JSONL manifests, audio, per-item review images or full logs.

The current canonical facts were supplied from the server-side Codex record. They were not independently regenerated in this local archive environment because the external datasets are not present here.

## Local archive validation

- project root remains `LyricAlignment/`;
- dataset source modules and scripts are present;
- Python source compilation was checked during archive construction;
- generated archive manifest verifies every included file by size and SHA-256;
- full dataset processing and full test execution were intentionally not required as archive evidence.

## Current entry

`docs/sessions/20260723_m4singer_rule_review.md`
