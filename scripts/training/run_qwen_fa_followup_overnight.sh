#!/usr/bin/env bash
# Resumable overnight follow-up for Qwen Forced Aligner LoRA.
#
# Scope:
#   1) R0 raw on frozen M4Singer test and MIR-1K OOD;
#   2) matched-budget full R1 projector-only training + test/OOD;
#   3) test-only synthetic-long construction/evaluation (20/30/60/180 s buckets);
#   4) paired seed-2 R1/R2 pilots and a validation-only decision gate;
#   5) optional full seed-2 R2 when AUTO_RUN_FULL_SEED2=1 and the gate passes.
#
# Re-running this command resumes incomplete training from the latest checkpoint
# and skips outputs that pass artifact validation. Partial directories are kept.
set -Eeuo pipefail

MODE="${1:-run}"
PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
DATA_ROOT="${DATA_ROOT:-/home/hyan/Data/lyricalign}"
RUN_ROOT="${RUN_ROOT:-$DATA_ROOT/runs}"
DERIVED_ROOT="${DERIVED_ROOT:-$DATA_ROOT/derived}"
HF_HUB_CACHE="${HF_HUB_CACHE:-$DATA_ROOT/models/hf_cache}"
PYTHON_BIN="${PYTHON_BIN:-python}"
AUTO_RUN_FULL_SEED2="${AUTO_RUN_FULL_SEED2:-0}"
SECOND_SEED="${SECOND_SEED:-20260724}"

STATE_ROOT="${STATE_ROOT:-$RUN_ROOT/20260724_qwen_fa_followup_overnight}"
EVENTS="$STATE_ROOT/pipeline_events.jsonl"
SUMMARY="$STATE_ROOT/final_summary.json"
LOCK="$STATE_ROOT/pipeline.lock"

MODEL_ID="Qwen/Qwen3-ForcedAligner-0.6B-hf"
MODEL_REVISION="c07281df297b9905d24a508279258cccf987a064"
M4_LABELS="$DERIVED_ROOT/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"
M4_SPLIT="$DERIVED_ROOT/20260723_qwen_fa_lora_v1/split/m4singer_accepted_split_manifest.jsonl"
M4_CHARACTERS="$DERIVED_ROOT/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_character_annotations.jsonl"
M4_AUDIO_ROOT="/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer"
MIR_ROOT="$DERIVED_ROOT/20260722_mir1k_vocal_channel1_ood"
MIR_MANIFEST="$MIR_ROOT/mir1k_vocal_ood_manifest.jsonl"
MIR_CHARACTERS="$MIR_ROOT/mir1k_vocal_ood_characters.jsonl"
MIR_LABEL_DIR="$DERIVED_ROOT/20260724_mir1k_qwen_fa_labels_v1"
MIR_LABELS="$MIR_LABEL_DIR/mir1k_qwen_fa_labels.jsonl"

FULL_R2_RUN="$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407"
FULL_R2_TEST="$RUN_ROOT/20260723_qwen_fa_r2_full_m4singer_sealed_test"
FULL_R2_OOD="$RUN_ROOT/20260723_qwen_fa_r2_full_mir1k_ood"
FULL_R1_RUN="$RUN_ROOT/20260724_qwen_fa_r1_full_seed3407"
R0_TEST="$RUN_ROOT/20260724_qwen_fa_r0_raw_m4singer_test"
R0_OOD="$RUN_ROOT/20260724_qwen_fa_r0_raw_mir1k_ood"
R1_TEST="$RUN_ROOT/20260724_qwen_fa_r1_full_m4singer_test"
R1_OOD="$RUN_ROOT/20260724_qwen_fa_r1_full_mir1k_ood"
SEED2_R1_PILOT="$RUN_ROOT/20260724_qwen_fa_r1_pilot_seed${SECOND_SEED}"
SEED2_R2_PILOT="$RUN_ROOT/20260724_qwen_fa_r2_pilot_seed${SECOND_SEED}"
SEED2_DECISION="$STATE_ROOT/seed2_decision.json"
SEED2_FULL_R2="$RUN_ROOT/20260724_qwen_fa_r2_full_seed${SECOND_SEED}"

