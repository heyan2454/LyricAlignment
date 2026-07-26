#!/usr/bin/env bash
# Package the ~240 s cliff probe for review.
# Every staged file is <= 500 KiB (512000 bytes). Derived audio is excluded.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
ROOT="${ROOT:-/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_240_cliff_probe}"
EXPORT_ROOT="${EXPORT_ROOT:-/home/hyan/Data/lyricalign/exports}"
PYTHON_BIN="${PYTHON_BIN:-python}"
MAX_BYTES="${MAX_BYTES:-512000}"
STAMP="$(date +%Y%m%d_%H%M%S)"
NAME="qwen_fa_240_cliff_probe_review_${STAMP}"
STAGE="$EXPORT_ROOT/$NAME"
ARCHIVE="$EXPORT_ROOT/${NAME}.tar.gz"

[[ -d "$ROOT" ]] || { echo "ERROR: missing result root: $ROOT" >&2; exit 1; }
[[ -f "$ROOT/pipeline.complete" ]] || {
  echo "ERROR: pipeline.complete missing; run may be incomplete: $ROOT" >&2
  exit 1
}

rm -rf "$STAGE"
mkdir -p "$STAGE/results" "$STAGE/project_snapshot" "$STAGE/metadata"

ROOT="$ROOT" STAGE="$STAGE" MAX_BYTES="$MAX_BYTES" "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from pathlib import Path

root = Path(os.environ["ROOT"]).resolve()
stage = Path(os.environ["STAGE"]).resolve()
limit = int(os.environ["MAX_BYTES"])
result_dst = stage / "results"
metadata = stage / "metadata"

