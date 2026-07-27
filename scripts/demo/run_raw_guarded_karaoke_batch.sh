#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
exec "$PYTHON_BIN" "$ROOT/scripts/demo/run_raw_guarded_karaoke_batch.py" "$@"
