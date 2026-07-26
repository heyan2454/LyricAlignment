#!/usr/bin/env bash
# Complete the missing Qwen FA R2 evaluations in one idempotent entry.
#
# Default tasks:
#   1. Resolve or download a complete pinned local base-model snapshot.
#   2. Run seed3407 full-R2 MIR-1K OOD evaluation.
#   3. Run seed20260724 terminal step-001110 M4Singer validation.
#   4. Freeze the seed20260724 checkpoint using validation only.
#   5. Run seed20260724 M4Singer sealed test.
#   6. Run seed20260724 MIR-1K OOD test.
#   7. Write an aggregate summary.
#
# The script never deletes failed or incomplete evidence. Existing incomplete
# final directories are renamed with an .incomplete.<timestamp> suffix.
# Complete outputs are verified and skipped, so rerunning is safe.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
DATA_ROOT="${DATA_ROOT:-/home/hyan/Data/lyricalign}"
RUN_ROOT="${RUN_ROOT:-$DATA_ROOT/runs}"
DERIVED_ROOT="${DERIVED_ROOT:-$DATA_ROOT/derived}"

DEFAULT_PYTHON="/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python"
if [ -x "$DEFAULT_PYTHON" ]; then
  PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON}"
else
  PYTHON_BIN="${PYTHON_BIN:-python}"
fi

MODEL_ID="${MODEL_ID:-Qwen/Qwen3-ForcedAligner-0.6B-hf}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
HF_HUB_CACHE="${HF_HUB_CACHE:-$DATA_ROOT/models/hf_cache}"
MODEL_LOCAL_DIR="${MODEL_LOCAL_DIR:-$DATA_ROOT/models/Qwen3-ForcedAligner-0.6B-hf-${MODEL_REVISION:0:8}}"
MODEL_SOURCE="${MODEL_SOURCE:-}"
ALLOW_MODEL_DOWNLOAD="${ALLOW_MODEL_DOWNLOAD:-1}"

BATCH_SIZE="${BATCH_SIZE:-4}"
DEVICE="${DEVICE:-cuda}"
PREFLIGHT_ONLY="${PREFLIGHT_ONLY:-0}"
AUTO_ARCHIVE_INCOMPLETE="${AUTO_ARCHIVE_INCOMPLETE:-1}"

RUN_SEED3407_OOD="${RUN_SEED3407_OOD:-1}"
RUN_SEED2_TERMINAL_VALIDATION="${RUN_SEED2_TERMINAL_VALIDATION:-1}"
RUN_SEED2_M4_TEST="${RUN_SEED2_M4_TEST:-1}"
RUN_SEED2_MIR1K_OOD="${RUN_SEED2_MIR1K_OOD:-1}"

SEED3407_RUN="${SEED3407_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
SEED3407_OOD_OUT="${SEED3407_OOD_OUT:-$RUN_ROOT/20260723_qwen_fa_r2_full_mir1k_ood}"

SEED2_RUN="${SEED2_RUN:-$RUN_ROOT/20260724_qwen_fa_r2_full_seed20260724}"
SEED2_TERMINAL_STEP="${SEED2_TERMINAL_STEP:-1110}"
SEED2_TERMINAL_CKPT="${SEED2_TERMINAL_CKPT:-$SEED2_RUN/checkpoints/step-$(printf '%06d' "$SEED2_TERMINAL_STEP")}"
SEED2_TERMINAL_VAL_OUT="${SEED2_TERMINAL_VAL_OUT:-$RUN_ROOT/20260724_qwen_fa_r2_full_seed20260724_validation_step$(printf '%06d' "$SEED2_TERMINAL_STEP")}"
SEED2_SELECTION_JSON="${SEED2_SELECTION_JSON:-$SEED2_RUN/final_checkpoint_selection.json}"
SEED2_M4_TEST_OUT="${SEED2_M4_TEST_OUT:-$RUN_ROOT/20260724_qwen_fa_r2_full_seed20260724_m4singer_sealed_test}"
SEED2_MIR1K_OOD_OUT="${SEED2_MIR1K_OOD_OUT:-$RUN_ROOT/20260724_qwen_fa_r2_full_seed20260724_mir1k_ood}"

M4_AUDIO_ROOT="${M4_AUDIO_ROOT:-/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer}"
M4_LABELS="${M4_LABELS:-$DERIVED_ROOT/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl}"
M4_CHARACTERS="${M4_CHARACTERS:-$DERIVED_ROOT/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_character_annotations.jsonl}"

