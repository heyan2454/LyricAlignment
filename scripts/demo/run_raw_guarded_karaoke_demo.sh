#!/usr/bin/env bash
# Full user-facing demo: media extraction -> Spleeter vocals -> R2 raw + guarded
# local realignment -> karaoke videos.  The original mix remains the primary
# rendered audio; the separated vocal is used for alignment and diagnostics.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
DEMO_ROOT="${DEMO_ROOT:-$PROJECT/夜苏打}"
LYRICS="${LYRICS:-$DEMO_ROOT/歌词.txt}"
SOURCE_MEDIA="${SOURCE_MEDIA:-$DEMO_ROOT/夜苏打.mp4}"
OUT_ROOT="${OUT_ROOT:-$DEMO_ROOT/qwen_fa_raw_guarded_demo}"
WORK_ROOT="$OUT_ROOT/work"
AUDIO_ROOT="$WORK_ROOT/audio"
MIX_WAV="$AUDIO_ROOT/mix.wav"
VOCAL_WAV="$AUDIO_ROOT/vocals.wav"
ACCOMP_WAV="$AUDIO_ROOT/accompaniment.wav"
SEPARATION_REPORT="$AUDIO_ROOT/separation_quality.json"
ALIGN_ROOT="$OUT_ROOT/alignments/r2_raw_guarded"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
MODEL_SOURCE="${MODEL_SOURCE:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
R2_CHECKPOINT="${R2_CHECKPOINT:-/root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750}"
SPLEETER_ENV="${SPLEETER_ENV:-spleeter}"
SPLEETER_MODEL_ROOT="${SPLEETER_MODEL_ROOT:-$HOME/.cache/spleeter_models}"
STAGE="${STAGE:-all}" # all | prepare | align | render
FORCE_SEPARATE="${FORCE_SEPARATE:-0}"
FORCE_ALIGN="${FORCE_ALIGN:-0}"
FORCE_RENDER="${FORCE_RENDER:-0}"
CORE_SEC="${CORE_SEC:-30}"
LEFT_CONTEXT_SEC="${LEFT_CONTEXT_SEC:-10}"
RIGHT_CONTEXT_SEC="${RIGHT_CONTEXT_SEC:-10}"
KARAOKE_FONT="${KARAOKE_FONT:-Noto Sans CJK SC}"
SUBTITLE_BAND_HEIGHT="${SUBTITLE_BAND_HEIGHT:-}"

mkdir -p "$OUT_ROOT" "$WORK_ROOT" "$AUDIO_ROOT"
LOG="$OUT_ROOT/pipeline.log"
log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }
fail() { log "ERROR: $*"; exit 1; }
require_file() { [[ -f "$1" ]] || fail "missing file: $1"; }
require_dir() { [[ -d "$1" ]] || fail "missing directory: $1"; }

source_sha256() { sha256sum "$1" | awk '{print $1}'; }

spleeter_run() {
  local tmp="$WORK_ROOT/spleeter_output"
  local sep_log="$OUT_ROOT/spleeter.log"
  rm -rf "$tmp"
  mkdir -p "$tmp" "$SPLEETER_MODEL_ROOT"
  "$PYTHON_BIN" "$PROJECT/scripts/demo/validate_spleeter_model.py" \
    --model-root "$SPLEETER_MODEL_ROOT" --model-name 2stems 2>&1 | tee -a "$sep_log"

  if command -v spleeter >/dev/null 2>&1; then
    MODEL_PATH="$SPLEETER_MODEL_ROOT" spleeter separate -p spleeter:2stems -o "$tmp" "$MIX_WAV" \
      2>&1 | tee -a "$sep_log"
  elif command -v conda >/dev/null 2>&1 && conda env list | awk '{print $1}' | grep -Fxq "$SPLEETER_ENV"; then
    MODEL_PATH="$SPLEETER_MODEL_ROOT" conda run -n "$SPLEETER_ENV" \
      spleeter separate -p spleeter:2stems -o "$tmp" "$MIX_WAV" 2>&1 | tee -a "$sep_log"
  else
    fail "Spleeter not found on PATH and conda env '$SPLEETER_ENV' is unavailable"
  fi

  local generated_vocals generated_accompaniment
  generated_vocals="$(find "$tmp" -type f -name vocals.wav -print -quit)"
  generated_accompaniment="$(find "$tmp" -type f -name accompaniment.wav -print -quit)"
  [[ -n "$generated_vocals" && -n "$generated_accompaniment" ]] || fail "Spleeter outputs missing under $tmp"
  cp -f "$generated_vocals" "$VOCAL_WAV.tmp.wav"
  cp -f "$generated_accompaniment" "$ACCOMP_WAV.tmp.wav"
  "$PYTHON_BIN" "$PROJECT/scripts/demo/check_audio_separation.py" \
    --mix "$MIX_WAV" --vocals "$VOCAL_WAV.tmp.wav" --accompaniment "$ACCOMP_WAV.tmp.wav" \
    --report "$SEPARATION_REPORT.tmp.json"
  mv -f "$VOCAL_WAV.tmp.wav" "$VOCAL_WAV"
  mv -f "$ACCOMP_WAV.tmp.wav" "$ACCOMP_WAV"
  mv -f "$SEPARATION_REPORT.tmp.json" "$SEPARATION_REPORT"
}

