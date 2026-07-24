#!/usr/bin/env bash
# Collect the missing Qwen Forced Aligner follow-up evidence without modifying runs.
#
# Outputs:
#   1) lightweight evidence archive: identities, metrics, commands, code/config
#      snapshots, checkpoint hashes, environment and pipeline completion evidence.
#   2) optional metric-recompute archive: existing predictions plus the exact
#      filtered labels/references selected by each evaluator.
#
# This script NEVER copies checkpoint bodies, model caches, audio, or trainer
# states. It hashes selected best/terminal checkpoint artifacts in place.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
DATA_ROOT="${DATA_ROOT:-/home/hyan/Data/lyricalign}"
RUN_ROOT="${RUN_ROOT:-$DATA_ROOT/runs}"
DERIVED_ROOT="${DERIVED_ROOT:-$DATA_ROOT/derived}"
LOG_ROOT="${LOG_ROOT:-$DATA_ROOT/logs}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python || true)}"
SECOND_SEED="${SECOND_SEED:-20260724}"
BUILD_RECOMPUTE_PACK="${BUILD_RECOMPUTE_PACK:-1}"
HASH_TRAINER_STATE="${HASH_TRAINER_STATE:-0}"
STRICT="${STRICT:-0}"
STAMP="${STAMP:-$(date +%Y%m%d_%H%M%S)}"
OUT_PARENT="${OUT_PARENT:-$DATA_ROOT/evidence}"
OUT_ROOT="$OUT_PARENT/qwen_fa_followup_supplement_${STAMP}"
LIGHT="$OUT_ROOT/lightweight"
RECOMPUTE="$OUT_ROOT/metric_recompute_inputs"
STATUS_TSV="$LIGHT/path_status.tsv"

SEED2_RUN="${SEED2_RUN:-$RUN_ROOT/20260724_qwen_fa_r2_full_seed${SECOND_SEED}}"
FINAL_OOD_RUN="${FINAL_OOD_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_mir1k_ood}"
STATE_ROOT="${STATE_ROOT:-$RUN_ROOT/20260724_qwen_fa_followup_overnight}"
FULL_R1_RUN="${FULL_R1_RUN:-$RUN_ROOT/20260724_qwen_fa_r1_full_seed3407}"
FULL_R2_RUN="${FULL_R2_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
FULL_R2_TEST="${FULL_R2_TEST:-$RUN_ROOT/20260723_qwen_fa_r2_full_m4singer_sealed_test}"

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: no usable Python interpreter; set PYTHON_BIN explicitly" >&2
  exit 2
fi

mkdir -p "$LIGHT" "$RECOMPUTE"
printf 'required\tstatus\tsource\tdestination\n' > "$STATUS_TSV"

note_status() {
  local required="$1" status="$2" source="$3" destination="$4"
  printf '%s\t%s\t%s\t%s\n' "$required" "$status" "$source" "$destination" >> "$STATUS_TSV"
}

copy_file() {
  local source="$1" destination="$2" required="${3:-optional}"
  mkdir -p "$(dirname "$destination")"
  if [[ -f "$source" ]]; then
    cp -a "$source" "$destination"
    note_status "$required" present "$source" "$destination"
  else
    note_status "$required" missing "$source" "$destination"
  fi
}

copy_glob() {
  local source_dir="$1" pattern="$2" destination_dir="$3"
  mkdir -p "$destination_dir"
  local found=0 path
  shopt -s nullglob
  for path in "$source_dir"/$pattern; do
    [[ -f "$path" ]] || continue
    cp -a "$path" "$destination_dir/"
    note_status optional present "$path" "$destination_dir/$(basename "$path")"
    found=1
  done
  shopt -u nullglob
  if [[ "$found" -eq 0 ]]; then
    note_status optional missing "$source_dir/$pattern" "$destination_dir/"
  fi
}

tail_file() {
  local source="$1" destination="$2" lines="${3:-5000}"
  mkdir -p "$(dirname "$destination")"
  if [[ -f "$source" ]]; then
    tail -n "$lines" "$source" > "$destination"
    note_status optional present_tail "$source" "$destination"
  else
    note_status optional missing "$source" "$destination"
  fi
}

