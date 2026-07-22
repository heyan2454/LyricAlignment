#!/usr/bin/env bash
set -euo pipefail
RUN=/home/hyan/Data/lyricalign/derived/20260722_dataset_prepare_repair
PYTHONPATH=src python scripts/datasets/audit_m4singer.py --m4singer-root /home/hyan/Data/datasets/m4singer/raw/extracted/m4singer --out-dir "$RUN/audit"
PYTHONPATH=src python scripts/datasets/prepare_m4singer.py --m4singer-root /home/hyan/Data/datasets/m4singer/raw/extracted/m4singer --out-dir "$RUN/prepare" --include-audio-sha256
PYTHONPATH=src python scripts/datasets/freeze_m4singer_split.py --input "$RUN/prepare/m4singer_manifest.jsonl" --out-dir "$RUN/split" --seed m4singer-v2-song-split --validation-percent 10
PYTHONPATH=src python scripts/datasets/inventory_vocal_audio.py --manifest "$RUN/split/m4singer_accepted_split_manifest.jsonl" --audio-root /home/hyan/Data/datasets/m4singer/raw/extracted/m4singer --out-dir "$RUN/inventory" --vocal-source-type native_vocal --include-sha256
for bucket in 20 30 60 180; do PYTHONPATH=src python scripts/datasets/build_synthetic_long.py --manifest "$RUN/split/m4singer_accepted_split_manifest.jsonl" --annotations "$RUN/prepare/m4singer_character_annotations.jsonl" --audio-root /home/hyan/Data/datasets/m4singer/raw/extracted/m4singer --out-dir "$RUN/synthetic_$bucket" --bucket-sec "$bucket"; done
python -m compileall -q src scripts tests
PYTHONPATH=src pytest -q
