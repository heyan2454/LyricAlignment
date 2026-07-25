#!/usr/bin/env bash
# Dedicated 夜苏打 experiment: trim validated vocals after 03:05 and 03:12,
# align each tail with its supplied lyric subset using windowed R0/R1/R2, then render.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
DEMO_ROOT="${DEMO_ROOT:-$PROJECT/夜苏打}"
SOURCE_DEMO_ROOT="${SOURCE_DEMO_ROOT:-$DEMO_ROOT/qwen_fa_demo_serial}"
SOURCE_VOCAL="${SOURCE_VOCAL:-$SOURCE_DEMO_ROOT/work/audio/vocals.wav}"
SOURCE_VOCAL_IDENTITY="${SOURCE_VOCAL_IDENTITY:-$SOURCE_DEMO_ROOT/work/audio/vocals.identity.json}"
SEPARATION_REPORT="${SEPARATION_REPORT:-$SOURCE_DEMO_ROOT/work/audio/separation_quality.json}"
OUT_ROOT="${OUT_ROOT:-$DEMO_ROOT/qwen_fa_tail_windowed_0305_0312}"
CONFIG="$OUT_ROOT/cases.json"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs}"
MODEL_ID="${MODEL_ID:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
R1_RUN="${R1_RUN:-$RUN_ROOT/20260724_qwen_fa_r1_full_seed3407}"
R2_RUN="${R2_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
R1_CHECKPOINT="${R1_CHECKPOINT:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-}"
STAGE="${STAGE:-all}" # all | prepare | align | render
FORCE_PREPARE="${FORCE_PREPARE:-0}"
FORCE_ALIGN="${FORCE_ALIGN:-0}"
FORCE_RENDER="${FORCE_RENDER:-0}"
REQUIRE_VALIDATED_SEPARATION="${REQUIRE_VALIDATED_SEPARATION:-1}"
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

CASE_0305="$OUT_ROOT/cases/after_0305"
CASE_0312="$OUT_ROOT/cases/after_0312"

mkdir -p "$OUT_ROOT" "$CASE_0305/audio" "$CASE_0312/audio"
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

validate_source_vocal() {
  require_file "$SOURCE_VOCAL"
  if [[ "$REQUIRE_VALIDATED_SEPARATION" != "1" ]]; then
    log "WARNING: separation validation bypassed by REQUIRE_VALIDATED_SEPARATION=$REQUIRE_VALIDATED_SEPARATION"
    return
  fi
  require_file "$SOURCE_VOCAL_IDENTITY"
  require_file "$SEPARATION_REPORT"
  "$PYTHON_BIN" - "$SOURCE_VOCAL" "$SOURCE_VOCAL_IDENTITY" "$SEPARATION_REPORT" <<'PY'
import hashlib,json,sys
from pathlib import Path
vocal=Path(sys.argv[1]); identity_path=Path(sys.argv[2]); report_path=Path(sys.argv[3])
identity=json.loads(identity_path.read_text(encoding='utf-8'))
report=json.loads(report_path.read_text(encoding='utf-8'))
actual=hashlib.sha256(vocal.read_bytes()).hexdigest()
checks={
    'identity_schema_v2': identity.get('schema_version') == 'yessoda_spleeter_v2',
    'quality_passed': report.get('passed') is True,
    'vocal_hash_matches_identity': identity.get('vocals_sha256') == actual,
}
print(json.dumps(checks,ensure_ascii=False,sort_keys=True))
if not all(checks.values()):
    raise SystemExit('source vocal is not a validated Spleeter v2 output')
PY
}