all_rows = ["relative_path\tsize_bytes\tsha256\taction"]
excluded_rows = ["relative_path\tsize_bytes\tsha256\treason"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def copy(src: Path, rel: Path) -> None:
    dst = result_dst / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


for src in sorted(root.rglob("*")):
    if not src.is_file():
        continue
    rel = src.relative_to(root)
    size = src.stat().st_size
    sha = digest(src)
    if "derived_audio" in rel.parts or src.suffix.lower() in {".wav", ".flac", ".mp3"}:
        excluded_rows.append(f"{rel}\t{size}\t{sha}\tderived_audio")
        all_rows.append(f"{rel}\t{size}\t{sha}\texcluded_derived_audio")
        continue
    if size <= limit:
        copy(src, rel)
        all_rows.append(f"{rel}\t{size}\t{sha}\tcopied")
        continue
    if src.suffix == ".jsonl":
        dst = result_dst / rel.with_suffix(rel.suffix + ".gz")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as source, gzip.open(dst, "wb", compresslevel=9) as target:
            shutil.copyfileobj(source, target)
        if dst.stat().st_size <= limit:
            excluded_rows.append(f"{rel}\t{size}\t{sha}\treplaced_by_exact_gzip")
            all_rows.append(f"{rel}\t{size}\t{sha}\texact_gzip")
            continue
        dst.unlink()
    excluded_rows.append(f"{rel}\t{size}\t{sha}\tover_500KiB")
    all_rows.append(f"{rel}\t{size}\t{sha}\texcluded_over_limit")

(metadata / "all_result_files.tsv").write_text("\n".join(all_rows) + "\n", encoding="utf-8")
(metadata / "excluded_files.tsv").write_text("\n".join(excluded_rows) + "\n", encoding="utf-8")

# Always create compact, review-oriented rows.  These duplicate only the fields
# needed to diagnose the cliff, but retain every character row when possible.
keep = (
    "model_name",
    "probe_condition",
    "variant_kind",
    "segment_role",
    "reference_source_item_id",
    "character_index",
    "source_character_index",
    "normalized_character",
    "gt_start_class",
    "gt_end_class",
    "raw_start_class",
    "raw_end_class",
    "raw_start_signed_class_error",
    "raw_end_signed_class_error",
    "gt_start_class_probability",
    "gt_end_class_probability",
    "raw_start_top1_probability",
    "raw_end_top1_probability",
    "raw_start_top2_class",
    "raw_end_top2_class",
    "raw_start_margin",
    "raw_end_margin",
    "raw_start_entropy",
    "raw_end_entropy",
    "gt_start_sec",
    "gt_end_sec",
    "raw_start_sec",
    "raw_end_sec",
    "fixed_start_sec",
    "fixed_end_sec",
    "raw_start_abs_error_sec",
    "raw_end_abs_error_sec",
    "fixed_start_abs_error_sec",
    "fixed_end_abs_error_sec",
    "start_repaired",
    "end_repaired",
)
for src in sorted(root.glob("*/diagnostic_rows.jsonl")):
    model = src.parent.name
    dst = result_dst / model / "diagnostic_rows.compact.jsonl.gz"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8") as handle, gzip.open(dst, "wt", encoding="utf-8", compresslevel=9) as out:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            compact = {key: row.get(key) for key in keep if key in row}
            out.write(json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n")
    if dst.stat().st_size > limit:
        raise SystemExit(f"compact diagnostic file still exceeds 500 KiB: {dst}")
PY

FILES=(
  "scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py"
  "scripts/evaluation/collect_qwen_fa_240_cliff_probe.py"
  "scripts/evaluation/summarize_qwen_fa_240_cliff_probe.py"
  "scripts/training/run_qwen_fa_240_cliff_probe.sh"
  "scripts/maintenance/collect_qwen_fa_240_cliff_probe_review.sh"
  "tests/test_qwen_fa_240_cliff_probe.py"
  "docs/sessions/20260725_qwen_fa_240_cliff_probe_plan.md"
)
for rel in "${FILES[@]}"; do
  src="$PROJECT/$rel"
  if [[ ! -f "$src" ]]; then
    printf '%s\n' "$rel" >> "$STAGE/metadata/missing_project_files.txt"
    continue
  fi
  size="$(stat -c '%s' "$src")"
  if (( size > MAX_BYTES )); then
    printf '%s\t%s\t%s\n' "$rel" "$size" "$(sha256sum "$src" | awk '{print $1}')" \
      >> "$STAGE/metadata/excluded_project_files.tsv"
    continue
  fi
  mkdir -p "$STAGE/project_snapshot/$(dirname "$rel")"
  cp -a "$src" "$STAGE/project_snapshot/$rel"
done

{
  echo "collected_at=$(date -Is)"
  echo "project=$PROJECT"
  echo "result_root=$ROOT"
  echo "hostname=$(hostname)"
  echo
  echo "===== git HEAD ====="
  git -C "$PROJECT" rev-parse HEAD 2>&1 || true
  echo
  echo "===== git status --short ====="
  git -C "$PROJECT" status --short 2>&1 || true
  echo
  echo "===== git diff --stat ====="
  git -C "$PROJECT" diff --stat 2>&1 || true
} > "$STAGE/metadata/project_state.txt"

"$PYTHON_BIN" - <<'PY' > "$STAGE/metadata/python_environment.txt" 2>&1
import platform,sys
print("python:", sys.version.replace("\n", " "))
print("platform:", platform.platform())
for name in ("torch", "transformers", "peft", "numpy", "soundfile"):
    try:
        module=__import__(name)
        print(f"{name}:", getattr(module, "__version__", "unknown"))
    except Exception as exc:
        print(f"{name}: unavailable ({exc})")
PY
nvidia-smi > "$STAGE/metadata/nvidia_smi.txt" 2>&1 || true

oversized="$(find "$STAGE" -type f -size +"${MAX_BYTES}"c -print)"
if [[ -n "$oversized" ]]; then
  echo "ERROR: staged files exceed 500 KiB:" >&2
  echo "$oversized" >&2
  exit 1
fi

(
  cd "$STAGE"
  find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256
)
tar -C "$EXPORT_ROOT" -czf "$ARCHIVE" "$NAME"
sha256sum "$ARCHIVE" > "${ARCHIVE}.sha256"

printf 'Created:\n  %s\n  %s\n' "$ARCHIVE" "${ARCHIVE}.sha256"
du -h "$ARCHIVE"
