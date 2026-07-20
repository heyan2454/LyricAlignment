# AST Dataset Reuse Audit

**Status:** server inspection completed 2026-07-19  
**Mode:** read-only

## M4Singer

- discovered path: `/home/hyan/Data/datasets/m4singer` (migrated shared-data root)
- raw/prepared/separated: migrated raw archive and extracted WAV/TextGrid/meta JSON; this project will not depend on AST prepared derivative tables
- dataset version/license evidence: AST config `google_drive_archive_20260714`; CC BY-NC-SA 4.0 non-commercial noted in config
- file count and disk usage: 65,198 files; 20G reported by `du -sh`
- readable audio sample: passed after migration; `Alto-1#newboy/0000.wav`, PCM s16le, 48 kHz, mono, 5.005 s
- reliable audio-to-lyrics mapping: yes for raw smoke: root `meta.json` has per-item `item_name` and Chinese `txt`; sample `Alto-1#newboy#0000` maps to `0000.wav` and `好的是的我看见到处是阳光`
- AST may overwrite in place: preparation scripts exist; LyricAlignment will only read raw assets and will not invoke AST scripts
- comparison with user-downloaded copy: not possible: `/home/hyan/m4singer.zip.filepart` is an incomplete 2.7G partial file, not a complete archive
- decision: direct read-only reference to the shared `datasets` root
- reason: the migrated copy contains the required raw audio plus existing lyrics and no longer requires AST data-path binding

## MIR-1K

- discovered path: legacy `/home/hyan/Data/ast_data/mir1k/current`, a symlink to `prepared`; no corresponding `datasets/mir1k` root was found during this correction
- raw/prepared/separated: prepared layout
- file count and disk usage: 404 files; exact unique size deferred because AST may use hard links
- readable audio sample: passed; `clips/Ani_1_06/vocal.wav`, PCM s16le, 16 kHz, mono, 6.464 s
- reliable audio-to-lyrics mapping for smoke: not audited; therefore no MIR-1K sample is configured
- vocal and mix availability: vocal confirmed; mix availability not audited
- decision: direct reference for audio discovery; raw smoke deferred pending text mapping audit
- reason: no lyric association is inferred or constructed in this stage

## Rules

- 不修改 AST 数据；
- 不依赖 AST Python 源码；
- 不因路径不美观而复制数据；
- 只有 hash/结构核验后，才能判断用户准备上传的 M4Singer 是否重复；
- 无可靠歌词映射时，标记 raw smoke 暂不可用，不在本轮转换。
