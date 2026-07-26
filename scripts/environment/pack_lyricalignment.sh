#!/usr/bin/env bash
set -euo pipefail

# Package the exact Git-tracked project snapshot. The Python builder excludes
# any stale tracked generated manifest, writes one fresh manifest, and verifies
# that every ZIP member name is unique.
LYRICALIGN_ROOT="${LYRICALIGN_ROOT:-/home/hyan/LyricAlignment}"
OUTPUT_DIR="${OUTPUT_DIR:-/home/hyan}"

usage() {
  echo "Usage: $0 NOTE" >&2
  echo "Example: $0 after_qwen_smoke" >&2
}

if [[ $# -ne 1 || -z "${1//[[:space:]]/}" ]]; then
  usage
  exit 2
fi
if [[ ! -d "$LYRICALIGN_ROOT" ]]; then
  echo "LyricAlignment directory not found: $LYRICALIGN_ROOT" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi
builder="$LYRICALIGN_ROOT/scripts/environment/build_archive.py"
if [[ ! -f "$builder" ]]; then
  echo "Archive builder not found: $builder" >&2
  exit 1
fi
if ! git -C "$LYRICALIGN_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "LyricAlignment root is not a Git worktree: $LYRICALIGN_ROOT" >&2
  exit 1
fi

note="$({ printf '%s' "$1" | sed -E 's/[^[:alnum:]._-]+/_/g; s/^[_-]+//; s/[_-]+$//'; } || true)"
if [[ -z "$note" ]]; then
  echo "NOTE contains no filename-safe characters" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
timestamp="$(date -u +%Y%m%d%H%M%S)"
archive="$OUTPUT_DIR/LyricAlignment_${timestamp}_${note}.zip"
if [[ -e "$archive" ]]; then
  echo "Refusing to overwrite existing archive: $archive" >&2
  exit 1
fi

python3 "$builder" --output "$archive" --root-name LyricAlignment
printf '%s\n' "$archive"
