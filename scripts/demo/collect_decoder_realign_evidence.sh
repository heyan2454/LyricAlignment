#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="${PYTHON_BIN:-python}"
exec "$PYTHON_BIN" scripts/demo/collect_decoder_realign_evidence.py "$@"
