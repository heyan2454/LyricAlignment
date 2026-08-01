from __future__ import annotations

from lyricalign.research_v6.decoders import DecoderConfig, decode_rows
from lyricalign.research_v6.detector import DetectorConfig, inspect_alignment
from lyricalign.research_v6.experiment_analysis import candidate_record
from scripts.research.run_alignment_research_suite import synchronize_dynamic_plan


def _offset_rows():
    return [
        {
            "global_character_index": 10,
            "character": "甲",
            "raw_local_start_sec": 1.04,
            "raw_local_end_sec": 1.20,
            "raw_global_start_sec": 61.04,
            "raw_global_end_sec": 61.20,
            "official_fixed_local_start_sec": 1.04,
            "official_fixed_local_end_sec": 1.20,
            "official_fixed_global_start_sec": 61.04,
            "official_fixed_global_end_sec": 61.20,
            "fixed_global_start_sec": 61.04,
            "fixed_global_end_sec": 61.20,
            "start_sec": 61.04,
            "end_sec": 61.20,
            "raw_start_topk_classes": [13, 12],
            "raw_start_topk_probabilities": [0.9, 0.1],
            "raw_end_topk_classes": [15, 14],
            "raw_end_topk_probabilities": [0.9, 0.1],
            "raw_start_margin": 0.8,
            "raw_end_margin": 0.8,
        },
        {
            "global_character_index": 11,
            "character": "乙",
            "raw_local_start_sec": 1.20,
            "raw_local_end_sec": 1.36,
            "raw_global_start_sec": 61.20,
            "raw_global_end_sec": 61.36,
            "official_fixed_local_start_sec": 1.20,
            "official_fixed_local_end_sec": 1.36,
            "official_fixed_global_start_sec": 61.20,
            "official_fixed_global_end_sec": 61.36,
            "fixed_global_start_sec": 61.20,
            "fixed_global_end_sec": 61.36,
            "start_sec": 61.20,
            "end_sec": 61.36,
            "raw_start_topk_classes": [15, 14],
            "raw_start_topk_probabilities": [0.9, 0.1],
            "raw_end_topk_classes": [17, 16],
            "raw_end_topk_probabilities": [0.9, 0.1],
            "raw_start_margin": 0.8,
            "raw_end_margin": 0.8,
        },
    ]


def test_topk_timestamp_classes_are_converted_to_global_time_from_existing_fields():
    for name in ("joint_start_end", "topk_sequence"):
        rows = decode_rows(_offset_rows(), DecoderConfig(name=name, timestamp_step_sec=0.08, top_k=2))
        assert rows[0]["start_sec"] == 61.04
        assert rows[0]["end_sec"] == 61.20
        assert rows[1]["start_sec"] == 61.20
        assert rows[1]["end_sec"] == 61.36


def test_local_metric_scope_does_not_penalize_unrelated_song_units():
    gt = [
        {"character_index": i, "start_sec": float(i), "end_sec": float(i) + 0.5}
        for i in range(20)
    ]
    local = [{"global_character_index": 7, "start_sec": 7.0, "end_sec": 7.5}]
    baseline = [
        {"global_character_index": i, "start_sec": float(i), "end_sec": float(i) + 0.5}
        for i in range(20)
    ]
    record = candidate_record(
        "local", local, gt, structural={}, metric_indices=[7], metric_scope="target_span",
        spliced_rows=baseline, baseline_rows=baseline,
    )
    assert record["metrics"]["all_penalized_boundary_mae_sec"] == 0.0
    assert record["metric_scope"]["reference_unit_count"] == 1
    assert record["spliced_full_metrics"]["all_penalized_boundary_mae_sec"] == 0.0


class _FrozenModel:
    def predict_score(self, row):
        return 0.9 if int(row["global_character_index"]) == 1 else 0.1