prepare_media() {
  require_file "$LYRICS"
  require_file "$SOURCE_MEDIA"
  command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg is required"
  command -v ffprobe >/dev/null 2>&1 || fail "ffprobe is required"
  [[ -x "$PYTHON_BIN" ]] || fail "python environment missing: $PYTHON_BIN"

  local source_sha identity reuse
  source_sha="$(source_sha256 "$SOURCE_MEDIA")"
  identity="$AUDIO_ROOT/prepare.identity.json"
  reuse=0
  if [[ "$FORCE_SEPARATE" != "1" && -f "$MIX_WAV" && -f "$VOCAL_WAV" && -f "$ACCOMP_WAV" && -f "$SEPARATION_REPORT" && -f "$identity" ]]; then
    reuse="$($PYTHON_BIN - "$identity" "$source_sha" "$MIX_WAV" "$VOCAL_WAV" "$ACCOMP_WAV" "$SEPARATION_REPORT" <<'PY'
import hashlib,json,sys
from pathlib import Path
try:
    identity=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    paths=[Path(v) for v in sys.argv[3:7]]
    hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    checks=[
        identity.get('schema_version') == 'raw_guarded_demo_media_v1',
        identity.get('source_media_sha256') == sys.argv[2],
        identity.get('mix_sha256') == hashes[0],
        identity.get('vocals_sha256') == hashes[1],
        identity.get('accompaniment_sha256') == hashes[2],
        identity.get('separation_report_sha256') == hashes[3],
        json.loads(paths[3].read_text(encoding='utf-8')).get('passed') is True,
    ]
    print('1' if all(checks) else '0')
except Exception:
    print('0')
PY
)"
  fi
  if [[ "$reuse" == "1" ]]; then
    log "reuse validated mix and Spleeter stems"
    return
  fi

  log "extract original mix audio from $SOURCE_MEDIA"
  ffmpeg -nostdin -y -v warning -i "$SOURCE_MEDIA" -vn -ac 2 -ar 44100 -c:a pcm_s16le "$MIX_WAV.tmp.wav"
  mv -f "$MIX_WAV.tmp.wav" "$MIX_WAV"
  log "run and validate Spleeter vocal separation"
  spleeter_run
  "$PYTHON_BIN" - "$identity" "$SOURCE_MEDIA" "$source_sha" "$MIX_WAV" "$VOCAL_WAV" "$ACCOMP_WAV" "$SEPARATION_REPORT" "$SPLEETER_MODEL_ROOT" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
out=Path(sys.argv[1]); paths=[Path(v) for v in sys.argv[4:8]]
payload={
  'schema_version':'raw_guarded_demo_media_v1',
  'created_at':datetime.now(timezone.utc).isoformat(),
  'source_media':str(Path(sys.argv[2]).resolve()),
  'source_media_sha256':sys.argv[3],
  'mix_sha256':hashlib.sha256(paths[0].read_bytes()).hexdigest(),
  'vocals_sha256':hashlib.sha256(paths[1].read_bytes()).hexdigest(),
  'accompaniment_sha256':hashlib.sha256(paths[2].read_bytes()).hexdigest(),
  'separation_report_sha256':hashlib.sha256(paths[3].read_bytes()).hexdigest(),
  'spleeter_model_root':str(Path(sys.argv[8]).resolve()),
}
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
PY
  log "media prepared: mix=$MIX_WAV vocals=$VOCAL_WAV"
}

run_alignment() {
  require_file "$LYRICS"
  require_file "$VOCAL_WAV"
  require_dir "$R2_CHECKPOINT"
  local args=(
    --lyrics "$LYRICS" --audio "$VOCAL_WAV" --out-root "$ALIGN_ROOT"
    --model "$MODEL_SOURCE" --revision "$MODEL_REVISION" --r2-checkpoint "$R2_CHECKPOINT"
    --device cuda --language Chinese --timestamp-segment-sec 0.08
    --core-sec "$CORE_SEC" --left-context-sec "$LEFT_CONTEXT_SEC" --right-context-sec "$RIGHT_CONTEXT_SEC"
    --local-files-only
  )
  [[ "$FORCE_ALIGN" == "1" ]] && args+=(--force)
  log "run R2 raw baseline and guarded local realignment"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" "$PROJECT/scripts/demo/align_qwen_fa_raw_guarded_demo.py" "${args[@]}" \
    2>&1 | tee -a "$OUT_ROOT/alignment.log"
}

run_render() {
  require_file "$ALIGN_ROOT/alignment.json"
  require_file "$ALIGN_ROOT/baseline_raw/alignment.json"
  require_file "$MIX_WAV"
  require_file "$VOCAL_WAV"
  local args=(
    --alignment-root "$ALIGN_ROOT" --mix-audio "$MIX_WAV" --vocal-audio "$VOCAL_WAV"
    --out-root "$OUT_ROOT" --font "$KARAOKE_FONT"
  )
  if ffprobe -v error -select_streams v:0 -show_entries stream=index -of csv=p=0 "$SOURCE_MEDIA" | grep -q .; then
    args+=(--visual-source "$SOURCE_MEDIA")
  fi
  [[ -n "$SUBTITLE_BAND_HEIGHT" ]] && args+=(--subtitle-band-height "$SUBTITLE_BAND_HEIGHT")
  [[ "$FORCE_RENDER" == "1" ]] && args+=(--force)
  log "render baseline/final karaoke videos and two-way comparisons"
  PYTHONUNBUFFERED=1 "$PYTHON_BIN" "$PROJECT/scripts/demo/render_raw_guarded_karaoke.py" "${args[@]}" \
    2>&1 | tee -a "$OUT_ROOT/render.log"
}

cd "$PROJECT"
case "$STAGE" in
  all) prepare_media; run_alignment; run_render ;;
  prepare) prepare_media ;;
  align) run_alignment ;;
  render) run_render ;;
  *) fail "invalid STAGE=$STAGE (expected all|prepare|align|render)" ;;
esac
log "raw guarded karaoke demo complete: STAGE=$STAGE OUT_ROOT=$OUT_ROOT"