CFG_R1="$PROJECT/configs/training/qwen_fa_lora_full_r1_v1.yaml"
CFG_SEED2_PILOT="$PROJECT/configs/training/qwen_fa_lora_seed2_pilot_v1.yaml"
CFG_SEED2_FULL="$PROJECT/configs/training/qwen_fa_lora_full_r2_seed2_v1.yaml"
CFG_SMOKE="$PROJECT/configs/training/qwen_fa_followup_smoke_v1.yaml"

export HF_HUB_CACHE HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$STATE_ROOT"

fail() { echo "ERROR: $*" >&2; exit 1; }
require_file() { [ -f "$1" ] || fail "required file missing: $1"; }
require_dir() { [ -d "$1" ] || fail "required directory missing: $1"; }

emit() {
  local stage="$1" status="$2" message="${3:-}"
  echo "[$(date -Is)] [$stage] $status ${message}"
  "$PYTHON_BIN" - "$EVENTS" "$stage" "$status" "$message" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path, stage, status, message = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "stage": stage, "status": status, "message": message}, ensure_ascii=False) + "\n")
PY
}

archive_incomplete() {
  local path="$1"
  [ -e "$path" ] || return 0
  local moved="${path}.incomplete.$(date +%Y%m%d_%H%M%S).$$"
  mv "$path" "$moved"
  emit "archive" "retained" "$moved"
}

eval_complete() {
  local path="$1"
  [ -f "$path/metrics.json" ] && [ -f "$path/predictions.jsonl" ] && [ -f "$path/evaluation_identity.json" ] && [ -f "$path/return_code.txt" ] && [ "$(cat "$path/return_code.txt")" = "0" ]
}

training_complete() {
  local path="$1" expected="$2"
  "$PYTHON_BIN" - "$path" "$expected" <<'PY' >/dev/null 2>&1
import json, sys
from pathlib import Path
run, expected = Path(sys.argv[1]), int(sys.argv[2])
summary = json.loads((run / "runtime_summary.json").read_text(encoding="utf-8"))
assert summary.get("completed") is True
assert int(summary["steps"]) == expected
assert (run / "evaluation.json").is_file()
best = json.loads((run / "best_checkpoint.json").read_text(encoding="utf-8"))
ckpt = Path(best["checkpoint"])
assert ckpt.is_dir() and (ckpt / "projector.pt").is_file() and (ckpt / "trainer_state.pt").is_file()
PY
}

latest_checkpoint() {
  local run="$1"
  find "$run/checkpoints" -mindepth 1 -maxdepth 1 -type d -name 'step-*' 2>/dev/null | sort -V | tail -1
}

best_checkpoint() {
  "$PYTHON_BIN" - "$1/best_checkpoint.json" <<'PY'
import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["checkpoint"])
PY
}

run_eval_atomic() {
  local stage="$1" out="$2"; shift 2
  if eval_complete "$out"; then
    emit "$stage" "skip" "validated output exists: $out"
    return 0
  fi
  [ ! -e "$out" ] || archive_incomplete "$out"
  local tmp="${out}.tmp.$(date +%Y%m%d_%H%M%S).$$"
  mkdir -p "$tmp"
  emit "$stage" "start" "$tmp"
  cat > "$tmp/command.sh" <<EOF
cd "$PROJECT"
$PYTHON_BIN scripts/training/evaluate_qwen_fa_checkpoint.py --out-dir "$tmp" $*
EOF
  set +e
  (
    cd "$PROJECT"
    "$PYTHON_BIN" scripts/training/evaluate_qwen_fa_checkpoint.py --out-dir "$tmp" "$@"
  ) > >(tee "$tmp/stdout.log") 2> >(tee "$tmp/stderr.log" >&2)
  local rc=$?
  set -e
  echo "$rc" > "$tmp/return_code.txt"
  if [ "$rc" -ne 0 ]; then
    emit "$stage" "failed" "partial evidence: $tmp"
    return "$rc"
  fi
  eval_complete "$tmp" || fail "$stage returned success but artifacts are incomplete: $tmp"
  mv "$tmp" "$out"
  emit "$stage" "complete" "$out"
}