def test_frozen_detector_score_drives_spans_in_its_own_scale():
    rows = [
        {
            "global_character_index": i,
            "character": str(i),
            "raw_global_start_sec": i * 0.2,
            "raw_global_end_sec": i * 0.2 + 0.1,
            "official_fixed_global_start_sec": i * 0.2,
            "official_fixed_global_end_sec": i * 0.2 + 0.1,
            "start_sec": i * 0.2,
            "end_sec": i * 0.2 + 0.1,
            "raw_start_margin": 1.0,
            "raw_end_margin": 1.0,
        }
        for i in range(3)
    ]
    report = inspect_alignment(
        rows,
        config=DetectorConfig(risk_threshold=99.0, safe_threshold=0.2),
        risk_model=_FrozenModel(),
        active_threshold=0.5,
        active_safe_threshold=0.2,
        detector_name="frozen_test",
    )
    assert report["active_score_key"] == "learned_risk_score"
    assert report["risk_spans"] == [{"character_start": 1, "character_end": 1}]
    assert report["features"][1]["risk_score"] == 0.9
    assert report["features"][1]["rule_risk_score"] != 0.9


def test_dynamic_plan_synchronizes_audio_and_text_cursor_without_new_offset_field():
    plan = {
        "windows": [
            {"window_index": 0, "input_start_sec": 0.0},
            {"window_index": 1, "input_start_sec": 50.0},
        ],
        "boundary_diagnostics": [
            {"safe_boundary": {"global_character_index": 5}}
        ],
    }
    rows = [
        {
            "global_character_index": i,
            "official_fixed_global_start_sec": 10.0 + i,
        }
        for i in range(8)
    ]
    result = synchronize_dynamic_plan(plan, rows, 2)
    second = result["windows"][1]
    assert second["input_start_sec"] == 13.0
    assert second["planned_input_character_start"] == 3
    assert second["safe_input_offset_units"] == 2

from lyricalign.research_v6.detector import event_metrics
from lyricalign.research_v6.experiment_analysis import (
    choose_budget_candidates,
    paired_decoder_transition_metrics,
)
from lyricalign.research_v6.windowing import SilenceInterval, cap_silence_mapping
from lyricalign.research_v6.requests import AlignmentRequest, CorruptionSpec, apply_corruption
from scripts.research.run_alignment_research_suite import remap_trace


def test_event_metrics_use_one_to_one_overlap_matching():
    rows = [
        {"global_character_index": i, "score": score, "label": label}
        for i, (score, label) in enumerate([
            (0.9, True), (0.9, True), (0.1, False),
            (0.9, True), (0.1, False), (0.9, False),
        ])
    ]
    result = event_metrics(rows, score_key="score", label_key="label", threshold=0.5, merge_gap_units=0)
    assert result["reference_event_count"] == 2
    assert result["predicted_event_count"] == 3
    assert (result["tp"], result["fp"], result["fn"]) == (2, 1, 0)


def test_decoder_transition_reports_raw_harm_and_repair():
    gt = [
        {"character_index": 0, "start_sec": 0.0, "end_sec": 0.1},
        {"character_index": 1, "start_sec": 0.2, "end_sec": 0.3},
    ]
    raw = [
        {"global_character_index": 0, "start_sec": 0.0, "end_sec": 0.1},
        {"global_character_index": 1, "start_sec": 1.0, "end_sec": 1.1},
    ]
    candidate = [
        {"global_character_index": 0, "start_sec": 1.0, "end_sec": 1.1},
        {"global_character_index": 1, "start_sec": 0.2, "end_sec": 0.3},
    ]
    result = paired_decoder_transition_metrics(raw, candidate, gt, tolerance_sec=0.16)
    assert result["raw_correct_harm_rate"] == 1.0
    assert result["raw_error_repair_rate"] == 1.0


