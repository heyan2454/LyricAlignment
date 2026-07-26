#!/usr/bin/env bash
# Resumable, checksum-verified download of the official Spleeter 2-stem model.
set -Eeuo pipefail

MODEL_NAME="${MODEL_NAME:-2stems}"
RELEASE="${SPLEETER_RELEASE:-v1.4.0}"
MODEL_ROOT="${SPLEETER_MODEL_ROOT:-$HOME/.cache/spleeter_models}"
CACHE_ROOT="${SPLEETER_DOWNLOAD_CACHE:-$HOME/.cache/spleeter_downloads}"
BASE_URL="https://github.com/deezer/spleeter/releases/download/$RELEASE"
ARCHIVE="$CACHE_ROOT/$MODEL_NAME-$RELEASE.tar.gz"
CHECKSUM_INDEX="$CACHE_ROOT/checksum-$RELEASE.json"
TARGET="$MODEL_ROOT/$MODEL_NAME"
STAGE="$MODEL_ROOT/.${MODEL_NAME}.stage.$$"

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

for command in curl tar sha256sum python; do
  command -v "$command" >/dev/null 2>&1 || fail "required command not found: $command"
done
mkdir -p "$MODEL_ROOT" "$CACHE_ROOT"

log "download/resume $MODEL_NAME archive"
curl --fail --location \
  --retry 20 --retry-delay 3 --retry-all-errors \
  --continue-at - \
  --output "$ARCHIVE" \
  "$BASE_URL/$MODEL_NAME.tar.gz"

log "download checksum index"
curl --fail --location \
  --retry 20 --retry-delay 3 --retry-all-errors \
  --output "$CHECKSUM_INDEX.tmp" \
  "$BASE_URL/checksum.json"
mv -f "$CHECKSUM_INDEX.tmp" "$CHECKSUM_INDEX"

expected="$(python - "$CHECKSUM_INDEX" "$MODEL_NAME" <<'PY'
import json,sys
from pathlib import Path
index=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
value=index.get(sys.argv[2])
if not value:
    raise SystemExit(f'checksum index has no entry for {sys.argv[2]}')
print(value)
PY
)"
actual="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
[[ "$actual" == "$expected" ]] || fail "archive checksum mismatch: expected=$expected actual=$actual"

log "extract into staging directory"
rm -rf "$STAGE"
mkdir -p "$STAGE"
tar -xzf "$ARCHIVE" -C "$STAGE"
[[ -n "$(find "$STAGE" -type f -print -quit)" ]] || fail "model archive extracted no files"

# Optional provenance marker for this downloader. Runtime validation uses the actual
# TensorFlow checkpoint files and does not require this marker.
touch "$STAGE/.probe"
rm -rf "$TARGET.old"
if [[ -e "$TARGET" ]]; then
  mv "$TARGET" "$TARGET.old"
fi
mv "$STAGE" "$TARGET"
rm -rf "$TARGET.old"

log "installed model: $TARGET"
find "$TARGET" -maxdepth 1 -type f -printf '%f\t%s bytes\n' | sort
