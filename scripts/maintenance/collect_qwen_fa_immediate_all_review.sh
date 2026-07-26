#!/usr/bin/env bash
# Package the complete immediate diagnostic evidence while excluding every staged
# file larger than 500 KiB (512000 bytes) and all derived audio.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
ROOT="${ROOT:-/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_all}"
EXPORT_ROOT="${EXPORT_ROOT:-/home/hyan/Data/lyricalign/exports}"
PYTHON_BIN="${PYTHON_BIN:-python}"
MAX_BYTES="${MAX_BYTES:-512000}"
STAMP="$(date +%Y%m%d_%H%M%S)"
NAME="qwen_fa_immediate_all_review_${STAMP}"
STAGE="$EXPORT_ROOT/$NAME"
ARCHIVE="$EXPORT_ROOT/${NAME}.tar.gz"

[[ -d "$ROOT" ]] || { echo "missing result root: $ROOT" >&2; exit 1; }
[[ -f "$ROOT/pipeline.complete" ]] || { echo "pipeline.complete missing: $ROOT" >&2; exit 1; }
rm -rf "$STAGE"
mkdir -p "$STAGE/results" "$STAGE/project_snapshot" "$STAGE/metadata"

ROOT="$ROOT" STAGE="$STAGE" MAX_BYTES="$MAX_BYTES" "$PYTHON_BIN" - <<'PY'
from __future__ import annotations
import gzip, hashlib, json, os, shutil
from pathlib import Path

root=Path(os.environ['ROOT']).resolve()
stage=Path(os.environ['STAGE']).resolve()
limit=int(os.environ['MAX_BYTES'])
results=stage/'results'
all_rows=['relative_path\tsize_bytes\tsha256\tstatus']
excluded=['relative_path\tsize_bytes\tsha256\treason']


