#!/usr/bin/env bash
# Standalone 夜苏打 demo: Spleeter -> serial R0/R1/R2 inference -> KTV videos.
# Models are loaded strictly one at a time by align_qwen_fa_serial_demo.py.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
DEMO_ROOT="${DEMO_ROOT:-$PROJECT/夜苏打}"
LYRICS="${LYRICS:-$DEMO_ROOT/歌词.txt}"
SOURCE_MP4="${SOURCE_MP4:-$DEMO_ROOT/夜苏打.mp4}"
OUT_ROOT="${OUT_ROOT:-$DEMO_ROOT/qwen_fa_demo_serial}"
WORK_ROOT="$OUT_ROOT/work"
AUDIO_ROOT="$WORK_ROOT/audio"
MIX_WAV="$AUDIO_ROOT/mix.wav"
VOCAL_WAV="$AUDIO_ROOT/vocals.wav"
ACCOMP_WAV="$AUDIO_ROOT/accompaniment.wav"
SEPARATION_REPORT="$AUDIO_ROOT/separation_quality.json"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs}"
MODEL_ID="${MODEL_ID:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
R1_RUN="${R1_RUN:-$RUN_ROOT/20260724_qwen_fa_r1_full_seed3407}"
R2_RUN="${R2_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
R1_CHECKPOINT="${R1_CHECKPOINT:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-}"
SPLEETER_ENV="${SPLEETER_ENV:-spleeter}"
SPLEETER_MODEL_ROOT="${SPLEETER_MODEL_ROOT:-$HOME/.cache/spleeter_models}"
FORCE_SEPARATE="${FORCE_SEPARATE:-0}"
FORCE_SPLEETER_MODEL_REDOWNLOAD="${FORCE_SPLEETER_MODEL_REDOWNLOAD:-0}"
STAGE="${STAGE:-all}" # all | prepare | align | render
FORCE_ALIGN="${FORCE_ALIGN:-0}"
FORCE_RENDER="${FORCE_RENDER:-0}"
CORE_SEC="${CORE_SEC:-60}"
LEFT_CONTEXT_SEC="${LEFT_CONTEXT_SEC:-10}"
RIGHT_CONTEXT_SEC="${RIGHT_CONTEXT_SEC:-10}"
FUTURE_LINE_PADDING="${FUTURE_LINE_PADDING:-1}"
MINIMUM_FORWARD_CHARACTERS="${MINIMUM_FORWARD_CHARACTERS:-64}"
FUTURE_CHARACTER_RATIO="${FUTURE_CHARACTER_RATIO:-1.35}"
MAX_CANDIDATE_EXPANSIONS="${MAX_CANDIDATE_EXPANSIONS:-4}"
BOUNDARY_START_TOLERANCE_SEC="${BOUNDARY_START_TOLERANCE_SEC:-0.32}"
SEAM_TOLERANCE_SEC="${SEAM_TOLERANCE_SEC:-0.16}"
KARAOKE_FONT="${KARAOKE_FONT:-Noto Sans CJK SC}"

mkdir -p "$OUT_ROOT" "$WORK_ROOT" "$AUDIO_ROOT"
LOG="$OUT_ROOT/pipeline.log"
log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }
fail() { log "ERROR: $*"; exit 1; }
require_file() { [[ -f "$1" ]] || fail "missing file: $1"; }
require_dir() { [[ -d "$1" ]] || fail "missing directory: $1"; }

best_checkpoint_strict() {
  "$PYTHON_BIN" - "$1" <<'PY'
import json,sys
from pathlib import Path
run=Path(sys.argv[1]); best=run/'best_checkpoint.json'
if not best.is_file():
    raise SystemExit(f'missing validation-selected best_checkpoint.json: {best}')
data=json.loads(best.read_text(encoding='utf-8'))
for key in ('checkpoint','checkpoint_path','best_checkpoint'):
    value=data.get(key)
    if value:
        path=Path(value)
        if not path.is_absolute():
            path=(run/path).resolve()
        if not path.is_dir():
            raise SystemExit(f'best checkpoint path is not a directory: {path}')
        print(path)
        raise SystemExit
raise SystemExit(f'best_checkpoint.json has no checkpoint path: {best}')
PY
}

