#!/usr/bin/env bash
# Minimal supplemental / follow-up smoke for the four 补做对照 batches (C-E4/C-E8/C-E9/C-E5E7).
# Acceptance: each batch runs ONE case (one item, the requested phases) and passes
# with zero failures, producing the target phase artifacts.
#
# Usage:
#   bash scripts/research/run_supplemental_smoke.sh            # defaults (v8-backed manifest/baseline/frozen)
#   DEMO_ITEM=... MULTI_ITEM=... SUPP_ROOT=... bash scripts/research/run_supplemental_smoke.sh
#
# Gate: refuses to run while the formal v8 suite process is still on GPU.
set -uo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/research_v6_env.sh"; validate_research_v6_inputs
REPO_ROOT="${REPO_ROOT:-/home/hyan/LyricAlignment}"
V8="${V8_ROOT:-/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal_20260731_e9_lazy_compact_v8_inputcache_e9scope_aggregatefix}"
MANIFEST="${SUPP_MANIFEST:-$V8/manifest/active_manifest.jsonl}"
BASELINE="${SUPP_BASELINE:-/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal_20260731_e9_lazy_compact_v3_gtintervalfix/baseline}"
FROZEN="${SUPP_FROZEN:-$V8/frozen_parameters.json}"
SUPP_ROOT="${SUPP_ROOT:-/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/supplemental_20260801}"
DEMO_ITEM="${DEMO_ITEM:-demo_Chinese_人造卫星_d627f970}"
MULTI_ITEM="${MULTI_ITEM:-m4long_646_水星记}"

# --- gate: wait for formal v8 to be off GPU -------------------------------------------------
if command -v pgrep >/dev/null 2>&1; then
  if pgrep -f "run_alignment_research_suite.py --mode formal" >/dev/null 2>&1; then
    echo "ERROR: formal v8 suite is still running. Refusing to start supplemental smoke (GPU contention)." >&2
    exit 3
  fi
fi

BASE_ARGS=(--manifest "$MANIFEST" --baseline-root "$BASELINE" --frozen-params "$FROZEN"
  --model "$MODEL_SOURCE" --revision "$MODEL_REVISION" --r2-checkpoint "$R2_CHECKPOINT"
  --device "$DEVICE" --mode formal)

PASS=0; FAIL=0
run_suite() { # name out_root extra_args...
  local name="$1"; shift; local out_root="$1"; shift
  rm -rf "$out_root"; mkdir -p "$(dirname "$out_root")"
  echo "=== [$name] suite: $*"
  "$PYTHON_BIN" "$REPO_ROOT/scripts/research/run_alignment_research_suite.py" \
    "${BASE_ARGS[@]}" --out-root "$out_root" --item-id "$ITEM" "$@"
}

check_summary() { # out_root
  local out_root="$1"
  local s="$out_root/research_summary.json"
  [[ -f "$s" ]] || { echo "  FAIL: missing $s"; return 1; }
  "$PYTHON_BIN" - "$s" <<'PY' || return 1
import sys, json
s=json.load(open(sys.argv[1]))
ok = s.get("completed_item_count",0)>=1 and s.get("failed_item_count",0)==0
print(f"  summary: completed={s.get('completed_item_count')} failed={s.get('failed_item_count')} phases={s.get('phases')} -> {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
PY
}

check_item_phase() { # out_root item phases...
  local out_root="$1"; local item="$2"; shift 2
  "$PYTHON_BIN" - "$out_root/items/$item/item_summary.json" "$item" "$@" <<'PY' || return 1
import sys, json, os
path, item = sys.argv[1], sys.argv[2]; phases_to_check = sys.argv[3:]
if not os.path.exists(path):
    print(f"  FAIL: no item_summary for {item}"); sys.exit(1)
d=json.load(open(path)); ph=d.get("phases",{})
for p in phases_to_check:
    if p not in ph:
        print(f"  FAIL: phase {p} missing for {item}"); sys.exit(1)
    anymiss=True
    # per-phase content assertion
    if p=="E4":
        anymiss = not(ph[p].get("budget_case_count",0)>=1 or ph[p].get("chunk_case_count",0)>=1)
        detail=f"budget={ph[p].get('budget_case_count')} chunk={ph[p].get('chunk_case_count')}"
    elif p=="E8":
        anymiss = not(ph[p].get("case_count",0)>=1); detail=f"case={ph[p].get('case_count')}"
    elif p=="E9":
        anymiss = ph[p].get("applicable") is not True; detail=f"app={ph[p].get('applicable')} beam_w={ph[p].get('beam_width')} fallback_w={ph[p].get('fallback_window_count')}"
    elif p in ("E5","E7"):
        anymiss = ph[p].get("applicable") is not True; detail=f"app={ph[p].get('applicable')}"
    else:
        anymiss=False; detail=""
    print(f"  phase {p}: {detail}" + ("  PASS" if not anymiss else "  FAIL"))
    if anymiss: sys.exit(1)
sys.exit(0)
PY
}

finalize() { # label item phases...
  local label="$1"; shift; local item="$1"; shift
  local out="$SUPP_ROOT/$label"
  local core_ok; check_summary "$out"; core_ok=$?
  local item_ok; check_item_phase "$out" "$item" "$@"; item_ok=$?
  if [[ $core_ok -eq 0 && $item_ok -eq 0 ]]; then echo "[$label] PASS"; PASS=$((PASS+1));
  else echo "[$label] FAIL"; FAIL=$((FAIL+1)); fi
}

# ---- C-E9-fallback: beam width 3 vs 1 (beam on vs beam-width-1 control), demo item ----
ITEM="$DEMO_ITEM"
run_suite C-E9-w3 "$SUPP_ROOT/c_e9_w3" --phases E9 --system-beam-width 3
finalize C-E9-w3 "$DEMO_ITEM" E9
run_suite C-E9-w1 "$SUPP_ROOT/c_e9_w1" --phases E9 --system-beam-width 1
finalize C-E9-w1 "$DEMO_ITEM" E9

# ---- C-E8-propagation: demo item E8 propagation diagnostic ----
run_suite C-E8 "$SUPP_ROOT/c_e8" --phases E8
finalize C-E8 "$DEMO_ITEM" E8

# ---- C-E4-uncompact: demo item E4 with full detail (NO --compact-artifacts) ----
run_suite C-E4 "$SUPP_ROOT/c_e4" --phases E4
finalize C-E4 "$DEMO_ITEM" E4

# ---- C-E5E7-native-multiwindow: native-concat multi-window item E5+E7 ----
ITEM="$MULTI_ITEM"
run_suite C-E5E7 "$SUPP_ROOT/c_e5e7" --phases E5,E7
finalize C-E5E7 "$MULTI_ITEM" E5 E7

echo ""
echo "==== supplemental smoke: PASS=$PASS FAIL=$FAIL ===="
[[ $FAIL -eq 0 ]]
