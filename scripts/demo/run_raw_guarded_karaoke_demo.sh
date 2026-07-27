#!/usr/bin/env bash
# Compatibility entry for the historical fixed-song demo.
# With CLI arguments it delegates directly to the general batch entry.
# Renderer used downstream: scripts/demo/render_raw_guarded_karaoke.py
set -Eeuo pipefail
PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
ENTRY="$PROJECT/scripts/demo/run_raw_guarded_karaoke_batch.sh"

if (( $# > 0 )); then
  exec "$ENTRY" "$@"
fi

DEMO_ROOT="${DEMO_ROOT:-$PROJECT/夜苏打}"
SOURCE_MEDIA="${SOURCE_MEDIA:-$DEMO_ROOT/夜苏打.mp4}"
LYRICS="${LYRICS:-$DEMO_ROOT/歌词.txt}"
OUT_ROOT="${OUT_ROOT:-$DEMO_ROOT/qwen_fa_raw_guarded_demo}"
LANGUAGE="${LANGUAGE:-Chinese}"
SEPARATOR="${SEPARATOR:-demucs}"
MODEL_SOURCE="${MODEL_SOURCE:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
R2_CHECKPOINT="${R2_CHECKPOINT:-/root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750}"
STAGE="${STAGE:-all}"

args=(
  "$SOURCE_MEDIA"
  --lyrics "$LYRICS"
  --single-output-dir "$OUT_ROOT"
  --language "$LANGUAGE"
  --separator "$SEPARATOR"
  --model "$MODEL_SOURCE"
  --revision "$MODEL_REVISION"
  --r2-checkpoint "$R2_CHECKPOINT"
  --stage "$STAGE"
  --core-sec "${CORE_SEC:-30}"
  --left-context-sec "${LEFT_CONTEXT_SEC:-10}"
  --right-context-sec "${RIGHT_CONTEXT_SEC:-10}"
)
[[ -n "${KARAOKE_FONT:-}" ]] && args+=(--font "$KARAOKE_FONT")
[[ -n "${SUBTITLE_BAND_HEIGHT:-}" ]] && args+=(--subtitle-band-height "$SUBTITLE_BAND_HEIGHT")
[[ "${FORCE_SEPARATE:-0}" == "1" ]] && args+=(--force-separation)
[[ "${FORCE_ALIGN:-0}" == "1" ]] && args+=(--force-align)
[[ "${FORCE_RENDER:-0}" == "1" ]] && args+=(--force-render)
[[ "${FORCE_ALL:-0}" == "1" ]] && args+=(--force)
exec "$ENTRY" "${args[@]}"