MIR1K_ROOT="${MIR1K_ROOT:-$DERIVED_ROOT/20260722_mir1k_vocal_channel1_ood}"
MIR1K_MANIFEST="${MIR1K_MANIFEST:-$MIR1K_ROOT/mir1k_vocal_ood_manifest.jsonl}"
MIR1K_CHARACTERS="${MIR1K_CHARACTERS:-$MIR1K_ROOT/mir1k_vocal_ood_characters.jsonl}"
MIR1K_LABEL_DIR="${MIR1K_LABEL_DIR:-$DERIVED_ROOT/20260724_mir1k_qwen_fa_labels_v1}"
MIR1K_LABELS="${MIR1K_LABELS:-$MIR1K_LABEL_DIR/mir1k_qwen_fa_labels.jsonl}"
MIR1K_LABEL_SUMMARY="${MIR1K_LABEL_SUMMARY:-$MIR1K_LABEL_DIR/label_preparation_summary.json}"

SUMMARY_JSON="${SUMMARY_JSON:-$RUN_ROOT/20260724_qwen_fa_r2_cross_seed_followup_summary.json}"

EXPECTED_MIR1K_MANIFEST_SHA256="bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f"
EXPECTED_MIR1K_CHARACTERS_SHA256="78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9"
TIMESTAMP_SEGMENT_SEC="0.08"
NUM_TIMESTAMP_LABELS="5000"
SELECTION_METRIC="song_macro_boundary_mae_sec"

export PYTHONUNBUFFERED=1
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

fail() { echo "ERROR: $*" >&2; exit 1; }
info() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
require_file() { [ -f "$1" ] || fail "required file missing: $1"; }
require_dir() { [ -d "$1" ] || fail "required directory missing: $1"; }
sha256_file() { sha256sum "$1" | awk '{print $1}'; }

is_complete_eval_dir() {
  local dir="$1"
  [ -f "$dir/metrics.json" ] && \
  [ -f "$dir/predictions.jsonl" ] && \
  [ -f "$dir/evaluation_identity.json" ] && \
  [ -f "$dir/return_code.txt" ] && \
  [ "$(tr -d '[:space:]' < "$dir/return_code.txt")" = "0" ]
}

prepare_final_path() {
  local final_dir="$1"
  if [ -e "$final_dir" ]; then
    if [ "$AUTO_ARCHIVE_INCOMPLETE" != "1" ]; then
      fail "existing final path cannot be reused safely: $final_dir (set AUTO_ARCHIVE_INCOMPLETE=1 to preserve-renaming it)"
    fi
    local archived="${final_dir}.incomplete.$(date +%Y%m%d_%H%M%S)"
    info "Preserving non-reusable output: $final_dir -> $archived"
    mv "$final_dir" "$archived"
  fi
}