def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def compact_jsonl(src: Path, dst: Path) -> None:
    rows=[]
    with src.open(encoding='utf-8') as f:
        for line_no,line in enumerate(f,1):
            if not line.strip(): continue
            row=json.loads(line)
            row['_source_line']=line_no
            rows.append(row)
    def number(row,key,default=0.0):
        try: return float(row.get(key,default))
        except (TypeError,ValueError): return default
    chosen={}
    def add(seq,count):
        for row in seq[:count]:
            key=(str(row.get('model_name')),str(row.get('experiment')),str(row.get('variant_item_id')),int(row.get('character_index',-1)))
            chosen[key]=row
    add(sorted(rows,key=lambda r:max(number(r,'fixed_start_abs_error_sec'),number(r,'fixed_end_abs_error_sec')),reverse=True),80)
    add(sorted(rows,key=lambda r:max(number(r,'raw_start_abs_error_sec'),number(r,'raw_end_abs_error_sec')),reverse=True),80)
    add(sorted(rows,key=lambda r:max(number(r,'raw_start_entropy'),number(r,'raw_end_entropy')),reverse=True),50)
    add(sorted(rows,key=lambda r:min(number(r,'raw_start_margin',1e9),number(r,'raw_end_margin',1e9))),50)
    add(sorted(rows,key=lambda r:max(abs(number(r,'raw_start_signed_class_error')),abs(number(r,'raw_end_signed_class_error'))),reverse=True),80)
    # Preserve time coverage across every 30-second bucket.
    buckets={}
    for row in rows:
        midpoint=(number(row,'gt_global_start_sec')+number(row,'gt_global_end_sec'))/2
        bucket=int(midpoint//30)
        buckets.setdefault(bucket,[]).append(row)
    for bucket_rows in buckets.values():
        add(sorted(bucket_rows,key=lambda r:max(number(r,'fixed_start_abs_error_sec'),number(r,'fixed_end_abs_error_sec')),reverse=True),20)
    ordered=sorted(chosen.values(),key=lambda r:(str(r.get('variant_item_id')),int(r.get('character_index',-1))))
    dst.parent.mkdir(parents=True,exist_ok=True)
    max_output=480*1024
    written=0
    with dst.open('wb') as f:
        for row in ordered:
            payload=(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode()
            if written+len(payload)>max_output: break
            f.write(payload); written+=len(payload)
    meta={'source':str(src),'source_size_bytes':src.stat().st_size,'source_row_count':len(rows),'candidate_count':len(ordered),'written_size_bytes':written}
    dst.with_suffix('.meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

for src in sorted(root.rglob('*')):
    if not src.is_file(): continue
    rel=src.relative_to(root)
    if 'derived_audio' in rel.parts or src.suffix.lower() in {'.wav','.flac','.mp3','.m4a'}:
        excluded.append(f"{rel}\t{src.stat().st_size}\t{digest(src)}\tderived_audio")
        continue
    size=src.stat().st_size
    sha=digest(src)
    if size<=limit:
        dst=results/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        all_rows.append(f"{rel}\t{size}\t{sha}\tcopied")
        continue
    if src.suffix=='.jsonl':
        gz=results/rel.with_suffix(rel.suffix+'.gz'); gz.parent.mkdir(parents=True,exist_ok=True)
        with src.open('rb') as inp, gzip.open(gz,'wb',compresslevel=9) as out:
            shutil.copyfileobj(inp,out)
        if gz.stat().st_size<=limit:
            all_rows.append(f"{rel}\t{size}\t{sha}\tgzip:{gz.relative_to(results)}")
            continue
        gz.unlink()
        compact=results/rel.parent/(rel.stem+'.review.jsonl')
        compact_jsonl(src,compact)
        all_rows.append(f"{rel}\t{size}\t{sha}\tcompact:{compact.relative_to(results)}")
        continue
    excluded.append(f"{rel}\t{size}\t{sha}\tover_500KiB")

(stage/'metadata'/'all_result_files.tsv').write_text('\n'.join(all_rows)+'\n',encoding='utf-8')
(stage/'metadata'/'excluded_files.tsv').write_text('\n'.join(excluded)+'\n',encoding='utf-8')
PY

FILES=(
  scripts/evaluation/analyze_qwen_fa_time_coverage.py
  scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py
  scripts/evaluation/collect_qwen_fa_immediate_suite.py
  scripts/evaluation/summarize_qwen_fa_immediate_diagnostics.py
  scripts/evaluation/prepare_qwen_fa_immediate_all_selection.py
  scripts/evaluation/collect_qwen_fa_240_cliff_probe.py
  scripts/evaluation/summarize_qwen_fa_240_cliff_probe.py
  scripts/evaluation/collect_qwen_fa_repeat_probe.py
  scripts/evaluation/analyze_qwen_fa_error_blocks.py
  scripts/evaluation/summarize_qwen_fa_immediate_all.py
  scripts/training/run_qwen_fa_immediate_all.sh
  scripts/training/run_qwen_fa_240_cliff_probe.sh
  scripts/maintenance/collect_qwen_fa_immediate_all_review.sh
  tests/test_qwen_fa_immediate_diagnostics.py
  tests/test_qwen_fa_240_cliff_probe.py
  tests/test_qwen_fa_immediate_all.py
  docs/sessions/20260725_qwen_fa_immediate_all_plan.md
)
for rel in "${FILES[@]}"; do
  src="$PROJECT/$rel"
  [[ -f "$src" ]] || { printf '%s\n' "$rel" >> "$STAGE/metadata/missing_project_files.txt"; continue; }
  size="$(stat -c '%s' "$src")"
  if (( size > MAX_BYTES )); then
    printf '%s\t%s\t%s\n' "$rel" "$size" "$(sha256sum "$src"|awk '{print $1}')" >> "$STAGE/metadata/excluded_project_files.tsv"
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
  echo '===== git HEAD ====='
  git -C "$PROJECT" rev-parse HEAD 2>&1 || true
  echo
  echo '===== git status --short ====='
  git -C "$PROJECT" status --short 2>&1 || true
  echo
  echo '===== git diff --stat ====='
  git -C "$PROJECT" diff --stat 2>&1 || true
} > "$STAGE/metadata/project_state.txt"

"$PYTHON_BIN" - <<'PY' > "$STAGE/metadata/python_environment.txt" 2>&1
import platform,sys
print('python:',sys.version.replace('\n',' ')); print('platform:',platform.platform())
for name in ('torch','transformers','peft','accelerate','numpy','soundfile'):
    try:
        module=__import__(name); print(name+':',getattr(module,'__version__','unknown'))
    except Exception as exc: print(name+': unavailable',repr(exc))
PY
nvidia-smi > "$STAGE/metadata/nvidia_smi.txt" 2>&1 || true

oversized="$(find "$STAGE" -type f -size +"${MAX_BYTES}"c -print)"
if [[ -n "$oversized" ]]; then
  echo "staged files exceed 500 KiB:" >&2; echo "$oversized" >&2; exit 1
fi
(
  cd "$STAGE"
  find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256
)
mkdir -p "$EXPORT_ROOT"
tar -C "$EXPORT_ROOT" -czf "$ARCHIVE" "$NAME"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
echo "$ARCHIVE"
echo "$ARCHIVE.sha256"
