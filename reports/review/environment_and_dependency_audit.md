# Environment and Dependency Audit

**Updated:** 2026-07-20  
**Status:** historical server facts preserved; exact source lock pending recapture

## Historical server record

- provider: AutoDL
- GPU: NVIDIA GeForce RTX 4080 SUPER, 32760 MiB
- driver: 595.58.03
- Python: 3.12.3
- PyTorch: 2.8.0+cu128
- Transformers: 5.15.0.dev0 installed from source
- huggingface_hub: 1.24.0
- soundfile: 0.14.0
- external data path: `/home/hyan/Data` resolving to the external data disk

## Reproducibility limitation

The legacy archive recorded only `Transformers 5.15.0.dev0`; it did not preserve the source commit. A development version without commit ID is not an exact lock. The archive does not invent or infer that commit.

## Implemented capture mechanism

Before the next server smoke, run:

```bash
python scripts/environment/capture_environment.py \
  --out runs/smoke/<run_id>/environment_full.json
```

The script records:

- Python executable and version;
- platform;
- key package versions;
- package `direct_url.json`, including VCS commit when available;
- PyTorch CUDA runtime and GPU;
- ffmpeg version;
- `nvidia-smi` summary.

The standard smoke script also writes a compact environment summary automatically.

## Dependency files

- `pyproject.toml` declares direct project dependencies and optional smoke helpers;
- `requirements/qwen_smoke_server_known.txt` preserves only versions explicitly known from the historical run;
- once the Transformers commit is captured, create a commit-pinned installation/lock file before formal experiments.

## Git state

- expected remote: `git@github.com:heyan2454/LyricAlignment.git`
- this archive intentionally contains no `.git` directory;
- branch, remote, commit and dirty status must be captured after merge on the server.

## External assets

Data, model weights, full smoke outputs and large logs remain outside Git. Lightweight run summaries reference external paths and SHA256 values.