eval_identity_matches() {
  local dir="$1"
  local checkpoint="$2"
  local labels="$3"
  local characters="$4"
  local split="$5"
  "$PYTHON_BIN" - \
    "$dir/evaluation_identity.json" "$checkpoint" "$labels" "$characters" \
    "$split" "$MODEL_REVISION" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

identity_path, checkpoint, labels, characters, split, revision = sys.argv[1:]

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

try:
    data = json.loads(Path(identity_path).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
checks = (
    str(data.get("checkpoint_path")) == str(Path(checkpoint)),
    str(data.get("split")) == split,
    str(data.get("model_revision")) == revision,
    str(data.get("labels_sha256")) == sha(labels),
    str(data.get("characters_sha256")) == sha(characters),
)
raise SystemExit(0 if all(checks) else 1)
PY
}

checkpoint_step() {
  local checkpoint="$1"
  local name
  name="$(basename "$checkpoint")"
  case "$name" in
    step-*) echo $((10#${name#step-})) ;;
    *) fail "cannot parse checkpoint step from: $checkpoint" ;;
  esac
}

check_checkpoint() {
  local checkpoint="$1"
  require_dir "$checkpoint"
  require_file "$checkpoint/adapter/adapter_config.json"
  require_file "$checkpoint/adapter/adapter_model.safetensors"
  require_file "$checkpoint/projector.pt"
  require_file "$checkpoint/checkpoint_identity.json"
}

read_best_checkpoint() {
  local run_dir="$1"
  "$PYTHON_BIN" - "$run_dir/best_checkpoint.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
print(data["checkpoint"])
PY
}

resolve_model_source() {
  mkdir -p "$HF_HUB_CACHE" "$(dirname "$MODEL_LOCAL_DIR")"

  "$PYTHON_BIN" - \
    "$MODEL_SOURCE" "$MODEL_LOCAL_DIR" "$HF_HUB_CACHE" \
    "$MODEL_ID" "$MODEL_REVISION" "$ALLOW_MODEL_DOWNLOAD" <<'PY'
import os
import sys
from pathlib import Path

explicit, local_dir, cache_dir, repo_id, revision, allow_download = sys.argv[1:]
local_dir = Path(local_dir)
cache_dir = Path(cache_dir)
allow_download = allow_download == "1"
repo_cache_name = "models--" + repo_id.replace("/", "--")

candidates = []
def add(value):
    if not value:
        return
    path = Path(value).expanduser()
    if path not in candidates:
        candidates.append(path)

add(explicit)
add(local_dir)
for root in (
    cache_dir,
    Path("/root/.cache/huggingface/hub"),
    Path("/home/hyan/.cache/huggingface/hub"),
    Path("/root/autodl-tmp/AST_storage/huggingface/hub"),
    Path("/root/autodl-tmp/AST_storage/hf/hub"),
):
    add(root / repo_cache_name / "snapshots" / revision)
    snapshots = root / repo_cache_name / "snapshots"
    if snapshots.is_dir():
        for child in sorted(snapshots.iterdir(), reverse=True):
            add(child)

required = ("config.json", "processor_config.json", "tokenizer.json")
def validate(path: Path):
    problems = []
    if not path.is_dir():
        return False, ["not_directory"]
    for name in required:
        if not (path / name).is_file():
            problems.append(f"missing:{name}")
    weight = path / "model.safetensors"
    if not weight.is_file():
        problems.append("missing:model.safetensors")
    else:
        size = weight.stat().st_size
        if size < 1_000_000_000:
            problems.append(f"model.safetensors_too_small:{size}")
        else:
            try:
                from safetensors import safe_open
                with safe_open(str(weight), framework="pt", device="cpu") as handle:
                    if not list(handle.keys()):
                        problems.append("model.safetensors_has_no_tensors")
            except Exception as exc:
                problems.append(f"model.safetensors_unreadable:{type(exc).__name__}:{exc}")
    return not problems, problems

for candidate in candidates:
    ok, problems = validate(candidate)
    if ok:
        print(str(candidate.resolve()))
        raise SystemExit(0)
    if candidate.exists():
        print(f"Rejected model candidate {candidate}: {', '.join(problems)}", file=sys.stderr)

if not allow_download:
    raise SystemExit(
        "No complete local model snapshot was found. Set ALLOW_MODEL_DOWNLOAD=1 "
        "or MODEL_SOURCE=/absolute/path/to/a/complete/snapshot."
    )

print(
    f"No complete local model snapshot found; downloading pinned {repo_id}@{revision} "
    f"to {local_dir}",
    file=sys.stderr,
)
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id=repo_id,
    revision=revision,
    local_dir=str(local_dir),
    cache_dir=str(cache_dir),
)
ok, problems = validate(local_dir)
if not ok:
    raise SystemExit(f"Downloaded model directory is incomplete: {problems}")
print(str(local_dir.resolve()))
PY
}

validate_model_schema() {
  "$PYTHON_BIN" - "$MODEL_LOAD_SOURCE" "$TIMESTAMP_SEGMENT_SEC" "$NUM_TIMESTAMP_LABELS" <<'PY'
import sys
from pathlib import Path
from transformers import AutoConfig, AutoProcessor

source = Path(sys.argv[1])
expected_sec = float(sys.argv[2])
expected_labels = int(sys.argv[3])
processor = AutoProcessor.from_pretrained(source, local_files_only=True)
config = AutoConfig.from_pretrained(source, local_files_only=True)
raw_segment = float(processor.timestamp_segment_time)
segment_sec = raw_segment / 1000.0 if raw_segment > 1.0 else raw_segment
if abs(segment_sec - expected_sec) > 1e-12:
    raise SystemExit(
        f"timestamp segment mismatch: raw={raw_segment}, normalized_sec={segment_sec}, expected={expected_sec}"
    )
if int(config.num_labels) != expected_labels:
    raise SystemExit(f"num_labels mismatch: model={config.num_labels}, expected={expected_labels}")
weight = source / "model.safetensors"
print(
    f"Model schema passed: source={source}, timestamp_raw={raw_segment}, "
    f"timestamp_sec={segment_sec}, num_labels={config.num_labels}, "
    f"weight_bytes={weight.stat().st_size}"
)
PY
}

