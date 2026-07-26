#!/usr/bin/env bash
# One-off safe recovery for the full-R2 MIR-1K OOD evaluation.
# It fixes the archive finalizer bug where the raw MIR-1K manifest was passed
# to QwenFABatchCollator instead of a derived Qwen FA label JSONL.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs}"
FULL_RUN="${FULL_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
FINAL_OOD_DIR="${FINAL_OOD_DIR:-$RUN_ROOT/20260723_qwen_fa_r2_full_mir1k_ood}"
MIR1K_ROOT="${MIR1K_ROOT:-/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood}"
MIR1K_MANIFEST="${MIR1K_MANIFEST:-$MIR1K_ROOT/mir1k_vocal_ood_manifest.jsonl}"
MIR1K_CHARACTERS="${MIR1K_CHARACTERS:-$MIR1K_ROOT/mir1k_vocal_ood_characters.jsonl}"
LABEL_DIR="${LABEL_DIR:-/home/hyan/Data/lyricalign/derived/20260724_mir1k_qwen_fa_labels_v1}"
MIR1K_LABELS="${MIR1K_LABELS:-$LABEL_DIR/mir1k_qwen_fa_labels.jsonl}"
LABEL_SUMMARY="${LABEL_SUMMARY:-$LABEL_DIR/label_preparation_summary.json}"
HF_HUB_CACHE="${HF_HUB_CACHE:-/home/hyan/Data/lyricalign/models/hf_cache}"
PYTHON_BIN="${PYTHON_BIN:-python}"

EXPECTED_MANIFEST_SHA256="bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f"
EXPECTED_CHARACTERS_SHA256="78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9"
TIMESTAMP_SEGMENT_SEC="0.08"
NUM_TIMESTAMP_LABELS="5000"

export HF_HUB_CACHE HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

fail() { echo "ERROR: $*" >&2; exit 1; }
require_file() { [ -f "$1" ] || fail "required file missing: $1"; }
require_dir() { [ -d "$1" ] || fail "required directory missing: $1"; }
sha256_file() { sha256sum "$1" | awk '{print $1}'; }

cd "$PROJECT"
require_dir "$FULL_RUN"
require_file "$FULL_RUN/config.yaml"
require_file "$FULL_RUN/best_checkpoint.json"
require_file "$MIR1K_MANIFEST"
require_file "$MIR1K_CHARACTERS"
require_dir "$MIR1K_ROOT/vocal_wavs"
require_file "$PROJECT/scripts/training/prepare_qwen_fa_labels.py"
require_file "$PROJECT/scripts/training/evaluate_qwen_fa_checkpoint.py"

[ "$(sha256_file "$MIR1K_MANIFEST")" = "$EXPECTED_MANIFEST_SHA256" ] || fail "MIR-1K manifest hash mismatch"
[ "$(sha256_file "$MIR1K_CHARACTERS")" = "$EXPECTED_CHARACTERS_SHA256" ] || fail "MIR-1K character hash mismatch"
[ ! -e "$FINAL_OOD_DIR" ] || fail "refusing to overwrite final output: $FINAL_OOD_DIR"

"$PYTHON_BIN" - <<'PY'
import peft, torch, transformers, yaml
print("Python environment check passed")
PY

# Confirm the frozen model's timestamp schema matches the training label schema.
"$PYTHON_BIN" - "$FULL_RUN/config.yaml" "$TIMESTAMP_SEGMENT_SEC" "$NUM_TIMESTAMP_LABELS" <<'PY'
import sys, yaml
from pathlib import Path
from transformers import AutoConfig, AutoProcessor
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_segment = float(sys.argv[2])
expected_labels = int(sys.argv[3])
model_id = cfg["model"]["id"]
revision = cfg["model"]["revision"]
processor = AutoProcessor.from_pretrained(model_id, revision=revision, local_files_only=True)
config = AutoConfig.from_pretrained(model_id, revision=revision, local_files_only=True)
segment = float(processor.timestamp_segment_time) / 1000.0
num_labels = int(config.num_labels)
if abs(segment - expected_segment) > 1e-12:
    raise SystemExit(f"timestamp segment mismatch: model={segment}, expected={expected_segment}")
if num_labels != expected_labels:
    raise SystemExit(f"num_labels mismatch: model={num_labels}, expected={expected_labels}")
print(f"Timestamp schema passed: segment={segment}, num_labels={num_labels}")
PY

