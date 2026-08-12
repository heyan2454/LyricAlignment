"""Frozen baseline identity for realign-recovery Phase 0.

The detector artifact sha256 is computed at import time from the frozen
operating-points file; when the file is unavailable the field is "MISSING".
"""
from __future__ import annotations

import hashlib
from pathlib import Path

FROZEN_OPERATING_POINTS_PATH = Path(
    "/home/hyan/Data/lyricalign/runs/"
    "research_transition_recovery_detector_20260810_realgt_expansion_handoff/"
    "stage3b_cohort_ab_eval/FROZEN_OPERATING_POINTS.json"
)


def _detector_artifact_sha256() -> str:
    if not FROZEN_OPERATING_POINTS_PATH.is_file():
        return "MISSING"
    return hashlib.sha256(FROZEN_OPERATING_POINTS_PATH.read_bytes()).hexdigest()


FROZEN_BASELINE_IDENTITY = {
    "model_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
    "model_revision": "c07281df297b9905d24a508279258cccf987a064",
    "checkpoint_path": "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750",
    "processor_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
    "request_mode": "full_slot",
    "core_sec": 60,
    "left_context_sec": 10,
    "right_context_sec": 10,
    "silence_aware_window_plan": True,
    "decoder_view": "raw",
    "detector_artifact_sha256": _detector_artifact_sha256(),
    "detector_accept_threshold": 0.16546343952822562,
    "detector_reject_threshold": 0.16837782471409926,
    "real_gt_source": "m4singer_overlay_slur_time_v1",
    "schema_version": "realign_recovery_baseline_identity_v1",
}