run_training_resumable() {
  local stage_name="$1" config="$2" run_dir="$3" model_stage="$4" expected_steps="$5"
  if training_complete "$run_dir" "$expected_steps"; then
    emit "$stage_name" "skip" "validated training output exists: $run_dir"
    return 0
  fi
  local args=(--config "$config" --run-dir "$run_dir" --stage "$model_stage" --device cuda --local-files-only)
  if [ -d "$run_dir" ]; then
    local ckpt
    ckpt="$(latest_checkpoint "$run_dir")"
    if [ -n "$ckpt" ]; then
      args+=(--resume "$ckpt")
      emit "$stage_name" "resume" "$ckpt"
    else
      archive_incomplete "$run_dir"
      emit "$stage_name" "restart" "no checkpoint was available"
    fi
  else
    emit "$stage_name" "start" "$run_dir"
  fi
  local log="$STATE_ROOT/${stage_name}.log"
  set +e
  (cd "$PROJECT" && "$PYTHON_BIN" scripts/training/run_qwen_fa_lora.py "${args[@]}") > >(tee -a "$log") 2> >(tee -a "$log" >&2)
  local rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    emit "$stage_name" "failed" "rc=$rc; rerun the same pipeline to resume"
    return "$rc"
  fi
  training_complete "$run_dir" "$expected_steps" || fail "$stage_name did not reach expected completion"
  emit "$stage_name" "complete" "$run_dir"
}

ensure_mir_labels() {
  if [ -f "$MIR_LABELS" ]; then
    "$PYTHON_BIN" - "$MIR_LABELS" <<'PY'
import json, sys
from pathlib import Path
rows=[json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line]
assert rows and all("timestamp_class_ids" in row for row in rows)
PY
    return 0
  fi
  [ ! -e "$MIR_LABEL_DIR" ] || archive_incomplete "$MIR_LABEL_DIR"
  local tmp="${MIR_LABEL_DIR}.tmp.$(date +%Y%m%d_%H%M%S).$$"
  mkdir -p "$tmp"
  "$PYTHON_BIN" "$PROJECT/scripts/training/prepare_qwen_fa_labels.py" \
    --split-manifest "$MIR_MANIFEST" --characters "$MIR_CHARACTERS" --out-dir "$tmp" \
    --output-name mir1k_qwen_fa_labels.jsonl --timestamp-segment-sec 0.08 --num-labels 5000
  mv "$tmp" "$MIR_LABEL_DIR"
}

smoke_training_resume() {
  local run="$RUN_ROOT/20260724_qwen_fa_followup_smoke_r1"
  if training_complete "$run" 2; then
    emit "smoke_r1_resume" "skip" "$run"
    return
  fi
  if [ ! -d "$run" ]; then
    emit "smoke_r1_resume" "planned_stop" "run to step 1"
    (cd "$PROJECT" && "$PYTHON_BIN" scripts/training/run_qwen_fa_lora.py \
      --config "$CFG_SMOKE" --run-dir "$run" --stage r1 --device cuda --local-files-only --stop-after-step 1)
  fi
  run_training_resumable "smoke_r1_resume" "$CFG_SMOKE" "$run" r1 2
}

