# Asset Inventory

**Status:** server execution; external dataset acquisition remains partial only where upstream access failed
**Updated:** 2026-08-16

| Asset | Expected action | Actual path | Revision/version | Size | Verification | Notes |
|---|---|---|---|---:|---|---|
| Qwen Forced Aligner | downloaded preferred official variant | `/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064` | `c07281df297b9905d24a508279258cccf987a064` | 8 files / ~1.8G cache | passed | Initial transport failure resumed successfully; one M4Singer raw smoke completed. |
| Opencpop | download official source | `/home/hyan/Data/lyricalign/datasets/opencpop` | to verify | 0 | blocked on official access grant | Official site requires a Google Form and emailed download instructions; no public direct archive URL is provided. |
| M4Singer | direct read-only shared-data reuse | `/home/hyan/Data/datasets/m4singer` | `google_drive_archive_20260714` | prior AST audit: 20G / 65,198 files | passed | Migrated raw WAV and `meta.json` lyrics were rechecked at the new path; no second transfer needed. |
| MIR-1K | legacy path pending migration-path confirmation | `/home/hyan/Data/ast_data/mir1k/current` -> `prepared` | to verify | 404 files | partial | No `/home/hyan/Data/datasets/mir1k` directory was found; vocal WAV readable but lyrics mapping has not been audited. |
| MIR-MLPop | official annotations + available Mandarin audio + small Cantonese probe | `/home/hyan/Data/datasets/mir_mlpop` | `240223` / `ad425d5e494bc74ceedcdd3c3ad6c13179886d8a` | 1.2G; 20 cmn WAV + 3 yue WAV | partial upstream availability; local files passed checksum/ffprobe | Academic noncommercial only. Requested all 30 cmn and yue Test IDs 21–25; exact missing IDs are frozen in `acquisition.json`. |
| AMLL TTML DB | sparse annotation snapshot, no commercial audio | `/home/hyan/Data/datasets/amll_ttml_db` | `9006344d572bef64e19d7e06f82beedbf1bd1e5f` | 167M; 3,160 TTML | passed XML parse and checksum | Internal silver pool only; upstream CC0 declaration cannot clear underlying lyric/translation third-party rights. Rights/platform/audio-version audit required. |
| PJS v1.1 | official archive + independent manual phoneme relabels | `/home/hyan/Data/datasets/pjs` | `1.1`; labels `cc08bead6bf2b06e88608a8ece12555bcc720ec9` | 569M; 100 song + 100 speech WAV | archive/checksum/ffprobe passed | Japanese boundary calibration; CC BY-SA 4.0. |
| JamendoLyrics English | download official MultiLang `en/test` raw mixture config | `/home/hyan/Data/datasets/jamendolyrics_en` | `de188c963fd4539bc769b3feb83582e5a9595e36` | 101M; 20 MP3 | raw payload checksum, ffprobe and interval audit passed; vocal asset pending | Six per-track license types occur. Operational benchmark still needs separation plus separator/config/hash manifest to satisfy vocal-only contract. |
| GTSinger Chinese mini | select five song roots covering two singers/five techniques | `/home/hyan/Data/datasets/gtsinger_chinese` | `4426c862beed558b7e1cb8a4dce7e8c0c83bb208` | 239M; 850 selected files | 850/850; checksum, JSON/XML and ffprobe passed | 231 WAV/TextGrid/JSON plus 157 MusicXML; upstream adds unresolved indemnity/employer-authority terms after CC BY-NC-SA, so internal noncommercial research only. |
| iKala | record official restricted source; wait for access grant | `/home/hyan/Data/datasets/ikala` | Zenodo record `3532214` | metadata only; no main audio | blocked_pending_access | No identity-dependent request was submitted. Custom license remains unresolved. |

## Required completion fields

- source and acquisition date;
- resolved model revision or dataset version;
- external absolute path;
- file count and total disk usage;
- sampled audio readability;
- whether direct read-only reuse is possible;
- whether a transfer, symlink or second copy was created;
- verification command and outcome.

Machine-readable audit artifacts are external: `/home/hyan/Data/lyricalign/outputs/audits/ast_discovery.json` and
`/home/hyan/Data/lyricalign/outputs/audits/asset_inventory.json`.
