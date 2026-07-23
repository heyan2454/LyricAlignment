#!/usr/bin/env bash
# Safely finish the first full Qwen FA R2 experiment.
#
# Modes:
#   inspect   Read-only identity and artifact check (default).
#   run-ood   Run only the missing full-R2 MIR-1K OOD evaluation.
#   summarize Print/write a lightweight final result summary.
#
# This entry intentionally does NOT rerun the M4Singer sealed test.
set -Eeuo pipefail

MODE="${1:-inspect}"
PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs}"
FULL_RUN="${FULL_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
SEALED_TEST_DIR="${SEALED_TEST_DIR:-$RUN_ROOT/20260723_qwen_fa_r2_full_m4singer_sealed_test}"
FINAL_OOD_DIR="${FINAL_OOD_DIR:-$RUN_ROOT/20260723_qwen_fa_r2_full_mir1k_ood}"
PILOT_OOD_DIR="${PILOT_OOD_DIR:-$RUN_ROOT/20260723_qwen_fa_r2_mir1k_ood}"
MIR1K_ROOT="${MIR1K_ROOT:-/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood}"
MIR1K_LABELS="${MIR1K_LABELS:-$MIR1K_ROOT/mir1k_vocal_ood_manifest.jsonl}"
MIR1K_CHARACTERS="${MIR1K_CHARACTERS:-$MIR1K_ROOT/mir1k_vocal_ood_characters.jsonl}"
PYTHON_BIN="${PYTHON_BIN:-python}"
EXPECTED_MIR1K_LABELS_SHA256="bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f"
EXPECTED_MIR1K_CHARACTERS_SHA256="78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_file() {
  [ -f "$1" ] || fail "required file is missing: $1"
}