prepare_mir1k_labels() {
  require_file "$MIR1K_MANIFEST"
  require_file "$MIR1K_CHARACTERS"
  require_dir "$MIR1K_ROOT/vocal_wavs"

  [ "$(sha256_file "$MIR1K_MANIFEST")" = "$EXPECTED_MIR1K_MANIFEST_SHA256" ] || \
    fail "MIR-1K source manifest hash mismatch"
  [ "$(sha256_file "$MIR1K_CHARACTERS")" = "$EXPECTED_MIR1K_CHARACTERS_SHA256" ] || \
    fail "MIR-1K character annotations hash mismatch"

  if [ ! -f "$MIR1K_LABELS" ] || [ ! -f "$MIR1K_LABEL_SUMMARY" ]; then
    if [ -e "$MIR1K_LABEL_DIR" ]; then
      fail "MIR-1K label directory exists but is incomplete: $MIR1K_LABEL_DIR"
    fi
    local tmp="${MIR1K_LABEL_DIR}.tmp.$(date +%Y%m%d_%H%M%S).$$"
    mkdir -p "$tmp"
    info "Preparing deterministic MIR-1K Qwen FA labels"
    "$PYTHON_BIN" "$PROJECT/scripts/training/prepare_qwen_fa_labels.py" \
      --split-manifest "$MIR1K_MANIFEST" \
      --characters "$MIR1K_CHARACTERS" \
      --out-dir "$tmp" \
      --timestamp-segment-sec "$TIMESTAMP_SEGMENT_SEC" \
      --num-labels "$NUM_TIMESTAMP_LABELS"
    require_file "$tmp/m4singer_qwen_fa_labels.jsonl"
    mv "$tmp/m4singer_qwen_fa_labels.jsonl" "$tmp/mir1k_qwen_fa_labels.jsonl"
    mv "$tmp" "$MIR1K_LABEL_DIR"
  fi

  require_file "$MIR1K_LABELS"
  require_file "$MIR1K_LABEL_SUMMARY"

  "$PYTHON_BIN" - \
    "$MIR1K_MANIFEST" "$MIR1K_CHARACTERS" "$MIR1K_LABELS" "$MIR1K_LABEL_SUMMARY" \
    "$EXPECTED_MIR1K_MANIFEST_SHA256" "$EXPECTED_MIR1K_CHARACTERS_SHA256" \
    "$TIMESTAMP_SEGMENT_SEC" "$NUM_TIMESTAMP_LABELS" <<'PY'
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from lyricalign.training.qwen_fa_labels import build_label_record

manifest_path, chars_path, labels_path, summary_path = map(Path, sys.argv[1:5])
expected_manifest_hash, expected_chars_hash = sys.argv[5:7]
segment_sec, num_labels = float(sys.argv[7]), int(sys.argv[8])

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

manifest = read_jsonl(manifest_path)
characters = read_jsonl(chars_path)
labels = read_jsonl(labels_path)
summary = json.loads(summary_path.read_text(encoding="utf-8"))
if sha(manifest_path) != expected_manifest_hash or sha(chars_path) != expected_chars_hash:
    raise SystemExit("frozen MIR-1K source hash mismatch")
if summary["source_split_manifest_sha256"] != expected_manifest_hash:
    raise SystemExit("label summary points to a different MIR-1K manifest")
if summary["source_character_annotations_sha256"] != expected_chars_hash:
    raise SystemExit("label summary points to different MIR-1K characters")
if summary["output_labels_sha256"] != sha(labels_path):
    raise SystemExit("derived MIR-1K label hash differs from preparation summary")
if len(manifest) != 17 or len(labels) != 17 or len(characters) != 2035:
    raise SystemExit(
        f"unexpected frozen MIR-1K counts: manifest={len(manifest)}, labels={len(labels)}, chars={len(characters)}"
    )
by_item = defaultdict(list)
for row in characters:
    by_item[str(row["item_id"])].append(row)
expected = [
    build_label_record(
        row,
        by_item[str(row["item_id"])],
        segment_sec=segment_sec,
        num_labels=num_labels,
    )
    for row in manifest
]
if expected != labels:
    raise SystemExit("derived MIR-1K labels are not an exact reconstruction")
if sum(len(row["timestamp_class_ids"]) for row in labels) != 4070:
    raise SystemExit("unexpected MIR-1K timestamp label count")
print(
    f"MIR-1K labels passed: items={len(labels)}, characters={len(characters)}, "
    f"sha256={sha(labels_path)}"
)
PY
}