write_inputs() {
  cat > "$CASE_0305/lyrics.txt" <<'EOF'
想要毫无心事地睡去
即便明日将得过且过毫无期许
四处游弋的呼救词句
只是溶解在苏打再用夜色消磨千思万绪

稀疏泡沫飘散于夜色
摇晃瓶身话语也失真
趔趄地 徘徊着 短暂从时刻表抽身 如此选择

灌下苏打熟悉的苦涩
早已售罄的美梦
白昼靠近了 街灯褪色 与我远隔
EOF

  cat > "$CASE_0312/lyrics.txt" <<'EOF'
即便明日将得过且过毫无期许
四处游弋的呼救词句
只是溶解在苏打再用夜色消磨千思万绪

稀疏泡沫飘散于夜色
摇晃瓶身话语也失真
趔趄地 徘徊着 短暂从时刻表抽身 如此选择

灌下苏打熟悉的苦涩
早已售罄的美梦
白昼靠近了 街灯褪色 与我远隔
EOF
}

trim_tail() {
  local start_sec="$1" case_root="$2"
  local output="$case_root/audio/vocals_tail.wav"
  local identity="$case_root/audio/vocals_tail.identity.json"
  local source_sha current
  source_sha="$(sha256sum "$SOURCE_VOCAL" | awk '{print $1}')"
  current="0"
  if [[ "$FORCE_PREPARE" != "1" && -f "$output" && -f "$identity" ]]; then
    current="$($PYTHON_BIN - "$identity" "$output" "$source_sha" "$start_sec" <<'PY'
import hashlib,json,sys
from pathlib import Path
identity=Path(sys.argv[1]); output=Path(sys.argv[2])
try:
    data=json.loads(identity.read_text(encoding='utf-8'))
    checks=[
        data.get('schema_version') == 'yessoda_vocal_tail_v1',
        data.get('source_vocals_sha256') == sys.argv[3],
        abs(float(data.get('source_start_sec')) - float(sys.argv[4])) < 1e-9,
        data.get('output_sha256') == hashlib.sha256(output.read_bytes()).hexdigest(),
    ]
    print('1' if all(checks) else '0')
except Exception:
    print('0')
PY
)"
  fi
  if [[ "$current" == "1" ]]; then
    log "reuse vocal tail start=${start_sec}s: $output"
    return
  fi
  log "trim validated vocals from ${start_sec}s to EOF: $output"
  ffmpeg -nostdin -y -v warning \
    -i "$SOURCE_VOCAL" -ss "$start_sec" -map 0:a:0 \
    -ac 2 -ar 44100 -c:a pcm_s16le "$output.tmp.wav"
  mv -f "$output.tmp.wav" "$output"
  "$PYTHON_BIN" - "$identity" "$SOURCE_VOCAL" "$source_sha" "$start_sec" "$output" <<'PY'
import hashlib,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
identity=Path(sys.argv[1]); source=Path(sys.argv[2]); output=Path(sys.argv[5])
probe=subprocess.run([
    'ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(output)
],check=True,text=True,capture_output=True)
duration=float(probe.stdout.strip())
if duration <= 0:
    raise SystemExit(f'trimmed tail is empty: {output}')
payload={
    'schema_version':'yessoda_vocal_tail_v1',
    'created_at':datetime.now(timezone.utc).isoformat(),
    'source_vocals':str(source.resolve()),
    'source_vocals_sha256':sys.argv[3],
    'source_start_sec':float(sys.argv[4]),
    'duration_sec':duration,
    'output':str(output.resolve()),
    'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
    'audio_format':{'sample_rate_hz':44100,'channels':2,'codec':'pcm_s16le'},
}
identity.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
PY
}

write_config() {
  "$PYTHON_BIN" - "$CONFIG" "$CASE_0305" "$CASE_0312" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
config=Path(sys.argv[1]); c305=Path(sys.argv[2]); c312=Path(sys.argv[3])
payload={
    'schema_version':'yessoda_tail_windowed_cases_v1',
    'created_at':datetime.now(timezone.utc).isoformat(),
    'cases':[
        {
            'case_id':'after_0305',
            'display_label':'03:05 后',
            'source_start_sec':185.0,
            'lyrics_path':str((c305/'lyrics.txt').resolve()),
            'audio_path':str((c305/'audio'/'vocals_tail.wav').resolve()),
            'case_root':str(c305.resolve()),
        },
        {
            'case_id':'after_0312',
            'display_label':'03:12 后',
            'source_start_sec':192.0,
            'lyrics_path':str((c312/'lyrics.txt').resolve()),
            'audio_path':str((c312/'audio'/'vocals_tail.wav').resolve()),
            'case_root':str(c312.resolve()),
        },
    ],
}
config.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
PY
}