def test_silence_trace_is_restored_to_original_clock():
    mapping = cap_silence_mapping(
        duration_sec=20.0,
        silences=[SilenceInterval(5.0, 15.0)],
        cap_sec=1.0,
    )
    trace = [{"window_index": 1, "input_start_sec": 6.0, "core_start_sec": 6.0, "core_end_sec": 10.0}]
    restored = remap_trace(trace, mapping)
    assert restored[0]["input_start_sec"] == 15.0
    assert restored[0]["core_start_sec"] == 15.0
    assert restored[0]["core_end_sec"] == 19.0


def test_sequential_text_budget_uses_first_nontruncated_candidate_without_risk_span():
    def candidate(amount, relation, risk, mae):
        return {
            "amount": amount,
            "coverage_relation": relation,
            "detector_selection_score": 0.9,
            "detector_report": {"risk_spans": risk},
            "candidate": {"name": str(amount), "metrics": {"all_penalized_boundary_mae_sec": mae, "coverage": 1.0}},
        }
    result = choose_budget_candidates([
        candidate(16, "core_target_truncated", [], 0.1),
        candidate(32, "future_only_removed_or_added", [{"character_start": 1, "character_end": 1}], 0.2),
        candidate(48, "future_only_removed_or_added", [], 0.3),
        candidate(64, "future_only_removed_or_added", [], 0.4),
    ])
    assert result["sequential_expansion"]["amount"] == 48
    assert result["detector_selected"]["amount"] in {32, 48, 64}


def test_budget_selection_accepts_no_gt_candidates_with_null_metrics():
    candidates = [
        {
            "amount": amount,
            "coverage_relation": "future_only_removed_or_added",
            "detector_selection_score": 0.0,
            "detector_report": {"risk_spans": []},
            "candidate": {"name": str(amount), "metrics": None},
        }
        for amount in (32, 48)
    ]
    result = choose_budget_candidates(candidates)
    assert result["oracle_best"] is None
    assert result["fixed_shortest"]["amount"] == 32
    assert result["sequential_expansion"]["amount"] == 32


def test_audio_corruption_keeps_ownership_inside_the_perturbed_request():
    request = AlignmentRequest("item", 170.0, 212.5, 460, 539, 180.0, 212.5)
    corrupted = apply_corruption(
        request, CorruptionSpec("audio_end_-2", audio_end_delta_sec=-2.0),
        total_units=539, duration_sec=212.5,
    )
    corrupted.validate(total_units=539, duration_sec=212.5)
    assert corrupted.ownership_end_sec == corrupted.audio_end_sec


def test_safe_boundary_metric_reuses_the_planning_decision_predicate():
    rows = [
        {
            "global_character_index": i,
            "character": str(i),
            "raw_global_start_sec": i * 0.2,
            "raw_global_end_sec": i * 0.2 + 0.1,
            "official_fixed_global_start_sec": i * 0.2,
            "official_fixed_global_end_sec": i * 0.2 + 0.1,
            "start_sec": i * 0.2,
            "end_sec": i * 0.2 + 0.1,
            "raw_start_margin": 2.0,
            "raw_end_margin": 2.0,
        }
        for i in range(2)
    ]

    class HighRisk:
        def predict_score(self, row):
            return 0.8 if int(row["global_character_index"]) == 0 else 0.1

    report = inspect_alignment(
        rows,
        config=DetectorConfig(risk_threshold=99.0, safe_threshold=0.2),
        risk_model=HighRisk(),
        active_threshold=0.5,
        active_safe_threshold=0.2,
    )
    first, second = report["features"]
    assert first["safe_boundary_score"] > 0.0
    assert first["safe_boundary_decision_score"] == 0.0
    assert 0 not in report["safe_boundaries"]
    assert second["safe_boundary_decision_score"] == second["safe_boundary_score"]

from lyricalign.demo.karaoke import parse_lyrics_text
from lyricalign.research_v6.metrics import aggregate_item_metrics
from lyricalign.research_v6.windowing import build_dynamic_window_plan
import scripts.research.run_alignment_research_suite as research_suite


