# Archive Report: Smoke Infrastructure Fix

**Archive date:** 2026-07-20  
**Output archive:** `LyricAlignment_20260720_smoke_infra_fix.zip`  
**Stable extracted root:** `LyricAlignment/`  
**Source:** `LyricAlignment_202607191737_after_qwen_smoke.zip`

## Purpose

将一条已报告成功但证据不足的 M4Singer short smoke，升级为后续可恢复、可追踪、可比较的标准 smoke 基础设施；同步修复资产脚本、环境复现和文档状态。

## Code changes

- revision/config/input-aware success resume；
- failed/corrupt/changed outputs rerun；
- atomic per-sample writes；
- per-sample model ID/requested revision/resolved revision；
- audio/text/config hashes；
- lightweight run command/environment/summary and external output hash；
- phase-level runtime with CUDA synchronization；
- start/end reverse order separated from overlap/gap；
- ffmpeg-derived duration instead of WAV-only `wave` duration；
- fixed asset output-parent bug；
- robust OpenCpop HTTP range handling, HTML rejection, size/hash checks；
- environment capture including package `direct_url.json`；
- tests for critical pure behavior.

## Documentation changes

- root naming rule fixed to `LyricAlignment/`；
- current state no longer says code/model smoke are unimplemented；
- legacy 6.253 s reclassified as undivided cold/unknown wall time；
- legacy run evidence preserved honestly without inventing missing hash；
- long-audio construction moved into unified data cleaning；
- future data distinguishes `native_short`, `synthetic_concat`, `natural_long`；
- next plan now starts with server merge/test/schema-v2 rerun, then data cleaning.

## Scope intentionally not executed

- no Qwen inference rerun during archive creation；
- no character-boundary conversion；
- no synthetic long-audio generation；
- no metric or metric smoke；
- no LoRA/training；
- no OpenCpop authorization bypass.

## Validation required before use

The archive creation process ran local compile/tests (`5 passed`) and will regenerate/verify the final manifest after all edits. Server-specific model inference, exact environment capture and external-path checks remain the next execution stage.

## Session temperatures

| Session | Temperature | Reason |
|---|---|---|
| `20260720_smoke_infrastructure_archive.md` | hot | Current merge and execution entry. |
| `20260719_asset_preparation_and_raw_smoke_scope.md` | warm | Historical scope and asset decisions remain useful. |
| `20260719_chinese_dataset_training_route.md` | warm | Long-term dataset/training route remains relevant. |
| `20260719_structure_and_data_curation_revision.md` | cold | Stable decisions migrated to manuals/status. |