capture_command() {
  local destination="$1"; shift
  mkdir -p "$(dirname "$destination")"
  {
    printf '$'
    printf ' %q' "$@"
    printf '\n\n'
    "$@"
  } > "$destination" 2>&1 || true
}

copy_project_rel() {
  local rel="$1" required="${2:-optional}"
  copy_file "$PROJECT/$rel" "$LIGHT/code_snapshot/$rel" "$required"
}

write_readme() {
  cat > "$LIGHT/README.md" <<EOF
# Qwen FA follow-up supplement

Collected at: $(date -Is)

This package is read-only evidence collection for the 2026-07-24 handoff.
It does not modify metrics, rerun training/evaluation, or copy audio/checkpoint bodies.

Primary sources:

- full R2 seed2: \`$SEED2_RUN\`
- final R2 MIR-1K OOD: \`$FINAL_OOD_RUN\`
- follow-up pipeline state: \`$STATE_ROOT\`

Check \`path_status.tsv\` and \`collection_summary.json\` for missing items.
\`checkpoint_inventory.json\` records best/terminal checkpoint identity and hashes.
\`evaluation_step_resolution.json\` checks which periodic validation file is byte/JSON-equivalent to \`evaluation.json\`.

The separate metric-recompute archive, when generated, contains existing prediction JSONL files and exact filtered references. It still excludes audio and model weights.
EOF
}

write_readme

# ---------------------------------------------------------------------------
# 1. Environment, Git state, and exact source/config snapshots.
# ---------------------------------------------------------------------------
mkdir -p "$LIGHT/environment" "$LIGHT/git" "$LIGHT/code_snapshot"
{
  echo "collected_at=$(date -Is)"
  echo "hostname=$(hostname 2>/dev/null || true)"
  echo "user=$(id -un 2>/dev/null || true)"
  echo "project=$PROJECT"
  echo "data_root=$DATA_ROOT"
  echo "run_root=$RUN_ROOT"
  echo "derived_root=$DERIVED_ROOT"
  echo "python_bin=$PYTHON_BIN"
  echo "seed2_run=$SEED2_RUN"
  echo "final_ood_run=$FINAL_OOD_RUN"
  echo "state_root=$STATE_ROOT"
} > "$LIGHT/environment/paths.txt"

capture_command "$LIGHT/environment/uname.txt" uname -a
capture_command "$LIGHT/environment/python_version.txt" "$PYTHON_BIN" --version
capture_command "$LIGHT/environment/df.txt" df -h "$DATA_ROOT"
capture_command "$LIGHT/environment/ulimit.txt" bash -lc 'ulimit -a'
if command -v nvidia-smi >/dev/null 2>&1; then
  capture_command "$LIGHT/environment/nvidia_smi.txt" nvidia-smi
  capture_command "$LIGHT/environment/nvidia_query.csv" nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv
fi
if command -v conda >/dev/null 2>&1; then
  capture_command "$LIGHT/environment/conda_info.txt" conda info
  capture_command "$LIGHT/environment/conda_list_explicit.txt" conda list --explicit
fi
capture_command "$LIGHT/environment/pip_freeze.txt" "$PYTHON_BIN" -m pip freeze

if git -C "$PROJECT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  capture_command "$LIGHT/git/head.txt" git -C "$PROJECT" rev-parse HEAD
  capture_command "$LIGHT/git/branch.txt" git -C "$PROJECT" branch --show-current
  capture_command "$LIGHT/git/status.txt" git -C "$PROJECT" status --short --branch
  capture_command "$LIGHT/git/remotes.txt" git -C "$PROJECT" remote -v
  capture_command "$LIGHT/git/diff_stat.txt" git -C "$PROJECT" diff --stat
  capture_command "$LIGHT/git/recent_log.txt" git -C "$PROJECT" log -n 12 --date=iso-strict --pretty=fuller
else
  echo "not_a_git_worktree=$PROJECT" > "$LIGHT/git/status.txt"
fi

for rel in \
  src/lyricalign/metrics/character.py \
  src/lyricalign/training/qwen_fa_model.py \
  src/lyricalign/training/qwen_fa_runtime.py \
  scripts/training/run_qwen_fa_lora.py \
  scripts/training/evaluate_qwen_fa_checkpoint.py \
  scripts/training/run_qwen_fa_followup_overnight.sh \
  scripts/training/launch_qwen_fa_followup_detached.sh \
  scripts/training/run_full_r2_mir1k_ood_fixed_once.sh \
  scripts/training/finalize_qwen_fa_r2_manual.sh \
  scripts/evaluation/summarize_long_qwen_fa.py \
  configs/training/qwen_fa_lora_full_r1_v1.yaml \
  configs/training/qwen_fa_lora_full_r2_v1.yaml \
  configs/training/qwen_fa_lora_full_r2_seed2_v1.yaml; do
  copy_project_rel "$rel" required
done

# ---------------------------------------------------------------------------
# 2. Full seed2 lightweight run evidence.
# ---------------------------------------------------------------------------
SEED2_DST="$LIGHT/runs/$(basename "$SEED2_RUN")"
for name in \
  config.yaml command.sh commands.log runtime_summary.json evaluation.json \
  training_evaluation.json best_checkpoint.json model_identity.json \
  execution_identity.json source_manifest_identity.json split_manifest_identity.json \
  lora_target_modules.json trainable_parameter_summary.json metrics.jsonl; do
  case "$name" in
    runtime_summary.json|evaluation.json|best_checkpoint.json|model_identity.json|execution_identity.json|source_manifest_identity.json|split_manifest_identity.json|lora_target_modules.json|trainable_parameter_summary.json)
      req=required ;;
    *) req=optional ;;
  esac
  copy_file "$SEED2_RUN/$name" "$SEED2_DST/$name" "$req"
done
copy_glob "$SEED2_RUN" 'validation_step_*.json' "$SEED2_DST/periodic_validation"

"$PYTHON_BIN" - "$SEED2_RUN" "$SEED2_DST" "$HASH_TRAINER_STATE" <<'PY'
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

run = Path(sys.argv[1])
out = Path(sys.argv[2])
hash_trainer = sys.argv[3] == "1"
out.mkdir(parents=True, exist_ok=True)

def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

runtime = load(run / "runtime_summary.json") or {}
best = load(run / "best_checkpoint.json") or {}
terminal_step = runtime.get("steps")
best_path = Path(best["checkpoint"]) if best.get("checkpoint") else None
terminal_path = run / "checkpoints" / f"step-{int(terminal_step):06d}" if terminal_step is not None else None

checkpoints = []
for path in sorted((run / "checkpoints").glob("step-*")) if (run / "checkpoints").is_dir() else []:
    if not path.is_dir():
        continue
    m = re.fullmatch(r"step-(\d+)", path.name)
    step = int(m.group(1)) if m else None
    checkpoints.append({
        "step": step,
        "path": str(path),
        "is_best": bool(best_path and path.resolve() == best_path.resolve()),
        "is_terminal": bool(terminal_path and path.resolve() == terminal_path.resolve()),
    })

selected = []
for role, path in (("best", best_path), ("terminal", terminal_path)):
    if path is None:
        selected.append({"role": role, "path": None, "exists": False})
        continue
    row = {"role": role, "path": str(path), "exists": path.is_dir(), "artifacts": {}}
    for rel in (
        "checkpoint_identity.json",
        "adapter/adapter_config.json",
        "adapter/adapter_model.safetensors",
        "projector.pt",
        "trainer_state.pt",
    ):
        p = path / rel
        info = {"path": str(p), "exists": p.is_file()}
        if p.is_file():
            info["size_bytes"] = p.stat().st_size
            if rel != "trainer_state.pt" or hash_trainer:
                info["sha256"] = sha(p)
        row["artifacts"][rel] = info
    selected.append(row)
    if path.is_dir():
        target = out / "checkpoint_metadata" / role
        target.mkdir(parents=True, exist_ok=True)
        for rel in ("checkpoint_identity.json", "adapter/adapter_config.json"):
            src = path / rel
            if src.is_file():
                dst = target / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

inventory = {
    "schema_version": 1,
    "run": str(run),
    "runtime_summary": runtime,
    "best_checkpoint": best,
    "checkpoint_directories": checkpoints,
    "selected_checkpoint_artifacts": selected,
    "trainer_state_hashed": hash_trainer,
}
(out / "checkpoint_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Resolve whether evaluation.json is identical to a periodic validation record.
evaluation = load(run / "evaluation.json")
matches = []
for p in sorted(run.glob("validation_step_*.json")):
    candidate = load(p)
    if evaluation is not None and candidate == evaluation:
        m = re.search(r"(\d+)", p.stem)
        matches.append({"path": str(p), "step": int(m.group(1)) if m else None})
resolution = {
    "schema_version": 1,
    "run": str(run),
    "runtime_completed_step": terminal_step,
    "best_checkpoint_step": best.get("step"),
    "evaluation_json_present": (run / "evaluation.json").is_file(),
    "matching_periodic_validations": matches,
    "interpretation": (
        "evaluation.json exactly matches the listed periodic validation file(s)"
        if matches else
        "evaluation.json does not exactly match any retained periodic validation file, or required files are missing"
    ),
}
(out / "evaluation_step_resolution.json").write_text(json.dumps(resolution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

# Hash frozen inputs referenced by the run config without copying audio.
"$PYTHON_BIN" - "$SEED2_RUN/config.yaml" "$LIGHT/frozen_input_identity.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

try:
    import yaml
except Exception as exc:
    Path(sys.argv[2]).write_text(json.dumps({"error": f"PyYAML unavailable: {exc}"}, indent=2) + "\n")
    raise SystemExit(0)

config_path = Path(sys.argv[1])
out = Path(sys.argv[2])

def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def file_record(value):
    p = Path(value)
    row = {"path": str(p), "exists": p.is_file()}
    if p.is_file():
        row.update({"size_bytes": p.stat().st_size, "sha256": sha(p)})
        if p.suffix in {".jsonl", ".csv", ".txt"}:
            with p.open("rb") as f:
                row["line_count"] = sum(1 for _ in f)
    return row

if not config_path.is_file():
    out.write_text(json.dumps({"config_path": str(config_path), "exists": False}, indent=2) + "\n")
    raise SystemExit(0)

cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
data = cfg.get("data", {})
result = {
    "schema_version": 1,
    "config": file_record(config_path),
    "labels": file_record(data.get("labels", "")),
    "split_manifest": file_record(data.get("split_manifest", "")),
    "characters": file_record(data.get("characters", "")),
    "audio_root": {
        "path": str(data.get("audio_root", "")),
        "exists": Path(data.get("audio_root", "")).is_dir() if data.get("audio_root") else False,
        "copied": False,
    },
    "model": cfg.get("model"),
    "training": cfg.get("training"),
    "stages": cfg.get("stages"),
}
out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

# ---------------------------------------------------------------------------
# 3. Final full-R2 MIR-1K OOD evidence.
# ---------------------------------------------------------------------------
OOD_DST="$LIGHT/runs/$(basename "$FINAL_OOD_RUN")"
for name in metrics.json evaluation_identity.json return_code.txt command.sh command.txt stdout.log stderr.log long_summary.json; do
  case "$name" in
    metrics.json|evaluation_identity.json|return_code.txt) req=required ;;
    *) req=optional ;;
  esac
  if [[ "$name" == "stdout.log" || "$name" == "stderr.log" ]]; then
    tail_file "$FINAL_OOD_RUN/$name" "$OOD_DST/${name%.log}.tail.log" 5000
  else
    copy_file "$FINAL_OOD_RUN/$name" "$OOD_DST/$name" "$req"
  fi
done

# Record prediction identity even when the prediction body is kept separate.
"$PYTHON_BIN" - "$FINAL_OOD_RUN/predictions.jsonl" "$OOD_DST/predictions_identity.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
p, out = Path(sys.argv[1]), Path(sys.argv[2])
row = {"path": str(p), "exists": p.is_file(), "copied_to_lightweight": False}
if p.is_file():
    h = hashlib.sha256()
    with p.open("rb") as f:
        lines = 0
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
        with p.open("rb") as f2:
            lines = sum(1 for _ in f2)
    row.update({"size_bytes": p.stat().st_size, "line_count": lines, "sha256": h.hexdigest()})
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
PY

# ---------------------------------------------------------------------------
# 4. Pipeline completion and detached launcher evidence.
# ---------------------------------------------------------------------------
PIPE_DST="$LIGHT/pipeline"
for name in pipeline_events.jsonl final_summary.json seed2_decision.json pipeline.complete smoke.complete; do
  req=optional
  [[ "$name" == "pipeline_events.jsonl" || "$name" == "final_summary.json" ]] && req=required
  copy_file "$STATE_ROOT/$name" "$PIPE_DST/$name" "$req"
done
mkdir -p "$PIPE_DST/state_logs"
shopt -s nullglob
for state_log in "$STATE_ROOT"/*.log; do
  tail_file "$state_log" "$PIPE_DST/state_logs/$(basename "$state_log").tail" 10000
done
shopt -u nullglob

for pointer in \
  "$LOG_ROOT/qwen_fa_followup_latest.pid" \
  "$LOG_ROOT/qwen_fa_followup_latest.log" \
  "$LOG_ROOT/qwen_fa_followup_latest.rc" \
  "$LOG_ROOT/qwen_fa_followup_latest.launcher"; do
  copy_file "$pointer" "$PIPE_DST/launcher_pointers/$(basename "$pointer")" optional
done

# Resolve and collect the latest detached launch artifacts referenced by pointers.
"$PYTHON_BIN" - "$LOG_ROOT/qwen_fa_followup_latest" "$PIPE_DST/launcher_resolved.json" <<'PY'
import json, sys
from pathlib import Path
base, out = Path(sys.argv[1]), Path(sys.argv[2])
result = {}
for suffix in ("pid", "log", "rc", "launcher"):
    p = Path(str(base) + "." + suffix)
    value = p.read_text(encoding="utf-8").strip() if p.is_file() else None
    result[suffix] = {"pointer": str(p), "value": value, "target_exists": bool(value and Path(value).exists())}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
PY

if [[ -f "$PIPE_DST/launcher_resolved.json" ]]; then
  mapfile -t launcher_targets < <("$PYTHON_BIN" - "$PIPE_DST/launcher_resolved.json" <<'PY'
import json, sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text())
for key in ("rc", "launcher", "log"):
    value=data.get(key,{}).get("value")
    if value:
        print(f"{key}\t{value}")
PY
)
  if (( ${#launcher_targets[@]} > 0 )); then
    for row in "${launcher_targets[@]}"; do
      key="${row%%$'\t'*}"; path="${row#*$'\t'}"
      if [[ "$key" == "log" ]]; then
        tail_file "$path" "$PIPE_DST/detached/latest.log.tail" 10000
      else
        copy_file "$path" "$PIPE_DST/detached/$(basename "$path")" optional
      fi
    done
  fi
fi

tail_file "$DATA_ROOT/finalize_r2_ood_launcher.log" "$PIPE_DST/finalize_r2_ood_launcher.tail.log" 10000
copy_file "$DATA_ROOT/finalize_r2_ood_launcher.return_code" "$PIPE_DST/finalize_r2_ood_launcher.return_code" optional

# ---------------------------------------------------------------------------
# 5. Inventory all relevant evaluation predictions and optionally build a
#    self-contained metric-recompute input bundle.
# ---------------------------------------------------------------------------
"$PYTHON_BIN" - "$RUN_ROOT" "$LIGHT/evaluation_prediction_inventory.json" "$RECOMPUTE" "$BUILD_RECOMPUTE_PACK" <<'PY'
import hashlib
import json
import shutil
import sys
from pathlib import Path

run_root = Path(sys.argv[1])
inventory_out = Path(sys.argv[2])
recompute_root = Path(sys.argv[3])
build_recompute = sys.argv[4] == "1"

def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def read_jsonl(path: Path):
    rows=[]
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

def selected_eval_dirs():
    names = {
        "20260724_qwen_fa_r0_raw_m4singer_test",
        "20260724_qwen_fa_r0_raw_mir1k_ood",
        "20260724_qwen_fa_r1_full_m4singer_test",
        "20260724_qwen_fa_r1_full_mir1k_ood",
        "20260723_qwen_fa_r2_full_m4singer_sealed_test",
        "20260723_qwen_fa_r2_full_mir1k_ood",
    }
    paths = [run_root / name for name in sorted(names)]
    paths.extend(sorted(run_root.glob("20260724_qwen_fa_long_test_b*_*")))
    # Deduplicate while preserving order.
    seen=set(); result=[]
    for p in paths:
        key=str(p)
        if key not in seen:
            seen.add(key); result.append(p)
    return result

inventory=[]
for run in selected_eval_dirs():
    identity_path = run / "evaluation_identity.json"
    predictions_path = run / "predictions.jsonl"
    metrics_path = run / "metrics.json"
    row = {
        "run": str(run),
        "exists": run.is_dir(),
        "evaluation_identity_exists": identity_path.is_file(),
        "metrics_exists": metrics_path.is_file(),
        "predictions_exists": predictions_path.is_file(),
    }
    if predictions_path.is_file():
        row["predictions"] = {
            "path": str(predictions_path),
            "size_bytes": predictions_path.stat().st_size,
            "line_count": sum(1 for _ in predictions_path.open("rb")),
            "sha256": sha(predictions_path),
        }
    if identity_path.is_file():
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            row["identity"] = identity
        except Exception as exc:
            row["identity_error"] = str(exc)
            identity = None
    else:
        identity = None

    if build_recompute and identity and predictions_path.is_file():
        dst = recompute_root / "evaluations" / run.name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(predictions_path, dst / "predictions.jsonl")
        for src, name in (
            (metrics_path, "metrics.original.json"),
            (identity_path, "evaluation_identity.json"),
            (run / "return_code.txt", "return_code.txt"),
            (run / "command.sh", "command.sh"),
            (run / "command.txt", "command.txt"),
            (run / "long_summary.json", "long_summary.original.json"),
        ):
            if src.is_file():
                shutil.copy2(src, dst / name)

        labels_path = Path(identity.get("labels_path", ""))
        characters_path = Path(identity.get("characters_path", ""))
        split = identity.get("split")
        max_items = int(identity.get("max_items") or 0)
        selection = {
            "labels_path": str(labels_path),
            "characters_path": str(characters_path),
            "split": split,
            "max_items": max_items,
            "labels_source_exists": labels_path.is_file(),
            "characters_source_exists": characters_path.is_file(),
        }
        if labels_path.is_file() and characters_path.is_file():
            labels = read_jsonl(labels_path)
            if split:
                labels = [x for x in labels if x.get("split") == split]
            labels = sorted(labels, key=lambda x: str(x["item_id"]))
            if max_items:
                labels = labels[:max_items]
            item_ids = {str(x["item_id"]) for x in labels}
            characters = [x for x in read_jsonl(characters_path) if str(x.get("item_id")) in item_ids]
            characters = sorted(characters, key=lambda x: (str(x.get("item_id")), int(x.get("character_index", 0))))
            write_jsonl(dst / "labels.filtered.jsonl", labels)
            write_jsonl(dst / "references.filtered.jsonl", characters)
            selection.update({
                "selected_item_count": len(labels),
                "selected_character_count": len(characters),
                "labels_filtered_sha256": sha(dst / "labels.filtered.jsonl"),
                "references_filtered_sha256": sha(dst / "references.filtered.jsonl"),
            })
        (dst / "selection_identity.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        row["recompute_bundle"] = str(dst)
    inventory.append(row)

inventory_out.parent.mkdir(parents=True, exist_ok=True)
inventory_out.write_text(json.dumps({"schema_version": 1, "evaluations": inventory}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if build_recompute:
    recompute_root.mkdir(parents=True, exist_ok=True)
    (recompute_root / "README.md").write_text(
        "# Metric recompute inputs\n\n"
        "Contains existing evaluation predictions and evaluator-exact filtered labels/references.\n"
        "No audio, model cache, checkpoint body, projector, adapter, or trainer state is included.\n"
        "Training-run validation evaluations did not persist predictions and therefore require a validation-only rerun.\n",
        encoding="utf-8",
    )
PY

# ---------------------------------------------------------------------------
# 6. Generate validation-only rerun commands; do not execute them.
# ---------------------------------------------------------------------------
"$PYTHON_BIN" - "$PROJECT" "$RUN_ROOT" "$FULL_R1_RUN" "$FULL_R2_RUN" "$SEED2_RUN" "$LIGHT/recompute_validation_commands.sh" <<'PY'
import json
import shlex
import sys
from pathlib import Path

project, run_root, *rest = map(Path, sys.argv[1:-1])
out = Path(sys.argv[-1])
run_dirs = rest

lines = [
    "#!/usr/bin/env bash",
    "# Generated only; not executed by the collector.",
    "# Re-evaluates validation checkpoints through evaluate_qwen_fa_checkpoint.py",
    "# so corrected metrics can be recomputed from persisted predictions.",
    "set -Eeuo pipefail",
    f"PROJECT={shlex.quote(str(project))}",
    f"RUN_ROOT={shlex.quote(str(run_root))}",
    'PYTHON_BIN="${PYTHON_BIN:-python}"',
    'export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"',
    "",
]

def q(value):
    return shlex.quote(str(value))

def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

for run in run_dirs:
    cfg_path = run / "config.yaml"
    runtime = load_json(run / "runtime_summary.json")
    best = load_json(run / "best_checkpoint.json")
    if not cfg_path.is_file():
        lines.append(f"# SKIP missing config: {q(cfg_path)}")
        continue
    try:
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        lines.append(f"# SKIP cannot parse {q(cfg_path)}: {exc}")
        continue
    model = cfg["model"]["id"]
    revision = cfg["model"]["revision"]
    data = cfg["data"]
    candidates=[]
    if best.get("checkpoint"):
        candidates.append(("best", Path(best["checkpoint"]), best.get("step")))
    if runtime.get("steps") is not None:
        step=int(runtime["steps"])
        terminal=run / "checkpoints" / f"step-{step:06d}"
        if not any(p == terminal for _,p,_ in candidates):
            candidates.append(("terminal", terminal, step))
    for role, checkpoint, step in candidates:
        out_dir = run_root / f"{run.name}_validation_{role}_recompute"
        lines.extend([
            f"# {run.name}: {role} checkpoint, step={step}",
            f"if [[ -e {q(out_dir)} ]]; then echo 'refusing to overwrite existing output: {out_dir}' >&2; exit 2; fi",
            f"rm -rf {q(str(out_dir) + '.tmp')}",
            f"mkdir -p {q(str(out_dir) + '.tmp')}",
            " ".join([
                '"$PYTHON_BIN"', q(project / "scripts/training/evaluate_qwen_fa_checkpoint.py"),
                "--model", q(model), "--revision", q(revision),
                "--checkpoint-kind", "lora" if (checkpoint / "adapter" / "adapter_config.json").is_file() else "projector",
                "--checkpoint", q(checkpoint),
                "--labels", q(data["labels"]),
                "--characters", q(data["characters"]),
                "--audio-root", q(data["audio_root"]),
                "--out-dir", q(str(out_dir) + ".tmp"),
                "--split", "validation", "--batch-size", "4", "--device", "cuda", "--local-files-only",
                "--evaluation-role", q(f"validation_metric_recompute_{run.name}_{role}"),
            ]),
            f"printf '0\\n' > {q(str(out_dir) + '.tmp/return_code.txt')}",
            f"mv {q(str(out_dir) + '.tmp')} {q(out_dir)}",
            "",
        ])

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
out.chmod(0o755)
PY

# ---------------------------------------------------------------------------
# 7. Produce manifests, summary, and archives.
# ---------------------------------------------------------------------------
"$PYTHON_BIN" - "$LIGHT" "$STATUS_TSV" "$BUILD_RECOMPUTE_PACK" <<'PY'
import csv
import hashlib
import json
import sys
from pathlib import Path
root, status_path = Path(sys.argv[1]), Path(sys.argv[2])
build_recompute = sys.argv[3] == "1"

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

entries=[]
for p in sorted(root.rglob("*")):
    if p.is_file():
        entries.append({"path": p.relative_to(root).as_posix(), "size_bytes": p.stat().st_size, "sha256": sha(p)})
missing_required=[]
with status_path.open(encoding="utf-8") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        if row["required"] == "required" and row["status"] == "missing":
            missing_required.append(row["source"])
summary={
    "schema_version": 1,
    "lightweight_file_count": len(entries),
    "lightweight_size_bytes": sum(x["size_bytes"] for x in entries),
    "missing_required": missing_required,
    "collection_complete": not missing_required,
    "metric_recompute_pack_requested": build_recompute,
}
(root / "included_file_manifest.json").write_text(json.dumps({"schema_version":1,"entries":entries}, indent=2)+"\n", encoding="utf-8")
(root / "collection_summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
PY

mkdir -p "$OUT_PARENT"
LIGHT_ARCHIVE="$OUT_PARENT/qwen_fa_followup_lightweight_${STAMP}.tar.gz"
RECOMPUTE_ARCHIVE="$OUT_PARENT/qwen_fa_followup_metric_recompute_inputs_${STAMP}.tar.gz"

tar -C "$OUT_ROOT" -czf "$LIGHT_ARCHIVE" lightweight
sha256sum "$LIGHT_ARCHIVE" > "$LIGHT_ARCHIVE.sha256"

if [[ "$BUILD_RECOMPUTE_PACK" == "1" && -d "$RECOMPUTE/evaluations" ]]; then
  "$PYTHON_BIN" - "$RECOMPUTE" <<'PY'
import hashlib, json, sys
from pathlib import Path
root=Path(sys.argv[1])
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024), b''): h.update(c)
    return h.hexdigest()
entries=[]
for p in sorted(root.rglob('*')):
    if p.is_file(): entries.append({'path':p.relative_to(root).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha(p)})
(root/'included_file_manifest.json').write_text(json.dumps({'schema_version':1,'entries':entries},indent=2)+'\n')
PY
  tar -C "$OUT_ROOT" -czf "$RECOMPUTE_ARCHIVE" metric_recompute_inputs
  sha256sum "$RECOMPUTE_ARCHIVE" > "$RECOMPUTE_ARCHIVE.sha256"
fi

cat <<EOF
Collection finished.

Lightweight archive:
  $LIGHT_ARCHIVE
  $(du -h "$LIGHT_ARCHIVE" | awk '{print $1}')
  SHA256: $(cut -d' ' -f1 "$LIGHT_ARCHIVE.sha256")
EOF

if [[ -f "$RECOMPUTE_ARCHIVE" ]]; then
  cat <<EOF

Metric-recompute input archive:
  $RECOMPUTE_ARCHIVE
  $(du -h "$RECOMPUTE_ARCHIVE" | awk '{print $1}')
  SHA256: $(cut -d' ' -f1 "$RECOMPUTE_ARCHIVE.sha256")
EOF
fi

SUMMARY_JSON="$LIGHT/collection_summary.json"
if [[ -f "$SUMMARY_JSON" ]]; then
  cat "$SUMMARY_JSON"
fi

if [[ "$STRICT" == "1" ]]; then
  "$PYTHON_BIN" - "$SUMMARY_JSON" <<'PY'
import json,sys
from pathlib import Path
s=json.loads(Path(sys.argv[1]).read_text())
raise SystemExit(0 if s.get('collection_complete') else 3)
PY
fi