spleeter_run() {
  local input="$1" vocal_output="$2" accompaniment_output="$3"
  local tmp="$WORK_ROOT/spleeter_output"
  local spleeter_log="$OUT_ROOT/spleeter.log"
  rm -rf "$tmp"
  mkdir -p "$tmp" "$SPLEETER_MODEL_ROOT"

  if [[ "$FORCE_SPLEETER_MODEL_REDOWNLOAD" == "1" ]]; then
    log "remove cached Spleeter 2stems model before redownload: $SPLEETER_MODEL_ROOT/2stems"
    rm -rf "$SPLEETER_MODEL_ROOT/2stems"
  fi

  log "Spleeter MODEL_PATH=$SPLEETER_MODEL_ROOT"
  if command -v spleeter >/dev/null 2>&1; then
    MODEL_PATH="$SPLEETER_MODEL_ROOT" \
      spleeter separate -p spleeter:2stems -o "$tmp" "$input" \
      2>&1 | tee "$spleeter_log"
  elif command -v conda >/dev/null 2>&1 && conda env list | awk '{print $1}' | grep -Fxq "$SPLEETER_ENV"; then
    MODEL_PATH="$SPLEETER_MODEL_ROOT" \
      conda run -n "$SPLEETER_ENV" spleeter separate -p spleeter:2stems -o "$tmp" "$input" \
      2>&1 | tee "$spleeter_log"
  else
    fail "Spleeter not found. Install a separate conda env named '$SPLEETER_ENV' or put spleeter on PATH."
  fi

  [[ -f "$SPLEETER_MODEL_ROOT/2stems/.probe" ]] || \
    fail "Spleeter model cache has no completion probe: $SPLEETER_MODEL_ROOT/2stems/.probe"

  local generated_vocals generated_accompaniment
  generated_vocals="$(find "$tmp" -type f -name vocals.wav -print -quit)"
  generated_accompaniment="$(find "$tmp" -type f -name accompaniment.wav -print -quit)"
  [[ -n "$generated_vocals" ]] || fail "Spleeter did not produce vocals.wav under $tmp"
  [[ -n "$generated_accompaniment" ]] || fail "Spleeter did not produce accompaniment.wav under $tmp"

  cp -f "$generated_vocals" "$vocal_output.tmp.wav"
  cp -f "$generated_accompaniment" "$accompaniment_output.tmp.wav"
  if ! "$PYTHON_BIN" "$PROJECT/scripts/demo/check_audio_separation.py" \
      --mix "$input" \
      --vocals "$vocal_output.tmp.wav" \
      --accompaniment "$accompaniment_output.tmp.wav" \
      --report "$SEPARATION_REPORT.tmp.json"; then
    rm -f "$vocal_output.tmp.wav" "$accompaniment_output.tmp.wav"
    fail "Spleeter output failed quality validation. Inspect $spleeter_log and $SEPARATION_REPORT.tmp.json"
  fi
  mv -f "$vocal_output.tmp.wav" "$vocal_output"
  mv -f "$accompaniment_output.tmp.wav" "$accompaniment_output"
  mv -f "$SEPARATION_REPORT.tmp.json" "$SEPARATION_REPORT"
}

prepare_audio() {
  require_file "$LYRICS"
  require_file "$SOURCE_MP4"
  command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg is required"
  log "extract original mix audio"
  ffmpeg -nostdin -y -v warning -i "$SOURCE_MP4" -vn -ac 2 -ar 44100 -c:a pcm_s16le "$MIX_WAV.tmp.wav"
  mv -f "$MIX_WAV.tmp.wav" "$MIX_WAV"

  local source_sha reuse_ok
  source_sha="$(sha256sum "$MIX_WAV" | awk '{print $1}')"
  reuse_ok="0"
  if [[ "$FORCE_SEPARATE" != "1" ]]; then
    reuse_ok="$($PYTHON_BIN - \
      "$AUDIO_ROOT/vocals.identity.json" \
      "$source_sha" \
      "$VOCAL_WAV" \
      "$ACCOMP_WAV" \
      "$SEPARATION_REPORT" \
      "$SPLEETER_MODEL_ROOT" <<'PY'
import hashlib,json,sys
from pathlib import Path
identity_path=Path(sys.argv[1])
expected_mix_sha=sys.argv[2]
vocal=Path(sys.argv[3])
accompaniment=Path(sys.argv[4])
quality_path=Path(sys.argv[5])
model_root=Path(sys.argv[6]).resolve()
try:
    identity=json.loads(identity_path.read_text(encoding='utf-8'))
    quality=json.loads(quality_path.read_text(encoding='utf-8'))
    checks=[
        identity.get('schema_version') == 'yessoda_spleeter_v2',
        identity.get('mix_sha256') == expected_mix_sha,
        identity.get('model_root') == str(model_root),
        quality.get('passed') is True,
        identity.get('vocals_sha256') == hashlib.sha256(vocal.read_bytes()).hexdigest(),
        identity.get('accompaniment_sha256') == hashlib.sha256(accompaniment.read_bytes()).hexdigest(),
        identity.get('quality_report_sha256') == hashlib.sha256(quality_path.read_bytes()).hexdigest(),
    ]
    print('1' if all(checks) else '0')
except Exception:
    print('0')
PY
)"
  fi
  if [[ "$reuse_ok" == "1" ]]; then
    log "reuse validated Spleeter stems"
  else
    log "run Spleeter 2-stem separation"
    spleeter_run "$MIX_WAV" "$VOCAL_WAV" "$ACCOMP_WAV"
    "$PYTHON_BIN" - \
      "$AUDIO_ROOT/vocals.identity.json" \
      "$source_sha" \
      "$VOCAL_WAV" \
      "$ACCOMP_WAV" \
      "$SEPARATION_REPORT" \
      "$SPLEETER_MODEL_ROOT" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
