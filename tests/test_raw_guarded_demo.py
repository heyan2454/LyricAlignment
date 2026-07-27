from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from lyricalign.demo.raw_guarded import (
    agreement_between_trials,
    build_runtime_anchor_rows,
    choose_runtime_anchor_policy,
    nonoverlapping_candidates,
    prf,
)

ROOT = Path(__file__).resolve().parents[1]


def row(index: int, start: float, end: float, margin: float = 0.9) -> dict[str, object]:
    return {
        "global_character_index": index,
        "character": str(index),
        "raw_global_start_sec": start,
        "raw_global_end_sec": end,
        "fixed_global_start_sec": start,
        "fixed_global_end_sec": end,
        "selected_start_sec": start,
        "selected_end_sec": end,
        "start_sec": start,
        "end_sec": end,
        "raw_start_margin": margin,
        "raw_end_margin": margin,
        "raw_start_top1_probability": 0.95,
        "raw_end_top1_probability": 0.95,
    }


def test_runtime_anchor_rows_need_no_ground_truth() -> None:
    rows = [row(0, 0.0, 0.4), row(1, 0.4, 0.8), row(2, 0.8, 1.2)]
    shadow = []
    for window in (0, 1):
        for source in rows:
            shadow.append({**source, "shadow_window_index": window})
    anchors = build_runtime_anchor_rows(rows, shadow)
    policy = choose_runtime_anchor_policy(anchors)
    assert len(anchors) == 3
    assert policy["family"] == "A4"
    assert policy["confidence_margin_min"] == 0.9


def test_exact_plus2_agreement_is_tolerance_bounded() -> None:
    exact = [row(1, 1.0, 1.4), row(2, 1.4, 1.8)]
    plus2 = [row(1, 1.08, 1.48), row(2, 1.48, 1.88)]
    assert agreement_between_trials(exact, plus2, [1, 2], tolerance_sec=0.16)["supported"]
    plus2[1]["end_sec"] = 2.2
    assert not agreement_between_trials(exact, plus2, [1, 2], tolerance_sec=0.16)["supported"]


def test_candidate_selection_is_severity_first_and_nonoverlapping() -> None:
    candidates = [
        {"dependency_character_start": 2, "dependency_character_end": 4, "severity_score": 3},
        {"dependency_character_start": 3, "dependency_character_end": 5, "severity_score": 9},
        {"dependency_character_start": 8, "dependency_character_end": 8, "severity_score": 1},
    ]
    selected = nonoverlapping_candidates(candidates)
    assert [(row["dependency_character_start"], row["dependency_character_end"]) for row in selected] == [(3, 5), (8, 8)]


def test_prf_handles_empty_and_nonempty_counts() -> None:
    assert prf(0, 0, 0)["f1"] == 0.0
    metric = prf(8, 2, 4)
    assert abs(metric["precision"] - 0.8) < 1e-9
    assert abs(metric["recall"] - 2 / 3) < 1e-9


def test_demo_defaults_point_to_current_r2_assets() -> None:
    path = ROOT / "scripts" / "demo" / "align_qwen_fa_raw_guarded_demo.py"
    spec = importlib.util.spec_from_file_location("raw_guarded_demo_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.DEFAULT_REVISION == "c07281df297b9905d24a508279258cccf987a064"
    assert module.DEFAULT_R2.endswith("checkpoints/step-000750")
    assert "Qwen3-ForcedAligner-0.6B-hf" in module.DEFAULT_MODEL


def test_processor_artifact_preserves_official_decoder_when_raw_drives_commit() -> None:
    from lyricalign.demo.alignment_artifacts import stage_rows

    source = row(0, 1.0, 1.4)
    source.update({
        "fixed_global_start_sec": 1.0,
        "fixed_global_end_sec": 1.4,
        "official_fixed_global_start_sec": 0.8,
        "official_fixed_global_end_sec": 1.2,
    })
    processor = stage_rows([source], "processor_decoded")[0]
    selected = stage_rows([source], "selected")[0]
    assert (processor["start_sec"], processor["end_sec"]) == (0.8, 1.2)
    assert (selected["start_sec"], selected["end_sec"]) == (1.0, 1.4)