augment_evaluation_identity() {
  local identity_path="$1"
  local checkpoint="$2"
  local role="$3"
  local selection_json="${4:-}"
  local usage="${5:-evaluation}"
  local step
  step="$(checkpoint_step "$checkpoint")"

  "$PYTHON_BIN" - \
    "$identity_path" "$MODEL_ID" "$MODEL_REVISION" "$MODEL_LOAD_SOURCE" \
    "$MODEL_WEIGHT_SHA256" "$checkpoint" "$step" "$role" "$selection_json" "$usage" \
    "$SELECTION_METRIC" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    identity_path, canonical_model_id, revision, load_source, model_weight_sha256,
    checkpoint, step, role, selection_json, usage, selection_metric,
) = sys.argv[1:]
identity_path = Path(identity_path)
checkpoint = Path(checkpoint)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

data = json.loads(identity_path.read_text(encoding="utf-8"))
data.update({
    "identity_augmented_at": datetime.now(timezone.utc).isoformat(),
    "evaluation_role": role,
    "model_id": canonical_model_id,
    "model_revision": revision,
    "model_load_source": load_source,
    "model_weight_sha256": model_weight_sha256,
    "checkpoint_step": int(step),
    "checkpoint_path": str(checkpoint),
    "adapter_sha256": sha(checkpoint / "adapter" / "adapter_model.safetensors"),
    "projector_sha256": sha(checkpoint / "projector.pt"),
    "checkpoint_identity_sha256": sha(checkpoint / "checkpoint_identity.json"),
    "usage": usage,
    "checkpoint_selection_metric": selection_metric,
    "test_or_ood_not_used_for_checkpoint_selection": usage in {"sealed_test", "ood_test_only"},
})
if selection_json:
    selection = Path(selection_json)
    data["checkpoint_selection_path"] = str(selection)
    data["checkpoint_selection_sha256"] = sha(selection)
tmp = identity_path.with_suffix(identity_path.suffix + ".tmp")
tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(identity_path)
PY
}

run_evaluation() {
  local final_dir="$1"
  local checkpoint="$2"
  local labels="$3"
  local characters="$4"
  local audio_root="$5"
  local split="$6"
  local role="$7"
  local selection_json="${8:-}"
  local usage="${9:-evaluation}"

  check_checkpoint "$checkpoint"
  require_file "$labels"
  require_file "$characters"
  require_dir "$audio_root"

  if is_complete_eval_dir "$final_dir"; then
    if eval_identity_matches "$final_dir" "$checkpoint" "$labels" "$characters" "$split"; then
      info "Complete matching output already exists; skipping: $final_dir"
      return 0
    fi
    info "Complete output exists but its checkpoint/dataset identity does not match the requested evaluation"
  fi
  prepare_final_path "$final_dir"

  local stamp tmp_dir rc
  stamp="$(date +%Y%m%d_%H%M%S)"
  tmp_dir="${final_dir}.tmp.${stamp}.$$"
  mkdir -p "$tmp_dir"

  cat > "$tmp_dir/command.sh" <<CMD
cd "$PROJECT"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \\
"$PYTHON_BIN" scripts/training/evaluate_qwen_fa_checkpoint.py \\
  --model "$MODEL_LOAD_SOURCE" \\
  --revision "$MODEL_REVISION" \\
  --checkpoint-kind lora \\
  --checkpoint "$checkpoint" \\
  --labels "$labels" \\
  --characters "$characters" \\
  --audio-root "$audio_root" \\
  --out-dir "$tmp_dir" \\
  --split "$split" \\
  --batch-size "$BATCH_SIZE" \\
  --device "$DEVICE" \\
  --local-files-only \\
  --evaluation-role "$role"
CMD

  info "Starting $role"
  info "Checkpoint: $checkpoint"
  info "Output:     $tmp_dir"

  set +e
  (
    cd "$PROJECT"
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" scripts/training/evaluate_qwen_fa_checkpoint.py \
      --model "$MODEL_LOAD_SOURCE" \
      --revision "$MODEL_REVISION" \
      --checkpoint-kind lora \
      --checkpoint "$checkpoint" \
      --labels "$labels" \
      --characters "$characters" \
      --audio-root "$audio_root" \
      --out-dir "$tmp_dir" \
      --split "$split" \
      --batch-size "$BATCH_SIZE" \
      --device "$DEVICE" \
      --local-files-only \
      --evaluation-role "$role"
  ) > >(tee "$tmp_dir/stdout.log") 2> >(tee "$tmp_dir/stderr.log" >&2)
  rc=$?
  set -e

  echo "$rc" > "$tmp_dir/return_code.txt"
  if [ "$rc" -ne 0 ]; then
    fail "$role failed; partial evidence retained at $tmp_dir"
  fi

  require_file "$tmp_dir/metrics.json"
  require_file "$tmp_dir/predictions.jsonl"
  require_file "$tmp_dir/evaluation_identity.json"
  augment_evaluation_identity \
    "$tmp_dir/evaluation_identity.json" "$checkpoint" "$role" "$selection_json" "$usage"

  mv "$tmp_dir" "$final_dir"
  info "Completed: $final_dir"
}

