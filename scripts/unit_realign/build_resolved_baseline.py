#!/usr/bin/env python3
"""E0 (WP1) — freeze resolved baselines for the 2026-08-14 visualization session.

Emits, from the *code's literal* frozen values (not doc memory):

  CURRENT_BASELINE_RESOLVED.json   full-slot Current baseline (request_mode=full_slot,
                                   decoder_view=raw) + cascade + window params + hash
  B4_BASELINE_RESOLVED.json        historical pre-slot serial B4 baseline
                                   (align_qwen_fa_serial_demo --decoder official) + hash
  BUDGET_PROJECTION.json           GPU forward projection for this session

Both resolved JSONs carry a canonical ``sha256`` (reused baseline_identity.identity_digest)
so downstream cache/rerender hashes are stable. ``actual_writeback=0`` everywhere.

Usage:
  PYTHONPATH=src python scripts/unit_realign/build_resolved_baseline.py --out-root <run>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.realign_recovery.baseline_identity import identity_digest  # noqa: E402
from lyricalign.realign_recovery.frozen_baseline import FROZEN_BASELINE_IDENTITY  # noqa: E402


# Window/silence resolved values — taken from demo/window_planning.py
# build_silence_aware_window_plan parameter defaults (these match the B4 freeze).
WINDOW_SILENCE_RESOLVED = {
    "silence_aware_window_plan": True,
    "strict_silence_boundary_plan": False,
    "compress_silence_audio": False,
    "skip_silent_windows": True,
    "surround_context_sec": (10.0, 10.0),  # left, right
    # silence-aware parameters (window_planning defaults)
    "silence_boundary_min_sec": 0.8,
    "strong_silence_anchor_sec": 1.5,
    "silence_boundary_search_sec": 6.0,
    "leading_silence_min_sec": 2.0,
    "tail_min_core_sec": 18.0,
    "minimum_core_sec": 12.0,
}


def _current_baseline() -> dict:
    identity = dict(FROZEN_BASELINE_IDENTITY)  # request_mode=full_slot, decoder_view=raw
    cascade = dict(WINDOW_SILENCE_RESOLVED)
    # Current cascade core/context come from the frozen identity fields.
    cascade["core_sec"] = identity["core_sec"]
    cascade["left_context_sec"] = identity["left_context_sec"]
    cascade["right_context_sec"] = identity["right_context_sec"]
    resolved = {
        "role": "current_baseline",
        "stage": "01_generate_resolved_baseline",
        "source": "realign_recovery.frozen_baseline.FROZEN_BASELINE_IDENTITY + demo.window_planning",
        "identity": identity,
        "cascade": cascade,
        "actual_writeback": 0,
        "schema_version": "resolved_baseline_v1",
    }
    resolved["sha256"] = identity_digest(
        {**identity, **{"cascade": cascade, "schema_version": "resolved_baseline_v1"}}
    )
    return resolved


def _b4_baseline() -> dict:
    # B4 = historical pre-slot serial runner align_qwen_fa_serial_demo --decoder official
    # (03 V1: pre-slot/non-slot serial semantics; do NOT run Current's full-slot runner
    #  with the same parameters and call it B4).
    identity = {
        "model_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
        "model_revision": FROZEN_BASELINE_IDENTITY["model_revision"],
        "checkpoint_path": FROZEN_BASELINE_IDENTITY["checkpoint_path"],
        "processor_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
        "decoder_kind": "official",  # B4 freeze (Current is decoder_view=raw)
        "request_mode": "pre_slot_serial_non_slot",
        "runner": "scripts/demo/align_qwen_fa_serial_demo.py",
        "core_sec": 60,
        "left_context_sec": 10,
        "right_context_sec": 10,
        "schema_version": "resolved_baseline_v1",
    }
    resolved = {
        "role": "b4_historical_pre_slot_serial",
        "stage": "01_generate_resolved_baseline",
        "source": "03_VISUALIZATION_DESIGN V1 B4 freeze + serial runner semantics",
        "identity": identity,
        "cascade": dict(WINDOW_SILENCE_RESOLVED, **{
            "core_sec": 60, "left_context_sec": 10, "right_context_sec": 10,
        }),
        "actual_writeback": 0,
        "schema_version": "resolved_baseline_v1",
    }
    resolved["sha256"] = identity_digest(
        {**identity, **{"cascade": resolved["cascade"], "schema_version": "resolved_baseline_v1"}}
    )
    return resolved


def _budget_projection() -> dict:
    return {
        "per_forward_sec": 0.5,  # warm GPU, conservative of E_note §5.2 (0.2-0.75)
        "screening_regions": 40,
        "screening_branches_per_region": 5,
        "screening_forward_estimate": 300,
        "expansion_regions": 200,
        "expansion_flow": "top_1_or_2_mechanisms_only",
        "expansion_forward_estimate": 500,
        "total_forward_estimate": 1000,
        "total_forward_wall_sec_warm": 500,   # 1000 * 0.5
        "target_hours": 10,
        "hard_cap_hours": 12,
        "note": "forward wall time is minutes at warm GPU; dominant cost is model load / cold cache / evidence IO",
        "schema_version": "budget_projection_v1",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", required=True, help="run root to write resolved JSONs into")
    args = parser.parse_args()

    out = Path(args.out_root)
    out.mkdir(parents=True, exist_ok=True)

    current = _current_baseline()
    b4 = _b4_baseline()
    budget = _budget_projection()

    for name, payload in (
        ("CURRENT_BASELINE_RESOLVED.json", current),
        ("B4_BASELINE_RESOLVED.json", b4),
        ("BUDGET_PROJECTION.json", budget),
    ):
        target = out / name
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {target}")

    print("current sha256:", current["sha256"])
    print("b4 sha256:     ", b4["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