out=Path(sys.argv[1])
vocal=Path(sys.argv[3])
accompaniment=Path(sys.argv[4])
quality_report=Path(sys.argv[5])
model_root=Path(sys.argv[6])
out.write_text(json.dumps({
  'schema_version':'yessoda_spleeter_v2',
  'created_at':datetime.now(timezone.utc).isoformat(),
  'mix_sha256':sys.argv[2],
  'vocals_sha256':hashlib.sha256(vocal.read_bytes()).hexdigest(),
  'accompaniment_sha256':hashlib.sha256(accompaniment.read_bytes()).hexdigest(),
  'quality_report':str(quality_report.resolve()),
  'quality_report_sha256':hashlib.sha256(quality_report.read_bytes()).hexdigest(),
  'model_root':str(model_root.resolve()),
  'separator':'spleeter:2stems'
},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
PY
  fi
  log "audio prepared: $MIX_WAV ; $VOCAL_WAV ; $ACCOMP_WAV"
}

run_alignment() {
  require_file "$LYRICS"
  require_file "$MIX_WAV"
  require_file "$VOCAL_WAV"
  require_file "$PROJECT/scripts/demo/align_qwen_fa_serial_demo.py"
  [[ -x "$PYTHON_BIN" ]] || fail "python environment missing: $PYTHON_BIN"
  [[ -n "$R1_CHECKPOINT" ]] || R1_CHECKPOINT="$(best_checkpoint_strict "$R1_RUN")"
  [[ -n "$R2_CHECKPOINT" ]] || R2_CHECKPOINT="$(best_checkpoint_strict "$R2_RUN")"
  require_dir "$R1_CHECKPOINT"
  require_dir "$R2_CHECKPOINT"
  local args=(
    --lyrics "$LYRICS"
    --mix-audio "$MIX_WAV"
    --vocal-audio "$VOCAL_WAV"
    --out-root "$OUT_ROOT"
    --model "$MODEL_ID"
    --revision "$MODEL_REVISION"
    --r1-checkpoint "$R1_CHECKPOINT"
    --r2-checkpoint "$R2_CHECKPOINT"
    --device cuda --language Chinese --timestamp-segment-sec 0.08
    --core-sec "$CORE_SEC" --left-context-sec "$LEFT_CONTEXT_SEC" --right-context-sec "$RIGHT_CONTEXT_SEC"
    --future-line-padding "$FUTURE_LINE_PADDING"
    --minimum-forward-characters "$MINIMUM_FORWARD_CHARACTERS"
    --future-character-ratio "$FUTURE_CHARACTER_RATIO"
    --max-candidate-expansions "$MAX_CANDIDATE_EXPANSIONS"
    --boundary-start-tolerance-sec "$BOUNDARY_START_TOLERANCE_SEC"
    --seam-tolerance-sec "$SEAM_TOLERANCE_SEC"
    --local-files-only
  )
  [[ "$FORCE_ALIGN" == "1" ]] && args+=(--force)
  log "run 12 alignments serially: R0 -> R1 -> R2"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" "$PROJECT/scripts/demo/align_qwen_fa_serial_demo.py" "${args[@]}" \
    2>&1 | tee -a "$OUT_ROOT/alignment.log"
}

run_render() {
  require_file "$PROJECT/scripts/demo/render_qwen_fa_karaoke.py"
  require_file "$MIX_WAV"
  require_file "$VOCAL_WAV"
  local args=(
    --out-root "$OUT_ROOT"
    --mix-audio "$MIX_WAV"
    --vocal-audio "$VOCAL_WAV"
    --font "$KARAOKE_FONT"
  )
  [[ "$FORCE_RENDER" == "1" ]] && args+=(--force)
  log "render 12 individual + 4 three-way + 3 four-way videos"
  "$PYTHON_BIN" "$PROJECT/scripts/demo/render_qwen_fa_karaoke.py" "${args[@]}" \
    2>&1 | tee -a "$OUT_ROOT/render.log"
}

cd "$PROJECT"
case "$STAGE" in
  all)
    prepare_audio
    run_alignment
    run_render
    ;;
  prepare) prepare_audio ;;
  align) run_alignment ;;
  render) run_render ;;
  *) fail "invalid STAGE=$STAGE (expected all|prepare|align|render)" ;;
esac
log "demo stage complete: STAGE=$STAGE OUT_ROOT=$OUT_ROOT"