run_smoke() {
  emit "smoke" "start" "static, model, raw, resume, LoRA and long-concat paths"
  for path in "$M4_LABELS" "$M4_SPLIT" "$M4_CHARACTERS" "$MIR_MANIFEST" "$MIR_CHARACTERS" \
    "$CFG_R1" "$CFG_SEED2_PILOT" "$CFG_SEED2_FULL" "$CFG_SMOKE"; do require_file "$path"; done
  require_dir "$M4_AUDIO_ROOT"; require_dir "$MIR_ROOT/vocal_wavs"; require_dir "$FULL_R2_RUN"
  command -v ffmpeg >/dev/null || fail "ffmpeg missing"
  command -v nvidia-smi >/dev/null || fail "nvidia-smi missing"
  nvidia-smi >/dev/null
  "$PYTHON_BIN" - <<'PY'
import peft, torch, transformers, yaml
assert torch.cuda.is_available(), "CUDA unavailable"
print({"torch": torch.__version__, "transformers": transformers.__version__, "gpu": torch.cuda.get_device_name(0)})
PY
  (cd "$PROJECT" && "$PYTHON_BIN" -m compileall -q src scripts tests)
  (cd "$PROJECT" && "$PYTHON_BIN" -m pytest -q tests/test_synthetic.py tests/test_qwen_fa_followup_entrypoint.py)
  ensure_mir_labels
  "$PYTHON_BIN" - "$MODEL_ID" "$MODEL_REVISION" <<'PY'
import sys
from transformers import AutoConfig, AutoProcessor
model, revision = sys.argv[1:]
p = AutoProcessor.from_pretrained(model, revision=revision, local_files_only=True)
c = AutoConfig.from_pretrained(model, revision=revision, local_files_only=True)
segment_ms = float(p.timestamp_segment_time)
segment_sec = segment_ms / 1000.0
assert abs(segment_sec - 0.08) < 1e-12, {
    "timestamp_segment_time_ms": segment_ms,
    "timestamp_segment_sec": segment_sec,
}
assert int(c.num_labels) == 5000, {
    "num_labels": int(c.num_labels),
}
print({
    "processor/config offline smoke passed": True,
    "timestamp_segment_time_ms": segment_ms,
    "timestamp_segment_sec": segment_sec,
    "num_labels": int(c.num_labels),
})
PY
  run_eval_atomic "smoke_raw_m4" "$RUN_ROOT/20260724_qwen_fa_followup_smoke_raw_m4" \
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --checkpoint-kind raw \
    --labels "$M4_LABELS" --characters "$M4_CHARACTERS" --audio-root "$M4_AUDIO_ROOT" \
    --split test --max-items 1 --batch-size 1 --device cuda --local-files-only --evaluation-role smoke_raw_m4
  run_eval_atomic "smoke_raw_mir" "$RUN_ROOT/20260724_qwen_fa_followup_smoke_raw_mir" \
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --checkpoint-kind raw \
    --labels "$MIR_LABELS" --characters "$MIR_CHARACTERS" --audio-root "$MIR_ROOT" \
    --split test --max-items 1 --batch-size 1 --device cuda --local-files-only --evaluation-role smoke_raw_mir
  smoke_training_resume
  run_training_resumable "smoke_r2" "$CFG_SMOKE" "$RUN_ROOT/20260724_qwen_fa_followup_smoke_r2" r2 2

  local long_smoke="$DERIVED_ROOT/20260724_m4singer_test_long_smoke"
  if [ ! -f "$long_smoke/run_summary.json" ]; then
    [ ! -e "$long_smoke" ] || archive_incomplete "$long_smoke"
    local tmp="${long_smoke}.tmp.$(date +%Y%m%d_%H%M%S).$$"
    "$PYTHON_BIN" "$PROJECT/scripts/datasets/build_synthetic_long.py" \
      --manifest "$M4_SPLIT" --annotations "$M4_CHARACTERS" --audio-root "$M4_AUDIO_ROOT" \
      --out-dir "$tmp" --bucket-sec 20 --split test --max-candidates 1
    mv "$tmp" "$long_smoke"
  fi
  local count
  count="$($PYTHON_BIN - "$long_smoke/run_summary.json" <<'PY'
import json,sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text())["synthetic_count"])
PY
)"
  if [ "$count" -gt 0 ]; then
    mkdir -p "$long_smoke/labels"
    if [ ! -f "$long_smoke/labels/qwen_fa_labels.jsonl" ]; then
      "$PYTHON_BIN" "$PROJECT/scripts/training/prepare_qwen_fa_labels.py" \
        --split-manifest "$long_smoke/synthetic_manifest.jsonl" --characters "$long_smoke/synthetic_characters.jsonl" \
        --out-dir "$long_smoke/labels" --output-name qwen_fa_labels.jsonl
    fi
    run_eval_atomic "smoke_long_raw" "$RUN_ROOT/20260724_qwen_fa_followup_smoke_long_raw" \
      --model "$MODEL_ID" --revision "$MODEL_REVISION" --checkpoint-kind raw \
      --labels "$long_smoke/labels/qwen_fa_labels.jsonl" --characters "$long_smoke/synthetic_characters.jsonl" \
      --audio-root "$long_smoke" --split test --max-items 1 --batch-size 1 --device cuda --local-files-only --evaluation-role smoke_long_raw
  else
    emit "smoke_long" "data_limited" "no 20-second test candidate; code path completed"
  fi
  touch "$STATE_ROOT/smoke.complete"
  emit "smoke" "complete" "$STATE_ROOT/smoke.complete"
}

