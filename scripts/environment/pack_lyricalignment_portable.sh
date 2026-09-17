#!/usr/bin/env bash
set -euo pipefail

# Portable source-only packer (归位件, 原为仓库外散落脚本 /home/hyan/pack_lyricalignment.sh, 2026-08-08 版).
#
# 与主入口 pack_lyricalignment.sh 的区别：本变体额外传入一组 --exclude-root，
# 只打包"可移植源码"，把模型/备份/run 输出/results/reports/docs/sessions/docs/archive
# 以及 training/research/evaluation 脚本、docs/manual、docs/status 全部排除，
# 用于对外分享或上传的瘦身包；主入口打包完整 tracked 快照（含文档与 results）。
# exclude 清单是 2026-08-08 的口径，目录结构此后有演进，启用前需按需复核。
#
# 从主入口同步的三处改进：输出目录 mkdir -p、秒级时间戳（避免同分钟重名被拒）、
# 结束后 printf 输出归档路径。其余逻辑与原散落版本保持一致。
#
# Package the exact Git-tracked project snapshot.  The repository's archive
# builder supplies a stable root, per-file SHA-256 manifest, and self-check.
# Stable repository root. Override only when packaging a separate checkout.
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

# Models are local artifacts, never part of the portable source archive.
# Local/derived artifacts never enter the portable archive: models (checkpoints),
# backups, run outputs, historical sessions/archive notes, root patch archives.
python3 "$builder" --output "$archive" --root-name LyricAlignment \
  --exclude-root models --exclude-root .patch_backups --exclude-root .repair_backups \
  --exclude-root runs --exclude-root results --exclude-root reports \
  --exclude-root docs/sessions --exclude-root docs/archive \
  --exclude-root docs/research_v6 --exclude-root docs/research_fullslot_serial_detector \
  --exclude-root scripts/training --exclude-root scripts/research \
  --exclude-root scripts/evaluation \
  --exclude-root docs/manual --exclude-root docs/status
printf '%s\n' "$archive"