freeze_seed2_selection() {
  require_file "$SEED2_TERMINAL_VAL_OUT/metrics.json"
  check_checkpoint "$SEED2_TERMINAL_CKPT"

  "$PYTHON_BIN" - \
    "$SEED2_RUN" "$SEED2_TERMINAL_VAL_OUT/metrics.json" "$SEED2_TERMINAL_STEP" \
    "$SEED2_SELECTION_JSON" "$SELECTION_METRIC" <<'PY'
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
terminal_metrics_path = Path(sys.argv[2])
terminal_step = int(sys.argv[3])
out_path = Path(sys.argv[4])
metric_name = sys.argv[5]

candidates = []
for path in sorted(run_dir.glob("validation_step_*.json")):
    try:
        step = int(path.stem.rsplit("_", 1)[1])
    except ValueError:
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    value = float(data["metric"][metric_name])
    checkpoint = run_dir / "checkpoints" / f"step-{step:06d}"
    if not checkpoint.is_dir():
        raise SystemExit(f"validation candidate checkpoint is missing: {checkpoint}")
    candidates.append({
        "step": step,
        "checkpoint": str(checkpoint),
        metric_name: value,
        "metrics_path": str(path),
        "candidate_kind": "periodic_validation",
    })

historical_path = run_dir / "best_checkpoint.json"
historical = (
    json.loads(historical_path.read_text(encoding="utf-8"))
    if historical_path.is_file()
    else None
)
if historical is not None:
    historical_step = int(historical["step"])
    historical_checkpoint = Path(historical["checkpoint"])
    historical_value = float(historical[metric_name])
    if not historical_checkpoint.is_dir():
        raise SystemExit(f"historical validation-best checkpoint is missing: {historical_checkpoint}")
    if not any(candidate["step"] == historical_step for candidate in candidates):
        candidates.append({
            "step": historical_step,
            "checkpoint": str(historical_checkpoint),
            metric_name: historical_value,
            "metrics_path": str(historical_path),
            "candidate_kind": "historical_best_checkpoint_record",
        })

terminal = json.loads(terminal_metrics_path.read_text(encoding="utf-8"))
terminal_value = float(terminal["metric"][metric_name])
terminal_checkpoint = run_dir / "checkpoints" / f"step-{terminal_step:06d}"
candidates = [candidate for candidate in candidates if candidate["step"] != terminal_step]
candidates.append({
    "step": terminal_step,
    "checkpoint": str(terminal_checkpoint),
    metric_name: terminal_value,
    "metrics_path": str(terminal_metrics_path),
    "candidate_kind": "terminal_validation",
})
if not candidates:
    raise SystemExit("no seed2 validation candidates found")
for candidate in candidates:
    value = candidate[metric_name]
    if not math.isfinite(value):
        raise SystemExit(f"non-finite selection metric: {candidate}")

# Primary: lower validation song-macro boundary MAE. Exact tie: lower step.
selected = min(candidates, key=lambda item: (item[metric_name], item["step"]))
result = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "run_dir": str(run_dir),
    "selection_split": "M4Singer_validation",
    "selection_metric": metric_name,
    "selection_direction": "lower_is_better",
    "tie_break": "lower_checkpoint_step",
    "test_or_ood_not_used_for_checkpoint_selection": True,
    "historical_best_checkpoint_json": str(historical_path),
    "historical_best_checkpoint": historical,
    "candidates": sorted(candidates, key=lambda item: item["step"]),
    "selected": selected,
}
out_path.parent.mkdir(parents=True, exist_ok=True)
tmp = out_path.with_suffix(out_path.suffix + ".tmp")
tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(out_path)
print(selected["checkpoint"])
PY
}

