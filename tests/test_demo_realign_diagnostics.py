from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from lyricalign.demo.karaoke import parse_lyrics_text
from lyricalign.demo.realign_diagnostics import (
    bounded_splice,
    build_anchor_rows,
    build_overlap_features,
    commit_dependency_span,
    mine_natural_candidates,
    scan_anchor_policies,
    select_single_repair_candidate,
    selected_rollback_candidate,
    stage_rollback_candidate,
    stage_transition_provenance,
)

ROOT = Path(__file__).resolve().parents[1]


def serial_module():
    path = ROOT / "scripts" / "demo" / "align_qwen_fa_serial_demo.py"
    spec = importlib.util.spec_from_file_location("realign_shadow_serial_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def row(index: int, selected_start: float, selected_end: float, start: float, end: float) -> dict[str, object]:
    return {
        "global_character_index": index,
        "character": chr(ord("甲") + index),
        "raw_global_start_sec": selected_start,
        "raw_global_end_sec": selected_end,
        "fixed_global_start_sec": selected_start,
        "fixed_global_end_sec": selected_end,
        "selected_start_sec": selected_start,
        "selected_end_sec": selected_end,
        "start_sec": start,
        "end_sec": end,
        "raw_start_top1_probability": 0.9,
        "raw_end_top1_probability": 0.9,
        "raw_start_margin": 0.8,
        "raw_end_margin": 0.8,
        "raw_start_entropy": 0.1,
        "raw_end_entropy": 0.1,
        "raw_boundary_margin_mean": 0.8,
        "overlap_compressed": start > selected_start,
        "overlap_compression_floor_sec": start,
    }


def test_overlap_features_retain_two_window_predictions() -> None:
    shadow = [
        {**row(2, 1.00, 1.20, 1.00, 1.20), "shadow_window_index": 0},
        {**row(2, 1.08, 1.28, 1.08, 1.28), "shadow_window_index": 1},
    ]
    features = build_overlap_features(shadow)[2]
    assert features["overlap_observation_count"] == 2
    assert abs(features["overlap_fixed_start_range_sec"] - 0.08) < 1e-9
    assert features["overlap_window_indices"] == [0, 1]


def test_commit_dependency_span_traces_previous_final_end_without_gt() -> None:
    rows = [
        row(0, 0.0, 0.5, 0.0, 0.5),
        row(1, 0.4, 1.0, 0.5, 1.0),
        row(2, 0.8, 0.9, 1.0, 1.0),
    ]
    start, end, trace = commit_dependency_span(rows, 2, 2)
    assert (start, end) == (0, 2)
    assert [item["dependency_index"] for item in trace] == [1, 0]
    assert all(item["reason"] == "previous_final_end_supplied_forward_compression_floor" for item in trace)


def test_natural_candidate_mining_merges_collapse_and_dependency() -> None:
    rows = [
        row(0, 0.0, 0.5, 0.0, 0.5),
        row(1, 0.4, 1.0, 0.5, 1.0),
        row(2, 0.8, 0.9, 1.0, 1.0),
        row(3, 1.0, 1.3, 1.0, 1.3),
    ]
    candidates = mine_natural_candidates(rows, [], item_id="song", audio_variant="demucs")
    assert candidates
    candidate = candidates[0]
    assert candidate["observed_character_start"] <= 2 <= candidate["observed_character_end"]
    assert candidate["dependency_character_start"] == 0
    assert candidate["trigger_counts"]["zero_duration"] >= 1


def test_bounded_splice_preserves_non_target_rows() -> None:
    baseline = [
        {"global_character_index": 0, "start_sec": 0.0, "end_sec": 1.0},
        {"global_character_index": 1, "start_sec": 1.0, "end_sec": 2.0},
        {"global_character_index": 2, "start_sec": 2.0, "end_sec": 3.0},
        {"global_character_index": 3, "start_sec": 3.0, "end_sec": 4.0},
    ]
    replacement = [
        {"global_character_index": 1, "start_sec": 0.8, "end_sec": 1.8},
        {"global_character_index": 2, "start_sec": 1.8, "end_sec": 3.2},
    ]
    merged, diagnostic = bounded_splice(
        baseline, replacement, replace_start=1, replace_end=2, remerge=True
    )
    assert merged[0]["start_sec"] == 0.0 and merged[0]["end_sec"] == 1.0
    assert merged[3]["start_sec"] == 3.0 and merged[3]["end_sec"] == 4.0
    assert merged[1]["start_sec"] == 1.0
    assert merged[2]["end_sec"] == 3.0
    assert diagnostic["valid"] is True


def test_selected_rollback_recovers_precompression_interval() -> None:
    rows = [
        row(0, 0.0, 1.0, 0.0, 1.0),
        row(1, 1.0, 2.0, 1.0, 2.0),
        row(2, 1.5, 2.5, 2.0, 2.5),
        row(3, 2.5, 3.5, 2.5, 3.5),
    ]
    merged, diagnostic = selected_rollback_candidate(rows, 2, 2)
    assert merged[2]["start_sec"] == 2.0  # bounded by unchanged prefix
    assert merged[2]["end_sec"] == 2.5
    assert diagnostic["valid"] is True


def test_anchor_scan_reports_pair_coverage() -> None:
    rows = [row(index, index * 0.5, index * 0.5 + 0.4, index * 0.5, index * 0.5 + 0.4) for index in range(6)]
    gt = [
        {"character_index": index, "character": chr(ord("甲") + index), "start_sec": index * 0.5, "end_sec": index * 0.5 + 0.4}
        for index in range(6)
    ]
    shadow = []
    for window in (0, 1):
        for source in rows:
            shadow.append({**source, "shadow_window_index": window})
    anchors = build_anchor_rows(rows, shadow, gt, item_id="song", audio_variant="demucs")
    for anchor in anchors:
        anchor["core_sec"] = 30.0
    candidates = [{
        "item_id": "song", "audio_variant": "demucs", "core_sec": 30.0,
        "dependency_character_start": 2, "dependency_character_end": 3,
    }]
    results, shortlist = scan_anchor_policies(anchors, candidates)
    assert results
    assert shortlist
    assert any(result["pair_coverage"] == 1.0 for result in results)


def test_windowed_alignment_can_capture_accepted_shadow_rows(monkeypatch) -> None:
    module = serial_module()
    document = parse_lyrics_text("甲乙丙丁\n")
    absolute = {0: (1.0, 10.0), 1: (20.0, 31.0), 2: (31.0, 45.0), 3: (45.0, 60.0)}

    def fake_infer_slice(*, document, character_start, character_end, global_audio_offset_sec, **kwargs):
        output = []
        for item in document.characters[character_start:character_end]:
            start, end = absolute[item.global_index]
            output.append({
                "global_character_index": item.global_index,
                "character": item.text,
                "fixed_global_start_sec": start,
                "fixed_global_end_sec": end,
                "raw_global_start_sec": start,
                "raw_global_end_sec": end,
                "raw_boundary_margin_mean": 1.0,
            })
        return output, {"character_count": len(output)}

    class FakeAudio:
        def __init__(self, samples: int):
            self.samples = samples
        def __len__(self):
            return self.samples
        def __getitem__(self, value):
            return FakeAudio((value.stop or self.samples) - (value.start or 0))

    monkeypatch.setattr(module, "infer_slice", fake_infer_slice)
    args = SimpleNamespace(
        core_sec=30.0, left_context_sec=10.0, right_context_sec=10.0,
        minimum_forward_characters=64, future_character_ratio=1.35,
        future_line_padding=1, max_candidate_expansions=4,
        boundary_start_tolerance_sec=0.32, seam_tolerance_sec=0.16,
        capture_shadow_rows=True,
    )
    _, trace = module.windowed_alignment(object(), object(), FakeAudio(60 * 16000), document, args)
    assert trace
    assert all("shadow_rows" in window for window in trace)
    assert trace[0]["shadow_rows"][0]["global_character_index"] == 0


def test_stage_provenance_identifies_decoded_collapse() -> None:
    source = row(0, 1.0, 2.0, 2.0, 2.0)
    source["fixed_global_start_sec"] = 2.0
    source["fixed_global_end_sec"] = 2.0
    source["selected_start_sec"] = 2.0
    source["selected_end_sec"] = 2.0
    provenance = stage_transition_provenance([source])[0]
    assert provenance["first_collapsed_stage"] == "processor_decoded"
    assert provenance["first_changed_stage"] == "processor_decoded"


def test_cross_window_disagreement_candidates_are_capped_and_peak_centered() -> None:
    rows = [row(index, index * 0.5, index * 0.5 + 0.4, index * 0.5, index * 0.5 + 0.4) for index in range(20)]
    shadow = []
    for index, source in enumerate(rows):
        shadow.append({**source, "shadow_window_index": 0})
        shifted = dict(source)
        shifted["fixed_global_start_sec"] = float(source["fixed_global_start_sec"]) + (0.8 if index == 10 else 0.0)
        shifted["fixed_global_end_sec"] = float(source["fixed_global_end_sec"]) + (0.8 if index == 10 else 0.0)
        shifted["shadow_window_index"] = 1
        shadow.append(shifted)
    candidates = mine_natural_candidates(
        rows, shadow, item_id="song", audio_variant="demucs", max_target_units=8
    )
    disagreement = [row for row in candidates if row["candidate_type"] == "cross_window_disagreement_peak"]
    assert disagreement
    assert all(row["target_unit_count"] <= 8 for row in disagreement)
    assert any(10 in row["character_indices"] for row in disagreement)


def test_single_selector_keeps_baseline_without_anomaly_reduction() -> None:
    candidate = {
        "mode": "local_decoded_bounded_remerge", "anchor_mode": "best",
        "crop_mode": "exact_anchor", "splice": {"valid": True},
        "acceptance": {"before_anomaly": {"score": 0}, "after_anomaly": {"score": 0}},
        "modification_summary": {"boundary_change_abs_sec": {"mean": 0.1}},
    }
    selected = select_single_repair_candidate([candidate])
    assert selected["decision"] == "keep_baseline"


def _repair_candidate(
    *, ordinal_shift: float = 0.0, anchor_mode: str = "best_automatic",
    crop_mode: str = "exact_anchor", context_units: int = 0,
    mode: str = "local_raw_bounded_remerge", before: int = 8, after: int = 0,
    anchor_reproduction: dict[str, float] | None = None,
) -> dict[str, object]:
    return {
        "mode": mode,
        "anchor_mode": anchor_mode,
        "crop_mode": crop_mode,
        "context_units": context_units,
        "target_indices": [1, 2],
        "replacement_indices": [1, 2],
        "changed_rows": [
            {"global_character_index": 1, "start_sec": 1.0 + ordinal_shift, "end_sec": 1.4 + ordinal_shift},
            {"global_character_index": 2, "start_sec": 1.4 + ordinal_shift, "end_sec": 2.0 + ordinal_shift},
        ],
        "splice": {"valid": True},
        "anchor_reproduction": anchor_reproduction,
        "acceptance": {"before_anomaly": {"score": before}, "after_anomaly": {"score": after}},
        "modification_summary": {"boundary_change_abs_sec": {"mean": 0.1}},
    }


def test_selector_excludes_ground_truth_oracle_and_handles_none_anchor_reproduction() -> None:
    oracle = _repair_candidate(anchor_mode="gt_oracle", anchor_reproduction=None)
    automatic = _repair_candidate(anchor_mode="best_automatic", crop_mode="matched_context", context_units=2)
    selected = select_single_repair_candidate([oracle, automatic])
    assert selected["selected"] is True
    assert selected["anchor_mode"] == "best_automatic"
    assert selected["rejected_candidate_counts"]["ground_truth_anchor_excluded"] == 1


def test_selector_requires_agreement_from_second_reasonable_input() -> None:
    exact = _repair_candidate(crop_mode="exact_anchor")
    matched_close = _repair_candidate(ordinal_shift=0.08, crop_mode="matched_context", context_units=2)
    selected = select_single_repair_candidate(
        [exact, matched_close], require_context_agreement=True,
        context_agreement_tolerance_sec=0.16,
    )
    assert selected["selected"] is True
    assert selected["context_agreement"]["supported"] is True

    matched_far = _repair_candidate(ordinal_shift=1.0, crop_mode="matched_context", context_units=2)
    rejected = select_single_repair_candidate(
        [exact, matched_far], require_context_agreement=True,
        context_agreement_tolerance_sec=0.16,
    )
    assert rejected["selected"] is False
    assert rejected["rejected_candidate_counts"]["no_second_input_agreement"] == 2


def test_raw_rollback_expands_to_predecessor_that_would_recompress_target() -> None:
    rows = [
        row(0, 0.0, 1.0, 0.0, 1.0),
        row(1, 1.0, 1.8, 1.0, 2.2),
        row(2, 1.8, 2.6, 2.2, 2.6),
        row(3, 2.6, 3.2, 2.6, 3.2),
    ]
    # Raw predecessor ends at 1.8, so including index 1 allows index 2 to return
    # to its raw 1.8 start instead of being clamped by final index 1 end=2.2.
    merged, diagnostic = stage_rollback_candidate(rows, "raw", 2, 2, max_predecessor_units=4)
    assert diagnostic["effective_replace_start"] == 1
    assert diagnostic["predecessor_expansion_count"] == 1
    assert abs(merged[2]["start_sec"] - 1.8) < 1e-9


def test_disagreement_candidate_windows_do_not_overlap() -> None:
    rows = [row(index, index * 0.5, index * 0.5 + 0.4, index * 0.5, index * 0.5 + 0.4) for index in range(30)]
    shadow = []
    for index, source in enumerate(rows):
        shadow.append({**source, "shadow_window_index": 0})
        shifted = dict(source)
        shift = 0.8 if index in {10, 12, 22} else 0.0
        shifted["fixed_global_start_sec"] = float(source["fixed_global_start_sec"]) + shift
        shifted["fixed_global_end_sec"] = float(source["fixed_global_end_sec"]) + shift
        shifted["shadow_window_index"] = 1
        shadow.append(shifted)
    candidates = [
        candidate for candidate in mine_natural_candidates(
            rows, shadow, item_id="song", audio_variant="demucs", max_target_units=8,
        ) if candidate["candidate_type"] == "cross_window_disagreement_peak"
    ]
    intervals = sorted((candidate["dependency_character_start"], candidate["dependency_character_end"]) for candidate in candidates)
    assert intervals
    assert all(left_end < right_start for (_, left_end), (right_start, _) in zip(intervals, intervals[1:]))