def test_risk_gated_safe_boundary_reaches_dynamic_planner_end_to_end():
    baseline_rows = [
        {
            "global_character_index": 0,
            "official_fixed_global_end_sec": 58.0,
            "end_sec": 58.0,
        },
        {
            "global_character_index": 1,
            "official_fixed_global_end_sec": 62.0,
            "end_sec": 62.0,
        },
    ]
    report = {
        "active_score_key": "learned_risk_score",
        "features": [
            {
                "global_character_index": 0,
                "safe_boundary_score": 1.0,
                "safe_boundary_decision_score": 0.0,
                "risk_score": 0.9,
            },
            {
                "global_character_index": 1,
                "safe_boundary_score": 0.8,
                "safe_boundary_decision_score": 0.8,
                "risk_score": 0.1,
            },
        ],
    }
    candidates = research_suite.safe_boundary_candidates(report, baseline_rows)
    assert candidates[0]["safe_boundary_score"] == 0.0
    assert candidates[0]["raw_safe_boundary_score"] == 1.0
    plan = build_dynamic_window_plan(
        duration_sec=120.0,
        target_core_sec=60.0,
        left_context_sec=10.0,
        right_context_sec=10.0,
        safe_boundaries=candidates,
        search_before_sec=5.0,
        search_after_sec=5.0,
        minimum_score=0.25,
    )
    assert plan["boundary_diagnostics"][0]["safe_boundary"]["global_character_index"] == 1


def test_aggregate_metrics_handles_all_invalid_valid_mae_without_crashing():
    result = aggregate_item_metrics([
        {
            "metrics": {
                "reference_unit_count": 1,
                "all_penalized_boundary_mae_sec": 1.0,
                "valid_boundary_mae_sec": None,
                "coverage": 1.0,
            }
        }
    ])
    assert result["macro"]["valid_boundary_mae_sec"] is None
    assert result["reference_weighted_micro"]["valid_boundary_mae_sec"] is None


def test_complete_group_ranges_excludes_partial_96_unit_tail():
    assert research_suite.complete_group_ranges(191, 96) == [(0, 96)]
    assert research_suite.complete_group_ranges(192, 96) == [(0, 96), (96, 192)]


def test_e8_continuation_starts_from_repaired_prefix_and_reruns_tail(monkeypatch):
    document = parse_lyrics_text("甲乙丙丁", language="Chinese")
    seed_rows = [
        {"global_character_index": i, "start_sec": i * 0.5, "end_sec": i * 0.5 + 0.4}
        for i in range(4)
    ]
    trace = [
        {
            "window_index": 0,
            "core_start_sec": 0.0,
            "core_end_sec": 2.0,
            "input_start_sec": 0.0,
            "input_end_sec": 2.5,
            "committed_character_start": 0,
            "committed_character_end": 2,
            "input_character_start_before": 0,
            "committed_character_count": 2,
            "stable_suffix_candidate": None,
        },
        {
            "window_index": 1,
            "core_start_sec": 2.0,
            "core_end_sec": 4.0,
            "input_start_sec": 1.5,
            "input_end_sec": 4.0,
            "committed_character_start": 2,
            "committed_character_end": 4,
            "input_character_start_before": 1,
            "committed_character_count": 2,
            "is_final_core": True,
        },
    ]

    def fake_windowed_alignment(processor, model, audio, doc, args):
        assert args.research_initial_committed_cursor == 2
        assert len(args.research_initial_committed_rows) == 2
        assert len(args._precomputed_window_plan["windows"]) == 2
        rows = [dict(row) for row in args.research_initial_committed_rows]
        rows.extend([
            {"global_character_index": 2, "start_sec": 1.0, "end_sec": 1.4},
            {"global_character_index": 3, "start_sec": 1.5, "end_sec": 1.9},
        ])
        return rows, [{"window_index": 0}, {"window_index": 1}]

    monkeypatch.setattr(research_suite.SERIAL, "windowed_alignment", fake_windowed_alignment)
    args = type("Args", (), {
        "device": "cpu", "timestamp_segment_sec": 0.08, "decoder_top_k": 8,
        "core_sec": 60.0, "left_context_sec": 10.0, "right_context_sec": 10.0,
        "minimum_forward_characters": 64, "future_character_ratio": 1.35,
        "max_candidate_expansions": 4,
    })()
    rows, continuation_trace, metadata = research_suite.propagate_realign_candidate(
        seed_rows=seed_rows,
        target_end_index=1,
        trace=trace,
        processor=object(),
        model=object(),
        audio=[0.0],
        document=document,
        args=args,
    )
    assert len(rows) == 4
    assert len(continuation_trace) == 2
    assert metadata["initial_committed_cursor"] == 2
    assert metadata["rerun_window_count"] == 2