write_summary() {
  "$PYTHON_BIN" - \
    "$SUMMARY_JSON" "$MODEL_ID" "$MODEL_REVISION" "$MODEL_LOAD_SOURCE" \
    "$SEED3407_RUN" "$SEED3407_OOD_OUT" \
    "$SEED2_RUN" "$SEED2_TERMINAL_VAL_OUT" "$SEED2_SELECTION_JSON" \
    "$SEED2_M4_TEST_OUT" "$SEED2_MIR1K_OOD_OUT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    output, model_id, revision, model_source,
    seed3407_run, seed3407_ood,
    seed2_run, seed2_terminal_val, seed2_selection,
    seed2_m4_test, seed2_mir1k_ood,
) = sys.argv[1:]

def load(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

def metric_dir(path):
    data = load(Path(path) / "metrics.json")
    return None if data is None else data.get("metric", data)

summary = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "model_id": model_id,
    "model_revision": revision,
    "model_load_source": model_source,
    "seed3407": {
        "run_dir": seed3407_run,
        "validation_best_checkpoint": load(Path(seed3407_run) / "best_checkpoint.json"),
        "mir1k_ood_dir": seed3407_ood,
        "mir1k_ood": metric_dir(seed3407_ood),
        "mir1k_ood_identity": load(Path(seed3407_ood) / "evaluation_identity.json"),
    },
    "seed20260724": {
        "run_dir": seed2_run,
        "terminal_validation_dir": seed2_terminal_val,
        "terminal_validation": metric_dir(seed2_terminal_val),
        "final_checkpoint_selection": load(seed2_selection),
        "m4singer_sealed_test_dir": seed2_m4_test,
        "m4singer_sealed_test": metric_dir(seed2_m4_test),
        "m4singer_sealed_test_identity": load(Path(seed2_m4_test) / "evaluation_identity.json"),
        "mir1k_ood_dir": seed2_mir1k_ood,
        "mir1k_ood": metric_dir(seed2_mir1k_ood),
        "mir1k_ood_identity": load(Path(seed2_mir1k_ood) / "evaluation_identity.json"),
    },
}
output = Path(output)
output.parent.mkdir(parents=True, exist_ok=True)
tmp = output.with_suffix(output.suffix + ".tmp")
tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(output)
print(output)
PY
}

print_selected_metrics() {
  "$PYTHON_BIN" - "$SUMMARY_JSON" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
print("\n===== Final evaluation summary =====")
for seed_key, label in (("seed3407", "seed3407"), ("seed20260724", "seed20260724")):
    seed = data[seed_key]
    if seed_key == "seed20260724":
        selection = seed.get("final_checkpoint_selection")
        if selection:
            selected = selection["selected"]
            print(
                f"{label} selected step: {selected['step']} "
                f"({selection['selection_metric']}={selected[selection['selection_metric']] * 1000:.3f} ms)"
            )
        metric_pairs = (
            ("terminal_validation", seed.get("terminal_validation")),
            ("m4singer_sealed_test", seed.get("m4singer_sealed_test")),
            ("mir1k_ood", seed.get("mir1k_ood")),
        )
    else:
        metric_pairs = (("mir1k_ood", seed.get("mir1k_ood")),)
    for name, metric in metric_pairs:
        if not metric:
            print(f"{label} {name}: MISSING")
            continue
        value = metric.get("song_macro_boundary_mae_sec")
        coverage = metric.get("item_coverage")
        print(
            f"{label} {name}: song_macro_boundary_mae="
            f"{value * 1000:.3f} ms, item_coverage={coverage}"
        )
PY
}