# Build deterministic derived labels only when absent. Never overwrite an existing label directory.
if [ ! -f "$MIR1K_LABELS" ] || [ ! -f "$LABEL_SUMMARY" ]; then
  [ ! -e "$LABEL_DIR" ] || fail "label directory exists but is incomplete: $LABEL_DIR"
  tmp_labels="${LABEL_DIR}.tmp.$(date +%Y%m%d_%H%M%S).$$"
  mkdir -p "$tmp_labels"
  "$PYTHON_BIN" scripts/training/prepare_qwen_fa_labels.py \
    --split-manifest "$MIR1K_MANIFEST" \
    --characters "$MIR1K_CHARACTERS" \
    --out-dir "$tmp_labels" \
    --timestamp-segment-sec "$TIMESTAMP_SEGMENT_SEC" \
    --num-labels "$NUM_TIMESTAMP_LABELS"
  # The current generic preparation script has a stale M4Singer-specific filename.
  mv "$tmp_labels/m4singer_qwen_fa_labels.jsonl" "$tmp_labels/mir1k_qwen_fa_labels.jsonl"
  mv "$tmp_labels" "$LABEL_DIR"
fi

require_file "$MIR1K_LABELS"
require_file "$LABEL_SUMMARY"

# Reconstruct labels independently and require exact equality before OOD evaluation.
"$PYTHON_BIN" - \
  "$MIR1K_MANIFEST" "$MIR1K_CHARACTERS" "$MIR1K_LABELS" "$LABEL_SUMMARY" \
  "$EXPECTED_MANIFEST_SHA256" "$EXPECTED_CHARACTERS_SHA256" \
  "$TIMESTAMP_SEGMENT_SEC" "$NUM_TIMESTAMP_LABELS" <<'PY'
import hashlib, json, sys
from collections import defaultdict
from pathlib import Path
from lyricalign.training.qwen_fa_labels import build_label_record

manifest_path, chars_path, labels_path, summary_path = map(Path, sys.argv[1:5])
expected_manifest_hash, expected_chars_hash = sys.argv[5:7]
segment_sec, num_labels = float(sys.argv[7]), int(sys.argv[8])

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

manifest = read_jsonl(manifest_path)
characters = read_jsonl(chars_path)
labels = read_jsonl(labels_path)
summary = json.loads(summary_path.read_text(encoding="utf-8"))

if sha(manifest_path) != expected_manifest_hash or sha(chars_path) != expected_chars_hash:
    raise SystemExit("frozen source hash mismatch")
if summary["source_split_manifest_sha256"] != expected_manifest_hash:
    raise SystemExit("label summary points to a different manifest")
if summary["source_character_annotations_sha256"] != expected_chars_hash:
    raise SystemExit("label summary points to different character annotations")
if summary["output_labels_sha256"] != sha(labels_path):
    raise SystemExit("derived label hash differs from preparation summary")
if len(manifest) != 17 or len(labels) != 17 or len(characters) != 2035:
    raise SystemExit(f"unexpected frozen counts: manifest={len(manifest)}, labels={len(labels)}, chars={len(characters)}")

by_item = defaultdict(list)
for row in characters:
    by_item[str(row["item_id"])].append(row)
expected = [build_label_record(row, by_item[str(row["item_id"])], segment_sec=segment_sec, num_labels=num_labels) for row in manifest]
if expected != labels:
    raise SystemExit("derived labels are not an exact reconstruction from the frozen MIR-1K sources")
if sum(len(row["timestamp_class_ids"]) for row in labels) != 4070:
    raise SystemExit("unexpected timestamp label count")
print(f"Derived labels passed: rows={len(labels)}, characters=2035, timestamp_labels=4070, sha256={sha(labels_path)}")
PY

# Exact one-item collator preflight catches processor/token-count mismatches before loading full weights.
"$PYTHON_BIN" - "$FULL_RUN/config.yaml" "$MIR1K_LABELS" "$MIR1K_ROOT" <<'PY'
import json, sys, yaml
from pathlib import Path
from transformers import AutoConfig, AutoProcessor
from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
row = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()[0])
model_id, revision = cfg["model"]["id"], cfg["model"]["revision"]
processor = AutoProcessor.from_pretrained(model_id, revision=revision, local_files_only=True)
config = AutoConfig.from_pretrained(model_id, revision=revision, local_files_only=True)
inputs, words = QwenFABatchCollator(
    processor,
    audio_root=Path(sys.argv[3]),
    language="Chinese",
    timestamp_token_id=config.timestamp_token_id,
)([row])
active = int((inputs["labels"] != -100).sum().item())
if active != len(row["timestamp_class_ids"]):
    raise SystemExit(f"collator label count mismatch: active={active}, expected={len(row['timestamp_class_ids'])}")
print(f"One-item collator preflight passed: item={row['item_id']}, timestamp_positions={active}, words={len(words[0])}")
PY