def test_actual_e9_beam_carries_model_backed_hypotheses_across_windows(monkeypatch):
    document = parse_lyrics_text("甲乙丙丁", language="Chinese")
    baseline_rows = [
        {
            "global_character_index": i,
            "start_sec": i * 0.5,
            "end_sec": i * 0.5 + 0.4,
            "fixed_global_start_sec": i * 0.5,
            "fixed_global_end_sec": i * 0.5 + 0.4,
        }
        for i in range(4)
    ]
    trace = [
        {
            "window_index": 0, "core_start_sec": 0.0, "core_end_sec": 1.0,
            "input_start_sec": 0.0, "input_end_sec": 1.5,
            "committed_character_start": 0, "committed_character_end": 2,
            "committed_cursor_after": 2, "next_window_input_character_start": 1,
            "committed_character_count": 2,
        },
        {
            "window_index": 1, "core_start_sec": 1.0, "core_end_sec": 2.0,
            "input_start_sec": 0.5, "input_end_sec": 2.0,
            "committed_character_start": 2, "committed_character_end": 4,
            "committed_cursor_after": 4, "next_window_input_character_start": 4,
            "committed_character_count": 2, "is_final_core": True,
        },
    ]

    def fake_windowed_alignment(processor, model, audio, doc, args):
        before = int(args.research_initial_committed_cursor)
        after = min(4, before + 2)
        branch_shift = (
            float(args._precomputed_window_plan["windows"][0]["input_start_sec"]) * 0.001
            + float(args.minimum_forward_characters) * 0.00001
        )
        rows = [dict(row) for row in args.research_initial_committed_rows]
        for i in range(before, after):
            start = i * 0.5 + branch_shift
            rows.append({
                "global_character_index": i,
                "start_sec": start,
                "end_sec": start + 0.4,
                "fixed_global_start_sec": start,
                "fixed_global_end_sec": start + 0.4,
            })
        window = args._precomputed_window_plan["windows"][0]
        return rows, [{
            **window,
            "committed_cursor_after": after,
            "next_window_input_character_start": max(0, after - 1),
            "committed_character_count": after - before,
            "attempts": [{"status": "accepted"}],
            "stable_suffix_candidate": None,
        }]

    monkeypatch.setattr(research_suite.SERIAL, "windowed_alignment", fake_windowed_alignment)
    monkeypatch.setattr(research_suite, "support_for_rows", lambda rows, profile: {})
    monkeypatch.setattr(research_suite, "inspect_alignment", lambda rows, **kwargs: {
        "features": [
            {"global_character_index": row["global_character_index"], "risk_score": 0.1}
            for row in rows
        ],
        "risk_spans": [],
    })
    args = type("Args", (), {
        "system_beam_width": 3,
        "system_beam_cursor_backtrack_units": 2,
        "system_beam_window_backtrack_sec": 2.0,
        "system_beam_extra_forward_characters": 32,
        "minimum_forward_characters": 64,
        "device": "cpu", "timestamp_segment_sec": 0.08, "decoder_top_k": 8,
        "core_sec": 60.0, "left_context_sec": 10.0, "right_context_sec": 10.0,
        "future_character_ratio": 1.35, "max_candidate_expansions": 4,
        "detector_tolerance_sec": 0.16, "frozen_detector_model": None,
        "detector_model_threshold": 0.5, "detector_risk_threshold": 1.0,
        "detector_safe_threshold": 0.25, "selected_detector_name": "rule",
    })()
    result = research_suite.run_cursor_window_beam(
        baseline_rows=baseline_rows,
        baseline_trace=trace,
        processor=object(), model=object(), audio=[0.0], document=document,
        audio_profile={}, args=args,
    )
    assert result["multi_hypothesis_window_count"] >= 1
    assert result["selected_state"]["committed_cursor"] == 4
    assert len(result["final_states"]) >= 2