main() {
  cd "$PROJECT"
  require_dir "$PROJECT"
  require_file "$PROJECT/scripts/training/evaluate_qwen_fa_checkpoint.py"
  require_file "$PROJECT/scripts/training/prepare_qwen_fa_labels.py"
  require_file "$M4_LABELS"
  require_file "$M4_CHARACTERS"
  require_dir "$M4_AUDIO_ROOT"
  require_dir "$SEED3407_RUN"
  require_file "$SEED3407_RUN/best_checkpoint.json"
  require_dir "$SEED2_RUN"
  require_file "$SEED2_RUN/best_checkpoint.json"

  "$PYTHON_BIN" - <<'PY'
import peft, safetensors, torch, transformers, yaml
print(
    "Environment passed: "
    f"torch={torch.__version__}, transformers={transformers.__version__}, peft={peft.__version__}"
)
PY

  info "Resolving complete pinned base model"
  MODEL_LOAD_SOURCE="$(resolve_model_source)"
  export MODEL_LOAD_SOURCE HF_HUB_CACHE
  # All evaluation calls below use this local absolute path and remain offline.
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  info "Using model source: $MODEL_LOAD_SOURCE"
  validate_model_schema
  info "Hashing pinned base-model weights once"
  MODEL_WEIGHT_SHA256="$(sha256_file "$MODEL_LOAD_SOURCE/model.safetensors")"
  export MODEL_WEIGHT_SHA256
  info "Base-model weight SHA-256: $MODEL_WEIGHT_SHA256"
  prepare_mir1k_labels

  local seed3407_checkpoint
  seed3407_checkpoint="$(read_best_checkpoint "$SEED3407_RUN")"
  check_checkpoint "$seed3407_checkpoint"
  check_checkpoint "$SEED2_TERMINAL_CKPT"

  info "Planned seed3407 checkpoint: $seed3407_checkpoint"
  info "Planned seed2 terminal checkpoint: $SEED2_TERMINAL_CKPT"

  if [ "$PREFLIGHT_ONLY" = "1" ]; then
    info "PREFLIGHT_ONLY=1; no inference was run"
    exit 0
  fi

  if [ "$RUN_SEED3407_OOD" = "1" ]; then
    run_evaluation \
      "$SEED3407_OOD_OUT" "$seed3407_checkpoint" \
      "$MIR1K_LABELS" "$MIR1K_CHARACTERS" "$MIR1K_ROOT" test \
      final_full_r2_seed3407_mir1k_ood "$SEED3407_RUN/best_checkpoint.json" ood_test_only
  fi

  if [ "$RUN_SEED2_TERMINAL_VALIDATION" = "1" ]; then
    run_evaluation \
      "$SEED2_TERMINAL_VAL_OUT" "$SEED2_TERMINAL_CKPT" \
      "$M4_LABELS" "$M4_CHARACTERS" "$M4_AUDIO_ROOT" validation \
      full_r2_seed20260724_terminal_validation "" validation_selection_candidate
  fi

  if ! is_complete_eval_dir "$SEED2_TERMINAL_VAL_OUT"; then
    fail "seed2 terminal validation is required before checkpoint selection"
  fi

  local seed2_selected_checkpoint
  seed2_selected_checkpoint="$(freeze_seed2_selection)"
  check_checkpoint "$seed2_selected_checkpoint"
  info "Frozen seed2 checkpoint from validation only: $seed2_selected_checkpoint"

  if [ "$RUN_SEED2_M4_TEST" = "1" ]; then
    run_evaluation \
      "$SEED2_M4_TEST_OUT" "$seed2_selected_checkpoint" \
      "$M4_LABELS" "$M4_CHARACTERS" "$M4_AUDIO_ROOT" test \
      full_r2_seed20260724_m4singer_sealed_test "$SEED2_SELECTION_JSON" sealed_test
  fi

  if [ "$RUN_SEED2_MIR1K_OOD" = "1" ]; then
    run_evaluation \
      "$SEED2_MIR1K_OOD_OUT" "$seed2_selected_checkpoint" \
      "$MIR1K_LABELS" "$MIR1K_CHARACTERS" "$MIR1K_ROOT" test \
      full_r2_seed20260724_mir1k_ood "$SEED2_SELECTION_JSON" ood_test_only
  fi

  write_summary >/dev/null
  print_selected_metrics
  info "Summary written: $SUMMARY_JSON"
}

main "$@"
