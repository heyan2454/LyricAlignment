#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
exec "$PYTHON_BIN" scripts/demo/run_decoder_realign_comparison_batch.py "$@"