def test_pilot_freeze_is_best_effort_and_never_blocks_formal(tmp_path, monkeypatch):
    import scripts.research.freeze_research_parameters as freeze
    (tmp_path / "research_summary.json").write_text(
        __import__("json").dumps({
            "selected_item_count": 1,
            "completed_item_count": 1,
            "failed_item_count": 1,
            "detector_summary": {"labelled_unit_count": 0},
            "decoder_summary": {
                "official": {
                    "all": {"macro": {"all_penalized_boundary_mae_sec": 0.2, "coverage": 0.9}},
                    "structural_macro": {"zero_duration_count": 1},
                }
            },
        }),
        encoding="utf-8",
    )
    (tmp_path / "complete.json").write_text('{"status":"partial_failure"}', encoding="utf-8")
    output = tmp_path / "frozen.json"
    monkeypatch.setattr(
        __import__("sys"),
        "argv",
        [
            "freeze_research_parameters.py",
            "--pilot-root", str(tmp_path),
            "--output", str(output),
        ],
    )
    assert freeze.main() == 0
    payload = __import__("json").loads(output.read_text(encoding="utf-8"))
    assert payload["selection_effectiveness"]["formal_run_is_allowed"] is True
    assert payload["selection_effectiveness"]["level"] == "degraded_best_effort_freeze"
    assert payload["selected_decoder"] == "official"


def test_safe_boundary_list_uses_the_frozen_evidence_threshold():
    rows = [
        {
            "global_character_index": 0,
            "character": "甲",
            "raw_global_start_sec": 0.0,
            "raw_global_end_sec": 0.2,
            "official_fixed_global_start_sec": 0.0,
            "official_fixed_global_end_sec": 0.2,
            "start_sec": 0.0,
            "end_sec": 0.2,
            "raw_start_margin": 2.0,
            "raw_end_margin": 2.0,
        }
    ]
    low = inspect_alignment(
        rows,
        config=DetectorConfig(risk_threshold=99.0, safe_threshold=99.0),
        active_safe_boundary_score_threshold=1e-9,
    )
    high = inspect_alignment(
        rows,
        config=DetectorConfig(risk_threshold=99.0, safe_threshold=99.0),
        active_safe_boundary_score_threshold=1.1,
    )
    assert low["safe_boundaries"] == [0]
    assert high["safe_boundaries"] == []
    assert high["active_safe_boundary_score_threshold"] == 1.1
    from lyricalign.research_v6.windowing import choose_safe_boundary
    assert choose_safe_boundary(
        [{"time_sec": 60.0, "safe_boundary_score": 0.0}],
        nominal_sec=60.0, minimum_sec=55.0, maximum_sec=65.0, minimum_score=0.0,
    ) is None