prepare_cases() {
  command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg is required"
  command -v ffprobe >/dev/null 2>&1 || fail "ffprobe is required"
  [[ -x "$PYTHON_BIN" ]] || fail "python environment missing: $PYTHON_BIN"
  validate_source_vocal
  write_inputs
  trim_tail 185 "$CASE_0305"
  trim_tail 192 "$CASE_0312"
  write_config
  log "prepared two vocal-tail cases: $CONFIG"
}

run_alignment() {
  require_file "$CONFIG"
  require_file "$PROJECT/scripts/demo/align_qwen_fa_tail_windowed.py"
  [[ -x "$PYTHON_BIN" ]] || fail "python environment missing: $PYTHON_BIN"
  [[ -n "$R1_CHECKPOINT" ]] || R1_CHECKPOINT="$(best_checkpoint_strict "$R1_RUN")"
  [[ -n "$R2_CHECKPOINT" ]] || R2_CHECKPOINT="$(best_checkpoint_strict "$R2_RUN")"
  require_dir "$R1_CHECKPOINT"
  require_dir "$R2_CHECKPOINT"
  local args=(
    --config "$CONFIG"
    --model "$MODEL_ID"
    --revision "$MODEL_REVISION"
    --r1-checkpoint "$R1_CHECKPOINT"
    --r2-checkpoint "$R2_CHECKPOINT"
    --device cuda --language Chinese --timestamp-segment-sec 0.08
    --core-sec "$CORE_SEC"
    --left-context-sec "$LEFT_CONTEXT_SEC"
    --right-context-sec "$RIGHT_CONTEXT_SEC"
    --future-line-padding "$FUTURE_LINE_PADDING"
    --minimum-forward-characters "$MINIMUM_FORWARD_CHARACTERS"
    --future-character-ratio "$FUTURE_CHARACTER_RATIO"
    --max-candidate-expansions "$MAX_CANDIDATE_EXPANSIONS"
    --boundary-start-tolerance-sec "$BOUNDARY_START_TOLERANCE_SEC"
    --seam-tolerance-sec "$SEAM_TOLERANCE_SEC"
    --local-files-only
  )
  [[ "$FORCE_ALIGN" == "1" ]] && args+=(--force)
  log "align two vocal tails, windowed only, loading models serially R0 -> R1 -> R2"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" "$PROJECT/scripts/demo/align_qwen_fa_tail_windowed.py" "${args[@]}" \
    2>&1 | tee -a "$OUT_ROOT/alignment.log"
}

run_render() {
  require_file "$CONFIG"
  require_file "$PROJECT/scripts/demo/render_qwen_fa_tail_windowed.py"
  local args=(--config "$CONFIG" --font "$KARAOKE_FONT")
  [[ "$FORCE_RENDER" == "1" ]] && args+=(--force)
  log "render 6 individual videos and 2 R0/R1/R2 comparison videos"
  "$PYTHON_BIN" "$PROJECT/scripts/demo/render_qwen_fa_tail_windowed.py" "${args[@]}" \
    2>&1 | tee -a "$OUT_ROOT/render.log"
}

cd "$PROJECT"
case "$STAGE" in
  all)
    prepare_cases
    run_alignment
    run_render
    ;;
  prepare) prepare_cases ;;
  align) run_alignment ;;
  render) run_render ;;
  *) fail "invalid STAGE=$STAGE (expected all|prepare|align|render)" ;;
esac
log "tail-windowed demo stage complete: STAGE=$STAGE OUT_ROOT=$OUT_ROOT"