readarray -t identity < <("$PYTHON_BIN" - "$FULL_RUN/config.yaml" "$FULL_RUN/best_checkpoint.json" <<'PY'
import json, sys, yaml
from pathlib import Path
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
best = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
print(cfg["model"]["id"])
print(cfg["model"]["revision"])
print(best["checkpoint"])
print(best["step"])
PY
)
MODEL="${identity[0]}"
REVISION="${identity[1]}"
CHECKPOINT="${identity[2]}"
CHECKPOINT_STEP="${identity[3]}"

require_dir "$CHECKPOINT"
require_file "$CHECKPOINT/adapter/adapter_config.json"
require_file "$CHECKPOINT/adapter/adapter_model.safetensors"
require_file "$CHECKPOINT/projector.pt"
require_file "$CHECKPOINT/checkpoint_identity.json"

stamp="$(date +%Y%m%d_%H%M%S)"
tmp_dir="${FINAL_OOD_DIR}.tmp.${stamp}.$$"
mkdir -p "$tmp_dir"

cat > "$tmp_dir/command.sh" <<CMD
cd "$PROJECT"
HF_HUB_CACHE="$HF_HUB_CACHE" HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 \\
$PYTHON_BIN scripts/training/evaluate_qwen_fa_checkpoint.py \\
  --model "$MODEL" \\
  --revision "$REVISION" \\
  --checkpoint "$CHECKPOINT" \\
  --labels "$MIR1K_LABELS" \\
  --characters "$MIR1K_CHARACTERS" \\
  --audio-root "$MIR1K_ROOT" \\
  --out-dir "$tmp_dir" \\
  --split test \\
  --batch-size 4 \\
  --device cuda
CMD

set +e
"$PYTHON_BIN" scripts/training/evaluate_qwen_fa_checkpoint.py \
  --model "$MODEL" \
  --revision "$REVISION" \
  --checkpoint "$CHECKPOINT" \
  --labels "$MIR1K_LABELS" \
  --characters "$MIR1K_CHARACTERS" \
  --audio-root "$MIR1K_ROOT" \
  --out-dir "$tmp_dir" \
  --split test \
  --batch-size 4 \
  --device cuda \
  > >(tee "$tmp_dir/stdout.log") 2> >(tee "$tmp_dir/stderr.log" >&2)
rc=$?
set -e

if [ "$rc" -ne 0 ]; then
  echo "$rc" > "$tmp_dir/return_code.txt"
  fail "OOD evaluation failed; partial evidence retained at $tmp_dir"
fi

require_file "$tmp_dir/metrics.json"
require_file "$tmp_dir/predictions.jsonl"

"$PYTHON_BIN" - \
  "$tmp_dir/evaluation_identity.json" "$MODEL" "$REVISION" "$CHECKPOINT" "$CHECKPOINT_STEP" \
  "$FULL_RUN/best_checkpoint.json" "$MIR1K_MANIFEST" "$MIR1K_LABELS" "$LABEL_SUMMARY" \
  "$MIR1K_CHARACTERS" "$MIR1K_ROOT" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
(
    out_path, model, revision, checkpoint, step, best_json, manifest,
    labels, label_summary, characters, audio_root,
) = sys.argv[1:]

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

ckpt = Path(checkpoint)
data = {
    "schema_version": 2,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "evaluation_role": "final_full_r2_mir1k_ood",
    "selection_split": "M4Singer_validation",
    "selection_metric": "song_macro_boundary_mae_sec",
    "test_or_ood_not_used_for_checkpoint_selection": True,
    "model_id": model,
    "model_revision": revision,
    "hf_hub_offline": True,
    "checkpoint_step": int(step),
    "checkpoint_path": str(ckpt),
    "best_checkpoint_json": best_json,
    "best_checkpoint_json_sha256": sha(best_json),
    "adapter_sha256": sha(ckpt / "adapter" / "adapter_model.safetensors"),
    "projector_sha256": sha(ckpt / "projector.pt"),
    "checkpoint_identity_sha256": sha(ckpt / "checkpoint_identity.json"),
    "source_manifest_path": manifest,
    "source_manifest_sha256": sha(manifest),
    "derived_labels_path": labels,
    "derived_labels_sha256": sha(labels),
    "label_preparation_summary_path": label_summary,
    "label_preparation_summary_sha256": sha(label_summary),
    "characters_path": characters,
    "characters_sha256": sha(characters),
    "timestamp_segment_sec": 0.08,
    "num_timestamp_labels": 5000,
    "audio_root": audio_root,
    "split": "test",
    "usage": "ood_test_only",
}
Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo 0 > "$tmp_dir/return_code.txt"
mv "$tmp_dir" "$FINAL_OOD_DIR"
echo "Completed: $FINAL_OOD_DIR"

# The existing summarize mode is safe once the final directory exists.
bash scripts/training/finalize_qwen_fa_r2_manual.sh summarize