def test_e9_no_progress_hypotheses_are_rejected_and_explicitly_fall_back(monkeypatch):
    document = parse_lyrics_text("甲乙丙丁", language="Chinese")
    baseline_rows = [
        {
            "global_character_index": i,
            "start_sec": i * 0.5,
            "end_sec": i * 0.5 + 0.4,
            "fixed_global_start_sec": i * 0.5,
            "fixed_global_end_sec": i * 0.5 + 0.4,
        }
        for i in range(4)
    ]
    trace = [
        {
            "window_index": 0, "core_start_sec": 0.0, "core_end_sec": 1.0,
            "input_start_sec": 0.0, "input_end_sec": 1.5,
            "committed_character_start": 0, "committed_character_end": 2,
            "committed_cursor_after": 2, "next_window_input_character_start": 1,
            "committed_character_count": 2,
        },
        {
            "window_index": 1, "core_start_sec": 1.0, "core_end_sec": 2.0,
            "input_start_sec": 0.5, "input_end_sec": 2.0,
            "committed_character_start": 2, "committed_character_end": 4,
            "committed_cursor_after": 4, "next_window_input_character_start": 4,
            "committed_character_count": 2, "is_final_core": True,
        },
    ]

    def no_progress(processor, model, audio, doc, args):
        before = int(args.research_initial_committed_cursor)
        window = args._precomputed_window_plan["windows"][0]
        return list(args.research_initial_committed_rows), [{
            **window,
            "committed_cursor_after": before,
            "next_window_input_character_start": before,
            "committed_character_count": 0,
            "attempts": [],
            "stable_suffix_candidate": None,
        }]

    monkeypatch.setattr(research_suite.SERIAL, "windowed_alignment", no_progress)
    args = type("Args", (), {
        "system_beam_width": 3,
        "system_beam_cursor_backtrack_units": 2,
        "system_beam_window_backtrack_sec": 2.0,
        "system_beam_extra_forward_characters": 32,
        "minimum_forward_characters": 64,
        "device": "cpu", "timestamp_segment_sec": 0.08, "decoder_top_k": 8,
        "core_sec": 60.0, "left_context_sec": 10.0, "right_context_sec": 10.0,
        "future_character_ratio": 1.35, "max_candidate_expansions": 4,
        "detector_tolerance_sec": 0.16, "frozen_detector_model": None,
        "detector_model_threshold": 0.5, "detector_risk_threshold": 1.0,
        "detector_safe_threshold": 0.25, "dynamic_safe_score": 0.25,
        "selected_detector_name": "rule",
    })()
    result = research_suite.run_cursor_window_beam(
        baseline_rows=baseline_rows,
        baseline_trace=trace,
        processor=object(), model=object(), audio=[0.0], document=document,
        audio_profile={}, args=args,
    )
    assert result["fallback_window_count"] == 2
    assert result["selected_state"]["committed_cursor"] == 4
    assert result["selected_state"]["cumulative"]["fallback_count"] == 2
    assert all(row["failed_expansion_count"] == 3 for row in result["window_records"])


def test_safe_boundary_freeze_jointly_calibrates_risk_ceiling_and_evidence():
    from scripts.research.freeze_research_parameters import select_safe_boundary_joint_thresholds

    rows = [
        {"rule_risk_score": 0.10, "safe_boundary_score": 0.80, "gt_safe_boundary": True},
        {"rule_risk_score": 0.20, "safe_boundary_score": 0.70, "gt_safe_boundary": True},
        {"rule_risk_score": 0.30, "safe_boundary_score": 0.20, "gt_safe_boundary": False},
        {"rule_risk_score": 0.80, "safe_boundary_score": 0.90, "gt_safe_boundary": False},
    ]
    selected = select_safe_boundary_joint_thresholds(
        rows, selected_name="rule", model_payload=None, max_fpr=0.0,
    )
    assert selected is not None
    assert selected["f1"] == 1.0
    assert selected["risk_ceiling"] == 0.2
    from lyricalign.research_v6.detector import safe_boundary_score
    assert selected["evidence_threshold"] == safe_boundary_score(rows[1], risk_score=0.2)