prepare_long_bucket() {
  local bucket="$1" out="$DERIVED_ROOT/20260724_m4singer_test_synthetic_long_v1/bucket_${bucket}"
  if [ ! -f "$out/run_summary.json" ]; then
    [ ! -e "$out" ] || archive_incomplete "$out"
    local tmp="${out}.tmp.$(date +%Y%m%d_%H%M%S).$$"
    emit "long_${bucket}_build" "start" "$tmp"
    "$PYTHON_BIN" "$PROJECT/scripts/datasets/build_synthetic_long.py" \
      --manifest "$M4_SPLIT" --annotations "$M4_CHARACTERS" --audio-root "$M4_AUDIO_ROOT" \
      --out-dir "$tmp" --bucket-sec "$bucket" --split test
    mkdir -p "$(dirname "$out")"
    mv "$tmp" "$out"
  fi
  local count
  count="$($PYTHON_BIN - "$out/run_summary.json" <<'PY'
import json,sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text())["synthetic_count"])
PY
)"
  if [ "$count" -eq 0 ]; then
    emit "long_${bucket}" "data_limited" "no qualifying frozen-test sequence"
    return 2
  fi
  mkdir -p "$out/labels"
  if [ ! -f "$out/labels/qwen_fa_labels.jsonl" ]; then
    "$PYTHON_BIN" "$PROJECT/scripts/training/prepare_qwen_fa_labels.py" \
      --split-manifest "$out/synthetic_manifest.jsonl" --characters "$out/synthetic_characters.jsonl" \
      --out-dir "$out/labels" --output-name qwen_fa_labels.jsonl
  fi
}

