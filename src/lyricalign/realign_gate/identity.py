"""Shared identity and frozen constants for realign_gate.

Everything that must not be re-derived at runtime lives here, keyed to the
frozen baseline described in
docs/sessions/20260812_detector_production_realign_gate/04_OPENCODE_IMPLEMENTATION_PLAN.md
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path("/home/hyan/LyricAlignment")
DATA_ROOT = Path("/home/hyan/Data/lyricalign")

MODEL_ID = "Qwen3-ForcedAligner-0.6B-hf"
MODEL_REVISION = "c07281df297b9905d24a508279258cccf987a064"
CHECKPOINT_ID = "r2-step-000750"
CHECKPOINT_PATH = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"

FROZEN_OP_PATH = (
    DATA_ROOT
    / "runs/research_transition_recovery_detector_20260810_realgt_expansion_handoff"
    / "stage3b_cohort_ab_eval/FROZEN_OPERATING_POINTS.json"
)

REAL_GT_ANNOTATIONS = (
    DATA_ROOT
    / "derived/20260723_m4singer_overlay_slur_time_v1/prepare/m4singer_character_annotations.jsonl"
)

# Raw operating points (frozen val). T_accept/T_reject must match the artifact.
RAW_T_ACCEPT = 0.16546343952822562
RAW_T_REJECT = 0.16837782471409926
RAW_VAL_SAFE_ACCEPT_RATE = 0.8688524590163934
RAW_VAL_PROTECTED_RECALL = 0.6551724137931034

# Retrospective-after-fix numbers exist only in prose; no exact artifact.
RETROSPECTIVE_SOURCE_MISSING = {
    "safe_accept_rate": 0.8320,
    "protected_recall": 0.9567,
    "reproduced": False,
    "status": "not_reproduced_source_missing",
}

# Production baseline window.
CORE_SEC = 60.0
LEFT_CONTEXT_SEC = 10.0
RIGHT_CONTEXT_SEC = 10.0

# Old run to reuse (read-only).
OLD_RUN = DATA_ROOT / "runs/realign_recovery_20260812_20260811T202813Z"
HANDOFF_RUN = DATA_ROOT / "runs/research_transition_recovery_detector_20260810_realgt_expansion_handoff"


def load_frozen_operating_points(target: str = "raw") -> dict:
    with open(FROZEN_OP_PATH) as f:
        op = json.load(f)
    branch = op[target]["standardized_logistic"]
    return {
        "target": target,
        "model_kind": branch["model_kind"],
        "best_combo": branch["best_combo"],
        "operating_points": branch["operating_points"],
    }


def baseline_identity() -> dict:
    """Content-address the frozen baseline identity (mirrors forward_cache keys)."""
    return {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_path": CHECKPOINT_PATH,
        "core_sec": CORE_SEC,
        "left_context_sec": LEFT_CONTEXT_SEC,
        "right_context_sec": RIGHT_CONTEXT_SEC,
        "detector": {"kind": "standardized_logistic", "combo": "R", "merge": "light_merge"},
        "operating_points": {"T_accept": RAW_T_ACCEPT, "T_reject": RAW_T_REJECT},
    }