def test_pilot_selection_excludes_test_and_test_derived_synthetic_rows():
    items = [
        {"item_id": "train", "dataset": "m4", "split": "train", "selection_role": "m4_train", "duration_sec": 10},
        {"item_id": "val", "dataset": "m4", "split": "val", "selection_role": "m4_val", "duration_sec": 20},
        {"item_id": "test", "dataset": "m4", "split": "test", "selection_role": "m4_test", "duration_sec": 30},
        {"item_id": "synthetic_test", "dataset": "m4_long", "split": "test", "selection_role": "m4_synthetic_long", "duration_sec": 40},
        {"item_id": "heldout", "dataset": "mir1k", "split": "development", "selection_role": "heldout", "duration_sec": 50},
    ]
    args = type("Args", (), {
        "item_id": None, "mode": "pilot", "pilot_items_per_dataset": 8,
    })()
    selected = research_suite.select_items(items, args)
    assert {row["item_id"] for row in selected} == {"train", "val"}


def test_pilot_explicit_test_item_is_rejected():
    items = [{"item_id": "test", "dataset": "m4", "split": "test", "selection_role": "m4_test"}]
    args = type("Args", (), {
        "item_id": "test", "mode": "pilot", "pilot_items_per_dataset": 1,
    })()
    import pytest
    with pytest.raises(ValueError, match="not eligible for pilot"):
        research_suite.select_items(items, args)


def test_frozen_decoder_is_passed_to_local_and_serial_routes():
    args = type("Args", (), {
        "device": "cpu", "timestamp_segment_sec": 0.08, "decoder_top_k": 4,
        "decoder_beam_size": 12, "selected_decoder_name": "topk_sequence",
        "core_sec": 60.0, "left_context_sec": 10.0, "right_context_sec": 10.0,
        "minimum_forward_characters": 64, "future_character_ratio": 1.35,
        "max_candidate_expansions": 4,
    })()
    local = research_suite.local_args(args)
    serial = research_suite.serial_args(args)
    assert local.decoder_kind == "topk_sequence"
    assert local.decoder_beam_size == 12
    assert serial.decoder_kind == "topk_sequence"
    assert serial.serial_control_decoder_kind == "topk_sequence"
    assert serial.decoder_beam_size == 12


def test_research_decoder_projection_updates_serial_fixed_fields_before_commit():
    import scripts.demo.align_qwen_fa_serial_demo as serial_demo
    rows = _offset_rows()
    projected = serial_demo.apply_research_timestamp_decoder(
        rows,
        decoder_kind="topk_sequence",
        timestamp_segment_sec=0.08,
        decoder_top_k=2,
        decoder_beam_size=16,
        global_audio_offset_sec=60.0,
    )
    assert projected[0]["fixed_global_start_sec"] == 61.04
    assert projected[0]["fixed_global_end_sec"] == 61.20
    assert projected[0]["fixed_local_start_sec"] == __import__("pytest").approx(1.04)
    assert projected[0]["decoder_kind"] == "topk_sequence"
    same = serial_demo.project_rows_for_decoder(projected, "same")
    assert same[0]["fixed_global_start_sec"] == projected[0]["fixed_global_start_sec"]


def test_e8_downstream_effect_summary_excludes_failed_static_fallbacks():
    result = research_suite.summarize_e8_downstream_effects([
        {
            "propagation_status": "failed",
            "downstream_mae_delta": 0.0,
            "downstream_coverage_delta": 0.0,
        },
        {
            "propagation_status": "complete",
            "downstream_mae_delta": 0.4,
            "downstream_coverage_delta": -0.1,
        },
    ])
    assert result["candidate_propagation_complete_count"] == 1
    assert result["candidate_propagation_failure_count"] == 1
    assert result["downstream_mae_delta_mean_sec"] == 0.4
    assert result["downstream_coverage_delta_mean"] == -0.1