require_dir() {
  [ -d "$1" ] || fail "required directory is missing: $1"
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

read_config_value() {
  local dotted="$1"
  "$PYTHON_BIN" - "$FULL_RUN/config.yaml" "$dotted" <<'PY'
import sys
from pathlib import Path
import yaml

path = Path(sys.argv[1])
keys = sys.argv[2].split(".")
value = yaml.safe_load(path.read_text(encoding="utf-8"))
for key in keys:
    value = value[key]
print(value)
PY
}

best_checkpoint_path() {
  "$PYTHON_BIN" - "$FULL_RUN/best_checkpoint.json" <<'PY'
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
print(data["checkpoint"])
PY
}

best_checkpoint_step() {
  "$PYTHON_BIN" - "$FULL_RUN/best_checkpoint.json" <<'PY'
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
print(data["step"])
PY
}

check_checkpoint() {
  local ckpt="$1"
  require_dir "$ckpt"
  require_file "$ckpt/adapter/adapter_config.json"
  require_file "$ckpt/adapter/adapter_model.safetensors"
  require_file "$ckpt/projector.pt"
  require_file "$ckpt/trainer_state.pt"
  require_file "$ckpt/checkpoint_identity.json"
}

print_metric_file() {
  local label="$1"
  local path="$2"
  echo
  echo "===== $label ====="
  if [ ! -f "$path" ]; then
    echo "MISSING: $path"
    return
  fi
  "$PYTHON_BIN" - "$path" <<'PY'
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
metric = data.get("metric", data)
for key in (
    "song_macro_boundary_mae_sec",
    "all_item_penalized_boundary_mae_sec",
    "valid_only_boundary_mae_sec",
    "onset_mae_sec",
    "offset_mae_sec",
    "onset_p90_sec",
    "offset_p90_sec",
    "joint_within_80ms",
    "joint_within_160ms",
    "joint_within_240ms",
    "mean_iou",
    "invalid_prediction_rate",
    "item_coverage",
    "song_coverage",
):
    value = metric.get(key)
    if value is None:
        continue
    if key.endswith("_sec"):
        print(f"{key}: {value * 1000:.3f} ms")
    else:
        print(f"{key}: {value}")
PY
}

inspect_state() {
  echo "Project:          $PROJECT"
  echo "Full run:         $FULL_RUN"
  echo "Sealed test:      $SEALED_TEST_DIR"
  echo "Final OOD target: $FINAL_OOD_DIR"
  echo

  require_dir "$PROJECT"
  require_dir "$FULL_RUN"
  require_file "$FULL_RUN/config.yaml"
  require_file "$FULL_RUN/best_checkpoint.json"

  local ckpt step
  ckpt="$(best_checkpoint_path)"
  step="$(best_checkpoint_step)"
  check_checkpoint "$ckpt"

  echo "Validation-best step:       $step"
  echo "Validation-best checkpoint: $ckpt"
  echo "Adapter SHA-256:             $(sha256_file "$ckpt/adapter/adapter_model.safetensors")"
  echo "Projector SHA-256:           $(sha256_file "$ckpt/projector.pt")"

  echo
  if [ -f "$SEALED_TEST_DIR/metrics.json" ]; then
    echo "M4Singer sealed test metrics: PRESENT"
  else
    echo "M4Singer sealed test metrics: MISSING"
  fi

  if [ -f "$SEALED_TEST_DIR/evaluation_identity.json" ]; then
    echo "Sealed-test checkpoint identity: RECORDED"
  else
    echo "Sealed-test checkpoint identity: UNVERIFIED (metrics file has no checkpoint path/hash)"
  fi

  if [ -f "$FINAL_OOD_DIR/metrics.json" ]; then
    echo "Full R2 MIR-1K OOD metrics: PRESENT"
  elif [ -e "$FINAL_OOD_DIR" ]; then
    echo "Full R2 MIR-1K OOD output: EXISTS BUT INCOMPLETE; inspect before moving/removing it"
  else
    echo "Full R2 MIR-1K OOD metrics: MISSING"
  fi

  if [ -f "$PILOT_OOD_DIR/metrics.json" ]; then
    echo "Pilot MIR-1K OOD metrics: PRESENT (must not be mislabeled as final full R2)"
  fi

  print_metric_file "full R2 validation final" "$FULL_RUN/evaluation.json"
  print_metric_file "full R2 M4Singer sealed test" "$SEALED_TEST_DIR/metrics.json"
  print_metric_file "full R2 MIR-1K OOD" "$FINAL_OOD_DIR/metrics.json"
  print_metric_file "pilot R2 MIR-1K OOD (historical comparison only)" "$PILOT_OOD_DIR/metrics.json"
}

run_ood() {
  require_dir "$PROJECT"
  require_dir "$FULL_RUN"
  require_file "$FULL_RUN/config.yaml"
  require_file "$FULL_RUN/best_checkpoint.json"
  require_file "$MIR1K_LABELS"
  require_file "$MIR1K_CHARACTERS"
  require_dir "$MIR1K_ROOT/vocal_wavs"
  require_file "$PROJECT/scripts/training/evaluate_qwen_fa_checkpoint.py"

  "$PYTHON_BIN" - <<'PY' || fail "activate the lyricalign-qwen Conda environment before run-ood"
import peft, torch, transformers, yaml
print("Python environment check passed")
PY

  local labels_sha chars_sha
  labels_sha="$(sha256_file "$MIR1K_LABELS")"
  chars_sha="$(sha256_file "$MIR1K_CHARACTERS")"
  [ "$labels_sha" = "$EXPECTED_MIR1K_LABELS_SHA256" ] || \
    fail "MIR-1K labels SHA-256 mismatch: $labels_sha"
  [ "$chars_sha" = "$EXPECTED_MIR1K_CHARACTERS_SHA256" ] || \
    fail "MIR-1K character SHA-256 mismatch: $chars_sha"

  if [ -e "$FINAL_OOD_DIR" ]; then
    fail "refusing to overwrite existing final OOD path: $FINAL_OOD_DIR"
  fi

  local ckpt step model revision stamp tmp_dir
  ckpt="$(best_checkpoint_path)"
  step="$(best_checkpoint_step)"
  check_checkpoint "$ckpt"
  model="$(read_config_value model.id)"
  revision="$(read_config_value model.revision)"
  stamp="$(date +%Y%m%d_%H%M%S)"
  tmp_dir="${FINAL_OOD_DIR}.tmp.${stamp}.$$"

  mkdir -p "$tmp_dir"

  cat > "$tmp_dir/command.sh" <<CMD
cd "$PROJECT"
$PYTHON_BIN scripts/training/evaluate_qwen_fa_checkpoint.py \\
  --model "$model" \\
  --revision "$revision" \\
  --checkpoint "$ckpt" \\
  --labels "$MIR1K_LABELS" \\
  --characters "$MIR1K_CHARACTERS" \\
  --audio-root "$MIR1K_ROOT" \\
  --out-dir "$tmp_dir" \\
  --split test \\
  --batch-size 4 \\
  --device cuda
CMD

  echo "Running final full-R2 MIR-1K OOD"
  echo "Frozen checkpoint: $ckpt (step $step)"
  echo "Temporary output:  $tmp_dir"

  set +e
  (
    cd "$PROJECT"
    "$PYTHON_BIN" scripts/training/evaluate_qwen_fa_checkpoint.py \
      --model "$model" \
      --revision "$revision" \
      --checkpoint "$ckpt" \
      --labels "$MIR1K_LABELS" \
      --characters "$MIR1K_CHARACTERS" \
      --audio-root "$MIR1K_ROOT" \
      --out-dir "$tmp_dir" \
      --split test \
      --batch-size 4 \
      --device cuda
  ) > >(tee "$tmp_dir/stdout.log") 2> >(tee "$tmp_dir/stderr.log" >&2)
  local rc=$?
  set -e

  if [ "$rc" -ne 0 ]; then
    echo "$rc" > "$tmp_dir/return_code.txt"
    fail "OOD evaluation failed; partial evidence retained at $tmp_dir"
  fi

  require_file "$tmp_dir/metrics.json"
  require_file "$tmp_dir/predictions.jsonl"

  "$PYTHON_BIN" - \
    "$tmp_dir/evaluation_identity.json" \
    "$model" "$revision" "$ckpt" "$step" \
    "$FULL_RUN/best_checkpoint.json" \
    "$MIR1K_LABELS" "$MIR1K_CHARACTERS" "$MIR1K_ROOT" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    out_path,
    model,
    revision,
    checkpoint,
    step,
    best_json,
    labels,
    characters,
    audio_root,
) = sys.argv[1:]

def sha256(path: str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

ckpt = Path(checkpoint)
data = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "evaluation_role": "final_full_r2_mir1k_ood",
    "selection_split": "M4Singer_validation",
    "selection_metric": "song_macro_boundary_mae_sec",
    "test_or_ood_not_used_for_checkpoint_selection": True,
    "model_id": model,
    "model_revision": revision,
    "checkpoint_step": int(step),
    "checkpoint_path": str(ckpt),
    "best_checkpoint_json": best_json,
    "best_checkpoint_json_sha256": sha256(best_json),
    "adapter_sha256": sha256(str(ckpt / "adapter" / "adapter_model.safetensors")),
    "projector_sha256": sha256(str(ckpt / "projector.pt")),
    "checkpoint_identity_sha256": sha256(str(ckpt / "checkpoint_identity.json")),
    "labels_path": labels,
    "labels_sha256": sha256(labels),
    "characters_path": characters,
    "characters_sha256": sha256(characters),
    "audio_root": audio_root,
    "split": "test",
    "usage": "ood_test_only",
}
Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

  echo "0" > "$tmp_dir/return_code.txt"
  mv "$tmp_dir" "$FINAL_OOD_DIR"
  echo "Completed: $FINAL_OOD_DIR"
  print_metric_file "full R2 MIR-1K OOD" "$FINAL_OOD_DIR/metrics.json"
}

