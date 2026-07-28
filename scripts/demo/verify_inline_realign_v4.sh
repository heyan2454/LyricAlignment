#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=inline_realign_env.sh
source "$SCRIPT_DIR/inline_realign_env.sh"

REPO_ROOT="${REPO_ROOT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
CHECK_INPUTS="${CHECK_INPUTS:-1}"

cd "$REPO_ROOT"

command -v ffmpeg >/dev/null || { echo "ERROR: ffmpeg not found" >&2; exit 2; }
command -v ffprobe >/dev/null || { echo "ERROR: ffprobe not found" >&2; exit 2; }
command -v fc-match >/dev/null || { echo "ERROR: fc-match not found" >&2; exit 2; }
[[ -x "$PYTHON_BIN" ]] || { echo "ERROR: Python not executable: $PYTHON_BIN" >&2; exit 2; }

if [[ "$CHECK_INPUTS" == "1" ]]; then
  validate_inline_realign_inputs
fi

echo "[1/5] Python compile"
"$PYTHON_BIN" -m compileall -q \
  src/lyricalign/demo \
  scripts/demo/run_inline_realign_pipeline.py \
  scripts/demo/run_inline_realign_experiment.py \
  scripts/demo/align_qwen_fa_serial_demo.py \
  scripts/demo/analyze_inline_realign_visuals.py \
  scripts/demo/render_inline_realign_demo_batch.py \
  scripts/demo/summarize_inline_realign_followup.py \
  scripts/demo/collect_inline_realign_evidence.py \
  scripts/demo/watch_inline_realign_status.py

echo "[2/5] Shell syntax"
for script in \
  scripts/demo/inline_realign_env.sh \
  scripts/demo/run_inline_realign_smoke.sh \
  scripts/demo/run_inline_realign_formal.sh \
  scripts/demo/run_inline_realign_render_only.sh \
  scripts/demo/cleanup_inline_realign_overwrite.sh; do
  bash -n "$script"
done

echo "[3/5] Exact Simplified Chinese font face"
PYTHONPATH=src "$PYTHON_BIN" - <<'PY'
import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from lyricalign.demo.media_render import _fontconfig_match, detect_font

requested="Noto Sans CJK SC"
path,index,family,style=_fontconfig_match(requested)
resolved=detect_font(requested)
if family != requested or resolved != requested:
    raise SystemExit(f"SC font mismatch: requested={requested!r}, fontconfig={family!r}, matplotlib={resolved!r}")
# Debian/Ubuntu's standard Noto CJK collection normally uses index 2 for SC.
# Do not hard-code that as a universal requirement, but require that the exact
# face registered by Matplotlib remains SC rather than JP/KR/TC/HK.
prop=font_manager.FontProperties(family=resolved)
matched=font_manager.findfont(prop,fallback_to_default=False)
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    fig,ax=plt.subplots(figsize=(5,1.5))
    ax.text(0.02,0.55,"简体中文：窗口、稳定区、重新对齐",fontfamily=resolved,fontsize=16)
    ax.axis("off")
    out=Path("/tmp/lyricalign_sc_font_verify.png")
    fig.savefig(out,dpi=100)
    plt.close(fig)
font_warnings=[str(w.message) for w in caught if "Glyph" in str(w.message) or "findfont" in str(w.message)]
if font_warnings:
    raise SystemExit("SC font rendered with warnings: "+" | ".join(font_warnings))
print(json.dumps({
    "requested":requested,
    "fontconfig_file":str(path),
    "fontconfig_index":index,
    "fontconfig_family":family,
    "fontconfig_style":style,
    "matplotlib_family":resolved,
    "matplotlib_face":matched,
    "font_warnings":len(font_warnings),
},ensure_ascii=False,indent=2))
PY

echo "[4/5] Focused regression tests"
PYTHONPATH=src "$PYTHON_BIN" -m pytest -q \
  tests/test_inline_realign_v4_full_mechanism.py \
  tests/test_inline_realign_pipeline.py \
  tests/test_inline_realign_patch_20260728.py \
  tests/test_inline_realign_v3_visual_config.py \
  tests/test_decoder_realign_comparison_patch.py \
  tests/test_demo_realign_diagnostics.py

echo "[5/5] Entry help smoke"
"$PYTHON_BIN" scripts/demo/run_inline_realign_pipeline.py --help >/dev/null
"$PYTHON_BIN" scripts/demo/analyze_inline_realign_visuals.py --help >/dev/null
"$PYTHON_BIN" scripts/demo/render_inline_realign_demo_batch.py --help >/dev/null

echo "VERIFY_OK: Inline Realign v4 implementation and exact SC font face are ready."
