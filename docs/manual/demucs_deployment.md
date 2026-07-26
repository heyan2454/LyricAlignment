# Demucs deployment for lyric-alignment demo experiments

## Scope

This guide installs Demucs in an isolated environment and uses it only as a
vocal-separation input variant.  It does not replace the Qwen environment and
must not change Qwen, Transformers, PEFT, or CUDA packages in
`lyricalign-qwen`.

The project pins `demucs==4.1.0`.  The experiment default is
`htdemucs_ft`, `--two-stems vocals`, `--shifts 0`, and `--overlap 0.25`.
`shifts=0` is intentionally different from the Demucs CLI default: it removes
random shift augmentation and reduces cost for a reproducible separator
ablation.  Keep the same setting for all compared songs.

## Recommended AutoDL layout

```text
Conda environment:
/root/autodl-tmp/AST_storage/conda/envs/demucs

Model cache:
/root/autodl-tmp/AST_storage/Data/lyricalign/models/torch

MIR-1K experiment data:
/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1
```

Do not store downloaded model weights or separated WAV files in the Git
repository.

## 1. Create an isolated environment

```bash
conda create -n demucs python=3.11 ffmpeg -c conda-forge -y
conda run -n demucs python -m pip install --upgrade pip
conda run -n demucs python -m pip install "demucs==4.1.0"
```

Verify that PyTorch can see the GPU:

```bash
conda run -n demucs python - <<'PY'
import importlib.metadata
import torch
print("demucs", importlib.metadata.version("demucs"))
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("cuda_version", torch.version.cuda)
print("device", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
PY
```

If `cuda_available` is false, install a CUDA-enabled PyTorch/torchaudio pair
that matches the server driver using the official PyTorch installation command,
then rerun the check.  Do not guess a CUDA wheel suffix without checking the
server.

## 2. Fix the model cache location and pre-warm

```bash
export TORCH_HOME=/root/autodl-tmp/AST_storage/Data/lyricalign/models/torch
mkdir -p "$TORCH_HOME"

conda run -n demucs demucs --list-models
conda run -n demucs demucs \
  -n htdemucs_ft \
  --two-stems vocals \
  --other-method add \
  --device cuda \
  --shifts 0 \
  --overlap 0.25 \
  --jobs 0 \
  --out /tmp/demucs_preflight \
  /path/to/one_short_mix.wav
```

The first execution downloads model weights.  After pre-warming, record the
cache tree and hashes for offline/repeatable execution:

```bash
find "$TORCH_HOME" -type f -printf '%P\t%s\n' | sort \
  > /home/hyan/Data/lyricalign/demo_diagnostics/demucs_cache_inventory.tsv
find "$TORCH_HOME" -type f -print0 | sort -z | xargs -0 sha256sum \
  > /home/hyan/Data/lyricalign/demo_diagnostics/demucs_cache_sha256.txt
```

## 3. Run the MIR-1K separator preparation

Prepare development songs first:

```bash
cd /home/hyan/LyricAlignment
export TORCH_HOME=/root/autodl-tmp/AST_storage/Data/lyricalign/models/torch

/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python \
  scripts/demo/prepare_mir1k_separator_variants.py \
  --subset-root /home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1 \
  --roles development \
  --separators spleeter demucs \
  --spleeter-model-root /root/autodl-tmp/AST_storage/Data/lyricalign/models/spleeter \
  --spleeter-command "conda run -n spleeter spleeter" \
  --demucs-command "conda run -n demucs demucs" \
  --demucs-version 4.1.0 \
  --demucs-model htdemucs_ft \
  --demucs-device cuda \
  --demucs-shifts 0 \
  --demucs-overlap 0.25 \
  --demucs-jobs 0 \
  --demucs-torch-home "$TORCH_HOME"
```

Each item receives:

```text
audio/mix.wav
audio/official_vocal.wav
audio/spleeter_vocals.wav
audio/spleeter_accompaniment.wav
audio/demucs_htdemucs_ft_vocals.wav
audio/demucs_htdemucs_ft_accompaniment.wav
*.identity.json
*.quality.json
```

The identity records the mix hash, package/model request, command, parameters,
and output hashes.  The quality report rejects silent and near-copy outputs; it
is a structural check, not a singing-separation quality metric.

## 4. OOM and failure recovery

On a 32 GB vGPU, first run without `--demucs-segment`.  If Demucs still raises
CUDA OOM:

```bash
# retry only after the failed process exits
--demucs-segment 7
```

If GPU execution remains unstable, use `--demucs-device cpu`; record this as an
engineering fallback because runtime is no longer comparable.  Re-running the
same command resumes by identity and skips accepted outputs.  Use `--force`
only after deliberately changing or invalidating the separator output.

## 5. Batch demo integration

The general demo entry now accepts Demucs directly:

```bash
scripts/demo/run_qwen_fa_batch.sh /path/to/song_folder \
  --separator demucs \
  --demucs-command "conda run -n demucs demucs" \
  --demucs-version 4.1.0 \
  --demucs-model htdemucs_ft \
  --demucs-device cuda \
  --demucs-shifts 0 \
  --demucs-overlap 0.25 \
  --demucs-torch-home /root/autodl-tmp/AST_storage/Data/lyricalign/models/torch
```

`--stage render` no longer resolves separator weights.  It can rerender an
existing result without Spleeter or Demucs being available, provided the chosen
render audio already exists.

## Fairness requirements

- Separate each full song once, then crop identical windows downstream.
- Use the same sample-rate/channel conversion for every separator.
- Do not normalize one separator differently unless that is a declared factor.
- Keep Demucs model, shifts, overlap, segment, and package version fixed.
- Select the separator on the MIR-1K development subset only.
- Run the held-out subset once after freezing the chosen configuration.
- Report official isolated vocal as a diagnostic upper-bound input, not as a
  deployable separator.
- Alignment metrics are primary; listening and separator structural checks are
  auxiliary evidence.

## Upstream references

- Maintained Demucs repository: <https://github.com/adefossez/demucs>
- PyPI package: <https://pypi.org/project/demucs/>
