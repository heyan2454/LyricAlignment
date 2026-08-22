#!/usr/bin/env python3
"""Generate a machine-readable behavior registry for Lyric Align productization.

The registry is based on the 2026-08-14 session's mechanism design and the
2026-08-16 no-training evaluation strategy. It is intentionally not an
exhaustive configuration matrix; it records single-factor ablation candidates.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "reports/behavior_registry.json"

BEHAVIORS = [
    {
        "behavior_id": "input.multilingual_normalization",
        "layer": "input_text_normalization",
        "name": "Multilingual character/word/phoneme unit mapping",
        "target_failures": ["cross-language token mismatch", "character vs word granularity leakage", "Japanese word-unit boundary errors"],
        "hypothesis": "Explicit language-aware unit construction reduces forced-aligner prompt ambiguity.",
        "possible_harm": ["Over-splitting/merging changes alignment semantics", "Extra normalization complexity"],
        "datasets": ["mir_mlpop_cmn", "mir_mlpop_yue", "pjs", "gtsinger_chinese", "jamendolyrics_en"],
        "evidence": ["20260814 full-slot vs B4 language-aware comparison", "20260816 GTSinger full diagnostic: R2 both_100ms=90.1% on 1226 Chinese units"],
        "productization_gate": "diagnostic_visible then regression_selection",
    },
    {
        "behavior_id": "window.silence_aware",
        "layer": "window_context",
        "name": "Silence-aware window planning with skip-silent and boundary protection",
        "target_failures": ["long-song degradation", "silence-split fragments", "context drift across acoustic gaps"],
        "hypothesis": "Using strong silence anchors keeps each 60s request acoustically coherent.",
        "possible_harm": ["Short cores near silence may lose context", "More window-planning code paths"],
        "datasets": ["mir_mlpop_cmn", "mir_mlpop_yue", "jamendolyrics_en"],
        "evidence": ["Current full-slot baseline uses shared silence-aware config", "B4-vs-Current visualization", "20260816 GTSinger full diagnostic: 75 short segments runnable through serial demo", "20260816 hard-case ablation: compress/strict/skip silence mechanisms showed no metric change on 3 short hard cases"],
        "productization_gate": "diagnostic_visible then regression_selection",
    },
    {
        "behavior_id": "window.full_slot_vs_preslot",
        "layer": "window_context",
        "name": "Full-slot direct inference vs pre-slot occurrence-aware serial",
        "target_failures": ["repeated-lyrics misassignment", "serial error propagation", "whole-song collapse"],
        "hypothesis": "Full-slot with the complete window text avoids feeding whole-song units into one window.",
        "possible_harm": ["Full-slot may lose serial cursor constraints", "Different failure modes on very long songs"],
        "datasets": ["mir_mlpop_cmn", "jamendolyrics_en"],
        "evidence": ["20260814 full-slot fixes", "B4-vs-Current comparisons"],
        "productization_gate": "regression_selection",
    },
    {
        "behavior_id": "recovery.ru_coarse_proposal",
        "layer": "candidate_selection",
        "name": "R-U coarse target proposal",
        "target_failures": ["large initial errors", "targets needing coarse localization before refinement"],
        "hypothesis": "A coarse proposal identifies the recovery basin better than re-aligning the whole region.",
        "possible_harm": ["Proposal may be wrong and bias refinement", "Extra forward cost"],
        "datasets": ["mir_mlpop_cmn", "jamendolyrics_en", "gtsinger_chinese"],
        "evidence": ["20260814 R-U evidence", "E4 coarse-fine pilot"],
        "productization_gate": "diagnostic_visible then regression_selection",
    },
    {
        "behavior_id": "recovery.rs_context_isolation",
        "layer": "candidate_selection",
        "name": "R-S full local window with fixed context slots",
        "target_failures": ["context displacement", "collateral harm when repairing a target"],
        "hypothesis": "Isolating active targets while freezing context slots preserves surrounding alignment.",
        "possible_harm": ["May be too conservative for large errors", "Requires reliable fixed anchors"],
        "datasets": ["mir_mlpop_cmn", "pjs", "gtsinger_chinese"],
        "evidence": ["20260814 R-S verified context-isolation mechanism"],
        "productization_gate": "diagnostic_visible then regression_selection",
    },
    {
        "behavior_id": "recovery.coarse_fine",
        "layer": "candidate_selection",
        "name": "R-CF coarse-to-fine refinement",
        "target_failures": ["cases where R-U proposal alone is insufficient", "fine-grained split needed"],
        "hypothesis": "First localize with R-U, then refine with a bounded sparse/fixed target.",
        "possible_harm": ["Two-stage cost", "Stage A/B mismatch can add complexity"],
        "datasets": ["mir_mlpop_cmn", "jamendolyrics_en", "gtsinger_chinese"],
        "evidence": ["20260814 R-CF demo and E4 pilot"],
        "productization_gate": "diagnostic_visible then regression_selection",
    },
    {
        "behavior_id": "recovery.multi_iteration_recrop_split",
        "layer": "recovery_dynamics",
        "name": "Multi-iteration / audio recrop / fine-grained split",
        "target_failures": ["first repair stalls at fixed point", "coarse region formulation hides recoverable units"],
        "hypothesis": "Changing observation/crop or splitting the region can expand the recovery basin.",
        "possible_harm": ["More forwards", "oscillation/divergence", "increased system complexity"],
        "datasets": ["mir_mlpop_cmn", "jamendolyrics_en", "gtsinger_chinese"],
        "evidence": ["20260814 E1/E2/E3 design; not fully productized"],
        "productization_gate": "diagnostic_visible screening, then regression_selection",
    },
    {
        "behavior_id": "safety.no_gt_gate",
        "layer": "safety_writeback",
        "name": "No-GT writeback gate using raw/official/posterior/consensus signals",
        "target_failures": ["unsafe realign writeback", "catastrophic regressions", "context corruption"],
        "hypothesis": "Structural and confidence signals can gate writeback without GT leakage.",
        "possible_harm": ["Over-conservative gate blocks useful repairs", "Signal calibration cost"],
        "datasets": ["mir_mlpop_cmn", "jamendolyrics_en", "pjs"],
        "evidence": ["20260814 E5/E7 no-GT signal design"],
        "productization_gate": "regression_selection only after diagnostic signal study",
    },
    {
        "behavior_id": "postprocess.monotonic_min_duration",
        "layer": "postprocessing",
        "name": "Monotonicity, minimum duration, boundary smoothing and merge rules",
        "target_failures": ["zero-duration runs", "timestamp inversions", "cross-line overlaps"],
        "hypothesis": "Deterministic postprocessing can turn structurally invalid outputs into usable timelines.",
        "possible_harm": ["May hide genuine model uncertainty", "Aggressive smoothing can reduce accuracy"],
        "datasets": ["mir_mlpop_cmn", "jamendolyrics_en", "pjs", "gtsinger_chinese"],
        "evidence": ["Existing character_interval_metrics_v3_tolerant", "zero-duration analysis"],
        "productization_gate": "diagnostic_visible then regression_selection",
    },
    {
        "behavior_id": "postprocess.zero_duration_gate",
        "layer": "postprocessing",
        "name": "Zero-duration and overlap warning gate for productization",
        "target_failures": ["final zero-duration units", "raw inter-unit overlap", "timestamp regressions"],
        "hypothesis": "Explicit quality gates can separate structurally clean outputs from outputs needing repair or rejection.",
        "possible_harm": ["Over-rejection lowers usable yield", "Gate thresholds need calibration"],
        "datasets": ["gtsinger_chinese", "mir_mlpop_cmn", "jamendolyrics_en"],
        "evidence": ["20260816 GTSinger full diagnostic: 30-34/75 segments had final_zero_duration warning"],
        "productization_gate": "diagnostic_visible then regression_selection",
    },
    {
        "behavior_id": "decoder.raw_vs_official",
        "layer": "timestamp_decoder",
        "name": "Raw vs official timestamp decoder selection",
        "target_failures": ["boundary jitter", "zero-duration", "overlap"],
        "hypothesis": "Raw decoder may preserve sharper boundaries while official decoder may smooth; selection should be data-dependent.",
        "possible_harm": ["Raw decoder can introduce overlap/selected overlap", "Regressions on a small number of clean segments"],
        "datasets": ["gtsinger_chinese", "pjs"],
        "evidence": [
            "20260816 GTSinger full diagnostic: raw decoder improved both_100ms 90.05%->91.84% (20 improved, 2 regressed)",
            "20260816 PJS 5-segment: raw decoder reduced zero-duration but added selected overlap warnings"
        ],
        "productization_gate": "regression_selection",
    },
]


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    registry = {
        "schema_version": "lyric_align_behavior_registry_v1",
        "description": "Single-factor ablation candidates for no-training Evaluation V1 productization research.",
        "behaviors": BEHAVIORS,
    }
    atomic_json(args.out, registry)
    print(json.dumps({"out": str(args.out), "behavior_count": len(BEHAVIORS)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
