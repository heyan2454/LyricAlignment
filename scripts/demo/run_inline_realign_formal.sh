#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=inline_realign_env.sh
source "$SCRIPT_DIR/inline_realign_env.sh"
validate_inline_realign_inputs

OUT_ROOT="${OUT_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728}"
CONFIG="${INLINE_REALIGN_CONFIG:-$REPO_ROOT/configs/experiments/inline_realign_multilingual_formal_20260728.yaml}"
RENDER_MODE="${RENDER_MODE:-after}"          # after | skip
RESUME="${RESUME:-0}"
RETRY_FAILED_ONLY="${RETRY_FAILED_ONLY:-0}"
FROM_STAGE="${FROM_STAGE:-}"
INVALIDATE_STAGE="${INVALIDATE_STAGE:-}"
RESTART_ITEM="${RESTART_ITEM:-}"

cd "$REPO_ROOT"
printf '%s\n' \
  "Inline Realign formal（全机制）" \
  "输出：$OUT_ROOT" \
  "渲染模式：$RENDER_MODE" \
  "监控：$PYTHON_BIN scripts/demo/watch_inline_realign_status.py '$OUT_ROOT'" \
  "分析完成标记：$OUT_ROOT/analysis_complete.json" \
  "渲染完成标记：$OUT_ROOT/render_complete.json"

command=(
  "$PYTHON_BIN" scripts/demo/run_inline_realign_pipeline.py
  --mode formal --config "$CONFIG" --out-root "$OUT_ROOT" --python-bin "$PYTHON_BIN"
  --mir1k-subset-root "$MIR1K_SUBSET_ROOT" --m4-labels "$M4_LABELS" --m4-audio-root "$M4_AUDIO_ROOT"
  --model "$MODEL_SOURCE" --revision "$MODEL_REVISION" --r2-checkpoint "$R2_CHECKPOINT"
  --device "$DEVICE" --demo-prepared-suffixes "$DEMO_PREPARED_SUFFIXES"
  --demo-recursive --require-demo --m4-long-target-secs "$M4_LONG_TARGET_SECS"
  --demo-publish-layout "$DEMO_PUBLISH_LAYOUT" --render-mode "$RENDER_MODE"
)
[[ -n "$DEMO_ROOT" ]] && command+=(--demo-root "$DEMO_ROOT")
[[ -n "$DEMO_PUBLISH_ROOT" ]] && command+=(--demo-publish-root "$DEMO_PUBLISH_ROOT")
[[ "$RESUME" == "1" ]] && command+=(--resume)
[[ "$RETRY_FAILED_ONLY" == "1" ]] && command+=(--retry-failed-only)
[[ -n "$FROM_STAGE" ]] && command+=(--from-stage "$FROM_STAGE")
IFS=',' read -ra stages <<< "$INVALIDATE_STAGE"
for stage in "${stages[@]}"; do [[ -n "$stage" ]] && command+=(--invalidate-stage "$stage"); done
IFS=',' read -ra items <<< "$RESTART_ITEM"
for item in "${items[@]}"; do [[ -n "$item" ]] && command+=(--restart-item "$item"); done

# Held-out MIR-1K remains excluded unless the caller explicitly appends --include-heldout.
exec "${command[@]}" "$@"