run_long_bucket() {
  local bucket="$1" out="$DERIVED_ROOT/20260724_m4singer_test_synthetic_long_v1/bucket_${bucket}"
  set +e
  prepare_long_bucket "$bucket"
  local prep_rc=$?
  set -e
  if [ "$prep_rc" -eq 2 ]; then return 0; fi
  [ "$prep_rc" -eq 0 ] || return "$prep_rc"
  local labels="$out/labels/qwen_fa_labels.jsonl" chars="$out/synthetic_characters.jsonl" manifest="$out/synthetic_manifest.jsonl"
  local r1_ckpt r2_ckpt
  r1_ckpt="$(best_checkpoint "$FULL_R1_RUN")"; r2_ckpt="$(best_checkpoint "$FULL_R2_RUN")"
  local kinds=(raw r1 r2)
  for kind in "${kinds[@]}"; do
    local eval_out="$RUN_ROOT/20260724_qwen_fa_long_test_b${bucket}_${kind}"
    local args=(--model "$MODEL_ID" --revision "$MODEL_REVISION" --labels "$labels" --characters "$chars" --audio-root "$out" --split test --batch-size 1 --device cuda --local-files-only --evaluation-role "synthetic_long_test_b${bucket}_${kind}")
    case "$kind" in
      raw) args+=(--checkpoint-kind raw) ;;
      r1) args+=(--checkpoint-kind projector --checkpoint "$r1_ckpt") ;;
      r2) args+=(--checkpoint-kind lora --checkpoint "$r2_ckpt") ;;
    esac
    if run_eval_atomic "long_b${bucket}_${kind}" "$eval_out" "${args[@]}"; then
      "$PYTHON_BIN" "$PROJECT/scripts/evaluation/summarize_long_qwen_fa.py" \
        --manifest "$manifest" --characters "$chars" --predictions "$eval_out/predictions.jsonl" \
        --out "$eval_out/long_summary.json" --seam-margin-sec 0.5
    else
      emit "long_b${bucket}_${kind}" "optional_failure" "continuing to seed decision"
    fi
  done
}

write_summary() {
  "$PYTHON_BIN" - "$SUMMARY" "$R0_TEST" "$R0_OOD" "$FULL_R1_RUN" "$R1_TEST" "$R1_OOD" "$FULL_R2_RUN" "$FULL_R2_TEST" "$FULL_R2_OOD" "$SEED2_DECISION" "$RUN_ROOT" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
out = Path(sys.argv[1]); names = ["r0_m4_test","r0_mir_ood","r1_validation","r1_m4_test","r1_mir_ood","r2_validation","r2_m4_test","r2_mir_ood"]
paths = list(map(Path, sys.argv[2:10])); decision=Path(sys.argv[10]); run_root=Path(sys.argv[11])
def load_metric(path, validation=False):
    file = path / ("evaluation.json" if validation else "metrics.json")
    if not file.is_file(): return None
    data=json.loads(file.read_text(encoding="utf-8")); return data.get("metric", data)
result={"schema_version":1,"created_at":datetime.now(timezone.utc).isoformat(),"results":{}}
for name,path in zip(names,paths): result["results"][name]=load_metric(path, validation=name.endswith("validation"))
result["seed2_decision"]=json.loads(decision.read_text(encoding="utf-8")) if decision.is_file() else None
result["long_tests"]={}
for bucket in (20,30,60,180):
    result["long_tests"][str(bucket)]={}
    for kind in ("raw","r1","r2"):
        p=run_root/f"20260724_qwen_fa_long_test_b{bucket}_{kind}"/"long_summary.json"
        result["long_tests"][str(bucket)][kind]=json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"summary":str(out)},ensure_ascii=False))
PY
}

