#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python "$ROOT/scripts/demo/run_qwen_fa_batch.py" "$@"