summarize() {
  local out="$RUN_ROOT/20260723_qwen_fa_r2_final_summary.json"
  "$PYTHON_BIN" - \
    "$FULL_RUN" "$SEALED_TEST_DIR" "$FINAL_OOD_DIR" "$PILOT_OOD_DIR" "$out" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

full_run, sealed_dir, final_ood_dir, pilot_ood_dir, output = map(Path, sys.argv[1:])

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

def metrics(path: Path):
    data = load(path)
    return None if data is None else data.get("metric", data)

summary = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "full_run": str(full_run),
    "program_best_checkpoint": load(full_run / "best_checkpoint.json"),
    "full_validation_final": metrics(full_run / "evaluation.json"),
    "m4singer_sealed_test": metrics(sealed_dir / "metrics.json"),
    "m4singer_sealed_test_identity": load(sealed_dir / "evaluation_identity.json"),
    "mir1k_full_r2_ood": metrics(final_ood_dir / "metrics.json"),
    "mir1k_full_r2_ood_identity": load(final_ood_dir / "evaluation_identity.json"),
    "mir1k_pilot_ood_historical": metrics(pilot_ood_dir / "metrics.json"),
    "status": {
        "m4singer_sealed_test_complete": (sealed_dir / "metrics.json").is_file(),
        "m4singer_sealed_test_checkpoint_identity_recorded": (sealed_dir / "evaluation_identity.json").is_file(),
        "mir1k_full_r2_ood_complete": (final_ood_dir / "metrics.json").is_file(),
    },
}

tmp = output.with_suffix(output.suffix + ".tmp")
tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(output)
print(json.dumps(summary, ensure_ascii=False, indent=2))
print(f"\nSummary written to: {output}")
PY
}

case "$MODE" in
  inspect)
    inspect_state
    ;;
  run-ood)
    run_ood
    ;;
  summarize)
    summarize
    ;;
  *)
    fail "unknown mode '$MODE'; use inspect, run-ood, or summarize"
    ;;
esac