run_formal() {
  ensure_mir_labels
  local r2_ckpt
  r2_ckpt="$(best_checkpoint "$FULL_R2_RUN")"
  run_eval_atomic "r0_m4_test" "$R0_TEST" \
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --checkpoint-kind raw \
    --labels "$M4_LABELS" --characters "$M4_CHARACTERS" --audio-root "$M4_AUDIO_ROOT" \
    --split test --batch-size 4 --device cuda --local-files-only --evaluation-role r0_raw_m4singer_frozen_test
  run_eval_atomic "r0_mir_ood" "$R0_OOD" \
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --checkpoint-kind raw \
    --labels "$MIR_LABELS" --characters "$MIR_CHARACTERS" --audio-root "$MIR_ROOT" \
    --split test --batch-size 4 --device cuda --local-files-only --evaluation-role r0_raw_mir1k_ood

  run_training_resumable "full_r1_seed3407" "$CFG_R1" "$FULL_R1_RUN" r1 1110
  local r1_ckpt
  r1_ckpt="$(best_checkpoint "$FULL_R1_RUN")"
  run_eval_atomic "r1_m4_test" "$R1_TEST" \
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --checkpoint-kind projector --checkpoint "$r1_ckpt" \
    --labels "$M4_LABELS" --characters "$M4_CHARACTERS" --audio-root "$M4_AUDIO_ROOT" \
    --split test --batch-size 4 --device cuda --local-files-only --evaluation-role full_r1_m4singer_frozen_test
  run_eval_atomic "r1_mir_ood" "$R1_OOD" \
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --checkpoint-kind projector --checkpoint "$r1_ckpt" \
    --labels "$MIR_LABELS" --characters "$MIR_CHARACTERS" --audio-root "$MIR_ROOT" \
    --split test --batch-size 4 --device cuda --local-files-only --evaluation-role full_r1_mir1k_ood

  for bucket in 20 30 60 180; do
    set +e; run_long_bucket "$bucket"; local rc=$?; set -e
    [ "$rc" -eq 0 ] || emit "long_b${bucket}" "optional_failure" "rc=$rc; pipeline continues"
  done

  run_training_resumable "seed2_r1_pilot" "$CFG_SEED2_PILOT" "$SEED2_R1_PILOT" r1 100
  run_training_resumable "seed2_r2_pilot" "$CFG_SEED2_PILOT" "$SEED2_R2_PILOT" r2 100
  "$PYTHON_BIN" "$PROJECT/scripts/training/decide_qwen_fa_seed2.py" \
    --r1-evaluation "$SEED2_R1_PILOT/evaluation.json" --r2-evaluation "$SEED2_R2_PILOT/evaluation.json" \
    --seed "$SECOND_SEED" --out "$SEED2_DECISION"
  emit "seed2_decision" "complete" "$SEED2_DECISION"

  local recommendation
  recommendation="$($PYTHON_BIN - "$SEED2_DECISION" <<'PY'
import json,sys
from pathlib import Path
print("1" if json.loads(Path(sys.argv[1]).read_text())["recommend_full_r2_second_seed"] else "0")
PY
)"
  if [ "$AUTO_RUN_FULL_SEED2" = "1" ] && [ "$recommendation" = "1" ]; then
    run_training_resumable "full_r2_seed2" "$CFG_SEED2_FULL" "$SEED2_FULL_R2" r2 1110
  else
    emit "full_r2_seed2" "not_run" "AUTO_RUN_FULL_SEED2=$AUTO_RUN_FULL_SEED2 recommendation=$recommendation"
  fi
  write_summary
  touch "$STATE_ROOT/pipeline.complete"
  emit "pipeline" "complete" "$SUMMARY"
}

show_status() {
  echo "STATE_ROOT=$STATE_ROOT"
  [ -f "$STATE_ROOT/smoke.complete" ] && echo "smoke=complete" || echo "smoke=incomplete"
  [ -f "$STATE_ROOT/pipeline.complete" ] && echo "pipeline=complete" || echo "pipeline=incomplete"
  [ -f "$SEED2_DECISION" ] && cat "$SEED2_DECISION"
  [ -f "$SUMMARY" ] && echo "summary=$SUMMARY"
  [ -f "$EVENTS" ] && tail -n 30 "$EVENTS"
}

case "$MODE" in
  status) show_status; exit 0 ;;
  smoke) ;;
  run|resume) ;;
  *) fail "usage: $0 [run|resume|smoke|status]" ;;
esac

exec 9>"$LOCK"
flock -n 9 || fail "another follow-up pipeline holds $LOCK"
trap 'rc=$?; emit "pipeline" "exit" "rc=$rc"; exit $rc' EXIT

run_smoke
if [ "$MODE" != "smoke" ]; then run_formal; fi
