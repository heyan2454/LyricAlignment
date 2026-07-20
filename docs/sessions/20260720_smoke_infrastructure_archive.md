# Session: Smoke Infrastructure Archive

**Date:** 2026-07-20  
**Temperature:** hot

## Trigger

对 2026-07-19 after-Qwen-smoke 工作包 review 后，确认短片段 smoke 有效，但工程证据和恢复语义不足，且旧包根目录、状态文档和 manifest 不一致。

## User decisions

- 修复 revision-aware resume、逐样本模型身份、轻量独立证据、runtime 口径和时间戳诊断；
- 音频多格式兼容不是当前主线，未来数据清洗统一模型输入；
- 根目录永久稳定为 `LyricAlignment/`，后缀只用于 archive、run 和 session；
- 资产脚本实际 bug 与环境可复现性必须修复；
- 长音频准备纳入数据清洗，不在本轮建立临时拼接管线；
- M4Singer synthetic long 与未来 natural long 必须分开标记；
- MIR-1K 不加入训练，只可能作为歌词映射可靠时的 test-only/OOD。

## Implemented

### Smoke resume and identity

Skip requires all of:

- previous status is success;
- model ID matches;
- resolved revision matches;
- behavior config hash matches;
- audio SHA256 matches;
- text SHA256 matches.

Failed, corrupt, old-schema or changed-identity outputs are rerun. Writes are atomic.

### Evidence

Each new run writes a lightweight index under `runs/smoke/<run_id>/`:

- `command.txt`;
- `environment_summary.json`;
- `run_summary.json` with external output path and SHA256.

The old 2026-07-19 result is preserved only as a `legacy_report_summary`; missing command/output hash is not fabricated.

### Runtime

The adapter now separates:

- model load;
- ffmpeg decode;
- processor/input preparation;
- CUDA-synchronized forward;
- timestamp decode;
- total alignment excluding model load;
- first-sample cold-start total.

The old 6.253 s remains an undivided legacy wall time.

### Timestamp diagnostics

Separated:

- start time decrease;
- end time decrease;
- negative duration;
- interval overlap;
- gap between items;
- before/after audio range;
- empty output and item-count mismatch.

Overlap/gap are diagnostics and do not automatically mean reverse order.

### Asset and environment scripts

- `verify_assets.py` creates output parent before disk query and returns nonzero for missing required assets;
- `download_opencpop.py` verifies 206/Content-Range, restarts safely on ignored Range, rejects HTML, checks size and optional SHA256;
- `capture_environment.py` records package direct URL/VCS commit when available;
- small pytest coverage was added for resume, diagnostics, output-parent creation and ignored-Range behavior.

## Deferred to data cleaning

- unified audio conversion;
- character schema and boundaries;
- same-song ordered synthetic concatenation;
- 20/30/60/120 second buckets;
- natural long test-only samples;
- split inheritance and leakage audit;
- metrics and training.

## Evidence limits

No Qwen model inference was rerun while creating this archive. Code and lightweight tests can be checked locally, but the schema-v2 model smoke and exact server environment remain pending.
