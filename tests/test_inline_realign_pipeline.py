from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from lyricalign.demo.inline_realign import (
    analyze_precommit_trial,
    attempt_probe_rows,
    build_observation_features,
    nearest_segment_pair,
    reproduce_segment,
    stable_segment_candidate_diagnostics,
    stable_segments,
    anomaly_spans_from_trace,
)
from lyricalign.demo import media_render

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "demo" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(index: int, start: float, end: float, *, owner: int = 0, margin: float = 0.9) -> dict:
    return {
        "global_character_index": index,
        "character": chr(ord("甲") + index),
        "line_index": 0,
        "index_in_line": index,
        "start_sec": start,
        "end_sec": end,
        "selected_start_sec": start,
        "selected_end_sec": end,
        "fixed_global_start_sec": start,
        "fixed_global_end_sec": end,
        "official_fixed_global_start_sec": start,
        "official_fixed_global_end_sec": end,
        "raw_global_start_sec": start,
        "raw_global_end_sec": end,
        "raw_boundary_margin_mean": margin,
        "owner_window_index": owner,
        "core_start_sec": 0.0,
        "core_end_sec": 30.0,
        "input_start_sec": 0.0,
        "input_end_sec": 40.0,
    }


def test_precommit_localizes_collapse_and_ignores_future_lookahead_tail() -> None:
    candidates = [row(index, 39.2, 39.2) for index in range(12)]
    trial = [
        {**source, "start_sec": 10.0, "end_sec": 10.0}
        for source in candidates[:8]
    ]
    diagnostic = analyze_precommit_trial(
        existing_rows=[],
        candidate_rows=candidates[:8],
        all_candidate_rows=candidates,
        trial_rows=trial,
        window={"input_end_sec": 40.0, "core_end_sec": 30.0},
        vocal_activity={"sustained_active_duration_sec": 20.0},
    )
    assert diagnostic["triggered"] is True
    assert diagnostic["reasons"] == ["collapse_or_boundary_stacking"]
    assert diagnostic["tail_pileup_count"] == 0
    assert diagnostic["tail_reference"] == "committed_rows_near_core_end"
    assert diagnostic["anomaly_spans"][0]["character_start"] == 0
    assert diagnostic["anomaly_spans"][0]["character_end"] == 7


def test_precommit_tail_pileup_uses_committed_rows_near_core_end() -> None:
    committed = [
        {**row(index, 29.0 + index * 0.05, 29.02 + index * 0.05),
         "start_sec": 29.0 + index * 0.05, "end_sec": 29.02 + index * 0.05}
        for index in range(10)
    ]
    diagnostic = analyze_precommit_trial(
        existing_rows=[], candidate_rows=committed, all_candidate_rows=committed,
        trial_rows=committed, window={"input_end_sec": 40.0, "core_end_sec": 30.0},
        vocal_activity={"sustained_active_duration_sec": 20.0},
    )
    assert "large_core_tail_pileup" in diagnostic["reasons"]
    assert diagnostic["anomaly_spans"][0]["character_start"] == 0
    assert diagnostic["anomaly_spans"][0]["character_end"] == 9


def test_precommit_detects_active_window_without_commit() -> None:
    diagnostic = analyze_precommit_trial(
        existing_rows=[], candidate_rows=[], all_candidate_rows=[row(0, 35.0, 35.2)],
        trial_rows=[], window={"input_end_sec": 40.0},
        vocal_activity={"sustained_active_duration_sec": 12.0},
        uncommitted_character_index=7,
    )
    assert diagnostic["reasons"] == ["active_core_without_lyric_progress"]
    assert diagnostic["anomaly_spans"][0]["character_start"] == 7


def test_future_lookahead_is_not_counted_as_supported_repeat() -> None:
    core = row(0, 5.0, 5.2)
    future = {**row(0, 35.0, 35.2), "core_start_sec": 0.0, "core_end_sec": 30.0}
    features = build_observation_features([core, future])[0]
    assert features["observation_count"] == 2
    assert features["supported_observation_count"] == 1
    assert features["observation_roles"] == {"core": 1, "future_lookahead": 1}


def test_single_window_high_confidence_segment_is_allowed() -> None:
    rows = [row(index, index * 0.4, index * 0.4 + 0.2) for index in range(5)]
    segments = stable_segments(rows, rows, min_units=3, confidence_quantile=0.5)
    assert len(segments) == 1
    assert segments[0]["character_start"] == 0
    assert segments[0]["character_end"] == 4
    assert segments[0]["evidence_kind"] == "single_window_high_confidence"


def test_anchor_diagnostics_separate_rejection_reasons() -> None:
    rows = [
        row(0, 0.0, 0.2, margin=0.9),
        row(1, 0.4, 0.4, margin=0.9),
        {**row(2, 0.8, 1.0, margin=0.9), "raw_global_start_sec": 0.2},
        row(3, 1.2, 1.4, margin=0.1),
        row(4, 1.6, 1.8, margin=0.9),
    ]
    diagnostic = stable_segment_candidate_diagnostics(
        rows, rows, target_start=2, target_end=2, confidence_quantile=0.5,
        raw_official_tolerance_sec=0.16, repeated_context_tolerance_sec=0.24,
    )
    assert diagnostic["reason_counts"]["non_positive_duration"] == 1
    assert diagnostic["reason_counts"]["raw_official_movement_exceeded"] == 1
    assert diagnostic["reason_counts"]["confidence_below_window_quantile"] == 1
    assert diagnostic["nearest_left_rows"]
    assert diagnostic["nearest_right_rows"]


def test_segment_pair_has_no_character_or_line_span_cap() -> None:
    segments = [
        {"character_start": 0, "character_end": 4},
        {"character_start": 80, "character_end": 90},
    ]
    left, right, reason = nearest_segment_pair(segments, target_start=20, target_end=60)
    assert reason is None
    assert left == segments[0]
    assert right == segments[1]


def test_attempt_probe_collection_is_bounded() -> None:
    rows = [row(index, index * 0.5, index * 0.5 + 0.2) for index in range(100)]
    probes = attempt_probe_rows(
        rows, core_end_sec=30.0, next_input_boundary_sec=20.0, max_rows=12,
    )
    assert 1 <= len(probes) <= 12
    assert all("global_character_index" in probe for probe in probes)


def test_stable_segments_can_be_split_around_target() -> None:
    rows = [row(index, index * 0.4, index * 0.4 + 0.2) for index in range(10)]
    segments = stable_segments(
        rows, rows, min_units=2, confidence_quantile=0.5,
        excluded_character_range=(4, 5),
    )
    assert [(segment["character_start"], segment["character_end"]) for segment in segments] == [(0, 3), (6, 9)]


def test_anomaly_spans_use_local_diagnostic_range() -> None:
    trace = [{
        "window_index": 2, "committed_character_start": 10, "committed_character_end": 50,
        "precommit_diagnostic": {
            "triggered": True,
            "anomaly_spans": [{
                "character_start": 31, "character_end": 35,
                "reason": "zero_duration_run", "severity": 15,
            }],
        },
    }]
    spans = anomaly_spans_from_trace(trace)
    assert spans[0]["character_start"] == 31
    assert spans[0]["character_end"] == 35
    assert spans[0]["range_source"] == "localized_precommit_span"


def test_prefix_reproduction_requires_enough_observed_units() -> None:
    source_rows = [row(index, index * 0.4, index * 0.4 + 0.2) for index in range(4)]
    segment = {"character_start": 0, "character_end": 3, "rows": source_rows}
    current = [source_rows[0]]
    result = reproduce_segment(segment, current, minimum_observed_units=2, minimum_observed_ratio=0.5)
    assert result["supported"] is False
    assert result["reason"] == "insufficient_segment_coverage"


def test_gt_oracle_spans_and_incomplete_guard(tmp_path: Path) -> None:
    module = load_script("inline_experiment_helpers", "run_inline_realign_experiment.py")
    rows = [row(index, index * 0.4, index * 0.4 + 0.2) for index in range(6)]
    rows[2]["start_sec"] += 0.5; rows[2]["end_sec"] += 0.5
    gt = [
        {"character_index": index, "character": source["character"],
         "start_sec": index * 0.4, "end_sec": index * 0.4 + 0.2}
        for index, source in enumerate(rows)
    ]
    spans = module.gt_error_spans(rows, gt, threshold_sec=0.24)
    assert spans[0]["character_start"] == 2
    baseline = {
        "identity": {"request_hash": "base"},
        "summary": {"audio_duration_sec": 3.0},
        "lines": [{"line_index": 0}],
        "characters": rows,
    }
    output = tmp_path / "incomplete" / "alignment.json"
    summary = module.construct_incomplete_guard(
        item={"item_id": "x"}, baseline_payload=baseline, candidates=spans,
        out_path=output, gt=gt,
    )
    assert summary["completion_status"] == "incomplete"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["characters"]) == 2
    assert payload["summary"]["remaining_character_count"] == 4


def test_demo_manifest_finds_multiple_prepared_suffixes(tmp_path: Path) -> None:
    module = load_script("inline_manifest_demo", "build_inline_realign_manifest.py")
    song = tmp_path / "song"; song.mkdir()
    (song / "a.txt").write_text("甲乙", encoding="utf-8")
    (song / "a.mp3").write_bytes(b"media")
    prepared = song / "a_qwen_fa_raw_guarded" / "work" / "audio"
    prepared.mkdir(parents=True)
    (prepared / "vocals.wav").write_bytes(b"wav")
    args = module.parser().parse_args([
        "--mode", "smoke", "--out-root", str(tmp_path / "out"),
        "--demo-root", str(tmp_path), "--demo-recursive",
    ])
    audit = {}
    rows = module.demo_rows(args, 2, audit)
    assert len(rows) == 1
    assert rows[0]["prepared_root"].endswith("a_qwen_fa_raw_guarded")


def _experiment_args() -> SimpleNamespace:
    return SimpleNamespace(
        stable_segment_min_units=2, stable_segment_confidence_quantile=0.5,
        stable_raw_official_tolerance_sec=0.16, stable_context_tolerance_sec=0.24,
        stable_prefix_reproduction_tolerance_sec=0.24,
        stable_prefix_minimum_observed_units=2, stable_prefix_minimum_observed_ratio=0.5,
        max_stable_window_trials_per_item=2, max_expansion_trials_per_item=1,
        attempt_probe_max_rows=12, device="cpu", timestamp_segment_sec=0.08,
    )


def test_planner_divergence_scan_finds_informative_window() -> None:
    module = load_script("inline_planner_divergence", "run_inline_realign_experiment.py")
    first = row(0, 28.0, 28.2)
    second = row(1, 29.5, 29.8)
    for source in (first, second):
        source["official_fixed_local_start_sec"] = source["start_sec"]
        source["official_fixed_local_end_sec"] = source["end_sec"]
        source["raw_local_start_sec"] = source["start_sec"]
        source["raw_local_end_sec"] = source["end_sec"]
    second["raw_global_start_sec"] = 31.0; second["raw_global_end_sec"] = 31.2
    second["raw_local_start_sec"] = 31.0; second["raw_local_end_sec"] = 31.2
    trace = [{
        "window_index": 0, "input_character_start_before": 0, "committed_cursor_before": 0,
        "core_start_sec": 0.0, "core_end_sec": 30.0, "is_final_core": False,
        "next_input_boundary_sec": 20.0, "shadow_rows": [first, second],
    }]
    result = module.planner_divergence_summary(trace, total_characters=2)
    assert result["diverged_window_count"] == 1
    assert result["windows"][0]["committed_cursor_delta"] == -1


def test_stable_window_assistance_produces_split_suggestion_and_trial(monkeypatch) -> None:
    module = load_script("inline_assistance_helpers", "run_inline_realign_experiment.py")
    rows = []
    for index in range(10):
        source = row(index, 18.0 + index, 18.4 + index, owner=0 if index < 7 else 1)
        rows.append(source)
    shadow0 = [{**source, "fixed_global_start_sec": source["start_sec"], "fixed_global_end_sec": source["end_sec"]} for source in rows[:8]]
    shadow1 = [{**source, "fixed_global_start_sec": source["start_sec"], "fixed_global_end_sec": source["end_sec"]} for source in rows[2:]]
    trace = [
        {"window_index": 0, "core_end_sec": 30.0, "next_input_boundary_sec": 20.0,
         "committed_character_start": 0, "committed_character_end": 7, "committed_cursor_after": 7,
         "shadow_rows": shadow0},
        {"window_index": 1, "effective_input_start_sec": 20.0, "input_start_sec": 20.0,
         "input_end_sec": 50.0, "core_start_sec": 30.0, "core_end_sec": 50.0,
         "input_character_start_before": 5, "committed_character_end": 10,
         "candidate_character_end": 10, "shadow_rows": shadow1},
    ]
    gt = [{"character_index": index, "start_sec": source["start_sec"], "end_sec": source["end_sec"]} for index, source in enumerate(rows)]
    args = _experiment_args()
    assistance = module.stable_window_assistance_summary(
        args=args, rows=rows, trace=trace, gt=gt, total_characters=10,
    )
    assert assistance["transition_count"] == 1
    assert assistance["transitions"][0]["stable_prefix_input_cursor"] is not None

    monkeypatch.setattr(module, "_attempt_rows_for_rerun", lambda **kwargs: (rows, {"ok": True}))
    trials = module.run_stable_window_assistance_trials(
        args=args, processor=None, model=None, audio=[0] * 800000, document=SimpleNamespace(characters=list(range(10))),
        gt=gt, rows=rows, trace=trace, assistance=assistance,
    )
    assert trials["successful_trial_count"] <= trials["trial_count"]


def test_forced_expansion_trials_actively_run_larger_text(monkeypatch) -> None:
    module = load_script("inline_expansion_helpers", "run_inline_realign_experiment.py")
    rows = [row(index, index * 0.4, index * 0.4 + 0.2) for index in range(10)]
    trace = [{
        "window_index": 0, "candidate_character_start": 0, "candidate_character_end": 6,
        "committed_character_count": 5, "core_end_sec": 3.0, "input_start_sec": 0.0, "input_end_sec": 4.0,
        "attempts": [{"attempt_index": 0, "probe_rows": rows[:6]}],
        "precommit_diagnostic": {"triggered": False},
    }]
    monkeypatch.setattr(module, "_attempt_rows_for_rerun", lambda **kwargs: (rows[:kwargs["character_end"]], {"ok": True}))
    result = module.run_forced_expansion_trials(
        args=_experiment_args(), processor=None, model=None, audio=[0] * 64000,
        document=SimpleNamespace(characters=list(range(10))), gt=[], rows=rows, trace=trace,
        assistance=None,
    )
    assert result["window_count"] == 1
    assert result["variant_run_count"] == 2


def minimal_alignment(path: Path, request_hash: str) -> None:
    payload = {
        "identity": {"request_hash": request_hash},
        "summary": {"audio_duration_sec": 1.0},
        "lines": [{"line_index": 0}],
        "characters": [{
            "global_character_index": 0,
            "line_index": 0,
            "index_in_line": 0,
            "character": "甲",
            "start_sec": 0.0,
            "end_sec": 0.5,
        }],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_direct_render_uses_one_ffmpeg_pass_and_content_hash(tmp_path: Path, monkeypatch) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    minimal_alignment(left, "same")
    minimal_alignment(right, "same")
    audio = tmp_path / "mix.wav"
    audio.write_bytes(b"audio")
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd=None) -> None:
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")

    monkeypatch.setattr(media_render, "_run", fake_run)
    monkeypatch.setattr(media_render.shutil, "which", lambda _: "/usr/bin/fake")
    output = tmp_path / "compare.mp4"
    result = media_render.render_alignment_comparison(
        alignment_paths=[left, right], labels=["O0", "O1"],
        visual_source=None, audio_track=audio, output_path=output,
        ass_root=tmp_path / "ass", font="Noto Sans", layout="two", profile="review",
    )
    assert result["encoding_passes"] == 1
    assert len(commands) == 1
    assert "split=2" in commands[0][commands[0].index("-filter_complex") + 1]
    first_hash = result["request_hash"]

    payload = json.loads(right.read_text(encoding="utf-8"))
    payload["characters"][0]["end_sec"] = 0.6
    right.write_text(json.dumps(payload), encoding="utf-8")
    result2 = media_render.render_alignment_comparison(
        alignment_paths=[left, right], labels=["O0", "O1"],
        visual_source=None, audio_track=audio, output_path=output,
        ass_root=tmp_path / "ass", font="Noto Sans", layout="two", profile="review",
    )
    assert result2["request_hash"] != first_hash
    assert len(commands) == 2


def test_render_defaults_to_official_pair_review() -> None:
    module = load_script("inline_render_defaults", "render_decoder_realign_comparison.py")
    args = module.parser().parse_args([
        "--alignment-root", "/tmp/a", "--mix-audio", "/tmp/m.wav", "--out-root", "/tmp/o",
    ])
    assert args.four_way is False
    assert args.profile == "review"


def test_manifest_timestamp_conversion_and_default_m4_split() -> None:
    module = load_script("inline_manifest_test", "build_inline_realign_manifest.py")
    gt = module.timestamp_gt({
        "item_id": "x", "lyrics_normalized": "甲乙",
        "timestamp_class_ids": [1, 2, 3, 5], "timestamp_segment_sec": 0.08,
    })
    assert gt[0]["start_sec"] == 0.08
    assert gt[1]["end_sec"] == 0.40
    collapsed = module.timestamp_gt({
        "item_id": "x", "lyrics_normalized": "甲",
        "timestamp_class_ids": [4, 4], "timestamp_segment_sec": 0.08,
    })
    assert collapsed[0]["start_sec"] == 0.32
    assert collapsed[0]["end_sec"] == 0.40
    assert collapsed[0]["timestamp_interval_repaired"] is True
    args = module.parser().parse_args(["--mode", "smoke", "--out-root", "/tmp/o"])
    assert args.m4_splits == "validation"
    assert "_qwen_fa_raw_guarded" in args.demo_prepared_suffixes


def test_pipeline_formal_does_not_include_heldout_by_default() -> None:
    module = load_script("inline_pipeline_test", "run_inline_realign_pipeline.py")
    args = module.parser().parse_args([
        "--mode", "formal", "--out-root", "/tmp/o",
        "--mir1k-subset-root", "/tmp/mir", "--m4-labels", "/tmp/m4.jsonl",
        "--m4-audio-root", "/tmp/audio", "--model", "/tmp/model",
        "--revision", "rev", "--r2-checkpoint", "/tmp/r2",
    ])
    assert args.include_heldout is False


def test_followup_summarizer_keeps_oracle_and_automatic_separate(tmp_path: Path) -> None:
    module = load_script("inline_followup_summary", "summarize_inline_realign_followup.py")
    (tmp_path / "experiment_summary.json").write_text(json.dumps({
        "completed_item_count": 1, "failed_item_count": 0,
    }), encoding="utf-8")
    (tmp_path / "experiment_manifest.jsonl").write_text(json.dumps({
        "item_id": "x", "dataset": "mir1k", "profile": "natural_long",
        "selection_role": "development",
    }) + "\n", encoding="utf-8")
    item = tmp_path / "items" / "x"
    (item / "branches" / "B2_30_silence_official").mkdir(parents=True)
    (item / "item_summary.json").write_text(json.dumps({
        "dataset": "mir1k", "profile": "natural_long", "selection_role": "development",
    }), encoding="utf-8")
    (item / "inline_realign_shadow.json").write_text(json.dumps({
        "candidate_count": 2, "automatic_candidate_count": 1,
        "gt_oracle_candidate_count": 1, "local_inference_attempted_count": 2,
        "would_write_count": 1,
        "decisions": [
            {"reason": "no_left_stable_segment", "trigger": {"candidate_source": "automatic_precommit"}},
            {"reason": "shadow_would_write", "trigger": {"candidate_source": "gt_oracle"},
             "would_write": True, "gt_improved": True,
             "context_agreement": {"supported": True}},
        ],
    }), encoding="utf-8")
    (item / "branches" / "B2_30_silence_official" / "alignment.json").write_text(json.dumps({
        "summary": {"character_count": 2, "window_count": 1},
        "characters": [],
        "planner_divergence": {"evaluated_window_count": 1, "diverged_window_count": 0, "windows": []},
    }), encoding="utf-8")
    payload = module.summarize(tmp_path)
    shadow = payload["automatic_and_oracle_realign"]
    assert shadow["automatic_candidate_count"] == 1
    assert shadow["gt_oracle_candidate_count"] == 1
    assert shadow["gt_improved_count"] == 1
    assert shadow["automatic_reason_counts"]["no_left_stable_segment"] == 1
    assert shadow["gt_oracle_reason_counts"]["shadow_would_write"] == 1


def test_mir1k_manifest_auto_materializes_metadata_only_spare(tmp_path: Path, monkeypatch) -> None:
    module = load_script("inline_manifest_mir1k_repair", "build_inline_realign_manifest.py")
    subset = tmp_path / "subset"
    subset.mkdir()
    selection_rows = [
        {
            "item_id": "dev_1", "song_id": "dev_1.wav", "singer_id": "dev",
            "selection_role": "development", "selection_order": 0, "lyrics": "甲乙",
        },
        {
            "item_id": "spare_1", "song_id": "spare_1.wav", "singer_id": "spare",
            "selection_role": "spare", "selection_order": None, "lyrics": "丙丁",
        },
    ]
    module.write_jsonl(subset / "selection.jsonl", selection_rows)
    source_characters = tmp_path / "characters.jsonl"
    module.write_jsonl(source_characters, [
        {"item_id": item_id, "character_index": index, "character": character,
         "start_sec": index * 0.5, "end_sec": index * 0.5 + 0.3}
        for item_id, text in (("dev_1", "甲乙"), ("spare_1", "丙丁"))
        for index, character in enumerate(text)
    ])
    raw_root = tmp_path / "raw_mir1k"
    raw_root.mkdir()
    module.atomic_json(subset / "selection.json", {
        "source_characters": str(source_characters),
        "mir1k_root": str(raw_root),
        "units_per_line": 12,
    })

    def create_item(item_id: str, lyrics: str) -> None:
        item = subset / "items" / item_id
        (item / "audio").mkdir(parents=True)
        (item / "lyrics.txt").write_text(lyrics, encoding="utf-8")
        module.write_jsonl(item / "ground_truth.characters.jsonl", [
            {"item_id": item_id, "character_index": index, "character": character,
             "start_sec": index * 0.5, "end_sec": index * 0.5 + 0.3}
            for index, character in enumerate(lyrics)
        ])
        (item / "audio" / "official_vocal.wav").write_bytes(b"wav")
        (item / "audio" / "mix.wav").write_bytes(b"wav")

    create_item("dev_1", "甲乙")
    calls: list[list[str]] = []

    def fake_materialize(selection, characters_by_item, **kwargs):
        calls.append([str(row["item_id"]) for row in selection])
        for row in selection:
            create_item(str(row["item_id"]), str(row["lyrics"]))

    monkeypatch.setattr(module, "materialize_mir1k_subset", fake_materialize)
    args = module.parser().parse_args([
        "--mode", "formal", "--out-root", str(tmp_path / "out"),
        "--mir1k-subset-root", str(subset),
        "--mir1k-roles", "development,quick_v2_extra,spare",
    ])
    audit: dict = {}
    rows = module.mir_rows(args, 16, audit)
    assert {row["source_item_id"] for row in rows} == {"dev_1", "spare_1"}
    assert calls == [["spare_1"]]
    assert audit["mir1k_asset_repair"]["status"] == "complete"
    assert audit["mir1k_asset_repair"]["missing_item_count_after"] == 0


def test_mir1k_missing_assets_fail_early_when_auto_materialization_disabled(tmp_path: Path) -> None:
    module = load_script("inline_manifest_mir1k_no_repair", "build_inline_realign_manifest.py")
    subset = tmp_path / "subset"
    subset.mkdir()
    module.write_jsonl(subset / "selection.jsonl", [{
        "item_id": "spare_1", "song_id": "spare_1.wav", "singer_id": "spare",
        "selection_role": "spare", "selection_order": None, "lyrics": "丙丁",
    }])
    args = module.parser().parse_args([
        "--mode", "formal", "--out-root", str(tmp_path / "out"),
        "--mir1k-subset-root", str(subset), "--mir1k-roles", "spare",
        "--no-materialize-missing-mir1k",
    ])
    try:
        module.mir_rows(args, 16, {})
    except FileNotFoundError as exc:
        assert "metadata-only rows" in str(exc)
        assert "spare_1" in str(exc)
    else:
        raise AssertionError("expected missing MIR-1K assets to fail before experiment execution")


def test_canonical_final_rows_projects_infer_slice_schema() -> None:
    module = load_script("inline_canonical_rows", "run_inline_realign_experiment.py")
    inferred = [{
        "global_character_index": 0,
        "character": "甲",
        "fixed_global_start_sec": 1.0,
        "fixed_global_end_sec": 1.2,
        "official_fixed_global_start_sec": 1.0,
        "official_fixed_global_end_sec": 1.2,
        "raw_global_start_sec": 1.0,
        "raw_global_end_sec": 1.2,
    }]
    rows = module.canonical_final_rows(inferred)
    assert rows[0]["start_sec"] == 1.0
    assert rows[0]["end_sec"] == 1.2


def test_demo_manifest_infers_language_and_balances_cap(tmp_path: Path) -> None:
    module = load_script("inline_manifest_multilingual", "build_inline_realign_manifest.py")
    fixtures = [
        ("Chinese", "中文歌"),
        ("English", "English Song"),
        ("Japanese", "日本語曲"),
        ("Cantonese", "粵語歌"),
    ]
    for language, stem in fixtures:
        parent = tmp_path / language
        parent.mkdir(parents=True)
        (parent / f"{stem}.txt").write_text("lyrics", encoding="utf-8")
        (parent / f"{stem}.mp3").write_bytes(b"media")
        prepared = parent / f"{stem}_qwen_fa" / "work" / "audio"
        prepared.mkdir(parents=True)
        (prepared / "vocals.wav").write_bytes(b"wav")
    args = module.parser().parse_args([
        "--mode", "smoke", "--out-root", str(tmp_path / "out"),
        "--demo-root", str(tmp_path), "--demo-recursive",
    ])
    audit = {}
    rows = module.demo_rows(args, 4, audit)
    assert {row["language"] for row in rows} == {"Chinese", "English", "Japanese", "Cantonese"}
    assert len({row["item_id"] for row in rows}) == 4
    assert audit["demo"]["selected_by_language"] == {
        "Cantonese": 1, "Chinese": 1, "English": 1, "Japanese": 1,
    }
    assert all(row["prepared_root"].endswith("_qwen_fa") for row in rows)


def test_branch_request_identity_includes_item_language(tmp_path: Path) -> None:
    module = load_script("inline_branch_language", "run_inline_realign_experiment.py")
    lyrics = tmp_path / "lyrics.txt"; lyrics.write_text("hello", encoding="utf-8")
    audio = tmp_path / "audio.wav"; audio.write_bytes(b"wav")
    args = SimpleNamespace(
        model="model", revision="rev", left_context_sec=10.0, right_context_sec=10.0,
        future_character_ratio=1.35, max_candidate_expansions=4,
        max_case_preview_rows=64, stable_prefix_minimum_observed_units=2,
        stable_prefix_minimum_observed_ratio=0.5, stable_segment_min_units=2,
        stable_segment_confidence_quantile=0.5, stable_raw_official_tolerance_sec=0.16,
        stable_context_tolerance_sec=0.24,
    )
    item = {
        "item_id": "demo_English_x", "dataset": "demo", "profile": "long_serial",
        "language": "English", "lyrics_path": str(lyrics), "audio_path": str(audio),
    }
    request = module.branch_request(
        args, item, "B2_30_silence_official", module.VARIANTS["B2_30_silence_official"],
        {"kind": "checkpoint"},
    )
    assert request["language"] == "English"
    assert "gt_path" not in request
    assert "gt_sha256" not in request


def test_evaluation_identity_changes_with_gt_without_changing_inference(tmp_path: Path) -> None:
    module = load_script("inline_evaluation_identity", "run_inline_realign_experiment.py")
    gt_a = tmp_path / "a.jsonl"
    gt_b = tmp_path / "b.jsonl"
    gt_a.write_text('{"character_index":0,"start_sec":0.0,"end_sec":1.0}\n', encoding="utf-8")
    gt_b.write_text('{"character_index":0,"start_sec":0.1,"end_sec":1.1}\n', encoding="utf-8")
    first = module.evaluation_request({"gt_path": str(gt_a)}, "same-inference")
    second = module.evaluation_request({"gt_path": str(gt_b)}, "same-inference")
    assert first["inference_request_hash"] == second["inference_request_hash"]
    assert first["gt_sha256"] != second["gt_sha256"]
    assert module.canonical_hash(first) != module.canonical_hash(second)


def test_detector_gt_available_is_independent_of_error_count() -> None:
    module = load_script("inline_detector_gt_available", "run_inline_realign_experiment.py")
    result = module.detector_gt_overlap_summary([], [], total_units=10, gt_available=True)
    assert result["gt_available"] is True
    assert result["gt_error_case_count"] == 0
    assert result["case_precision"] is None
    assert result["case_recall"] is None


def test_formal_demo_default_consumes_all_discovered_items(tmp_path: Path) -> None:
    module = load_script("inline_manifest_all_demo", "build_inline_realign_manifest.py")
    for language, count in (("Chinese", 5), ("English", 3)):
        parent = tmp_path / language
        parent.mkdir(parents=True)
        for index in range(count):
            stem = f"song_{index}"
            (parent / f"{stem}.txt").write_text("lyrics", encoding="utf-8")
            (parent / f"{stem}.mp3").write_bytes(b"media")
            prepared = parent / f"{stem}_qwen_fa" / "work" / "audio"
            prepared.mkdir(parents=True)
            (prepared / "vocals.wav").write_bytes(b"wav")
    args = module.parser().parse_args([
        "--mode", "formal", "--out-root", str(tmp_path / "out"),
        "--demo-root", str(tmp_path), "--demo-recursive",
    ])
    assert args.demo_cap is None
    assert args.demo_per_language_cap is None
    audit = {}
    rows = module.demo_rows(args, None, audit)
    assert len(rows) == 8
    assert audit["demo"]["selection_policy"] == "all_discovered_items"


def test_smoke_demo_default_is_dynamic_one_per_discovered_language(tmp_path: Path) -> None:
    module = load_script("inline_manifest_smoke_dynamic", "build_inline_realign_manifest.py")
    args = module.parser().parse_args(["--mode", "smoke", "--out-root", str(tmp_path / "out")])
    # main() assigns the dynamic default; no hard total song count is encoded in the parser.
    assert args.demo_cap is None
    assert args.demo_per_language_cap is None


def test_detector_gt_overlap_reports_case_and_unit_metrics() -> None:
    module = load_script("inline_detector_overlap", "run_inline_realign_experiment.py")
    automatic = [
        {"character_start": 2, "character_end": 4},
        {"character_start": 10, "character_end": 11},
    ]
    oracle = [
        {"character_start": 3, "character_end": 5},
        {"character_start": 20, "character_end": 21},
    ]
    result = module.detector_gt_overlap_summary(automatic, oracle, total_units=30)
    assert result["automatic_case_hit_count"] == 1
    assert result["gt_error_case_detected_count"] == 1
    assert result["case_precision"] == 0.5
    assert result["case_recall"] == 0.5
    assert result["overlap_unit_count"] == 2


def test_three_context_consensus_accepts_plus2_plus4_when_exact_disagrees(monkeypatch) -> None:
    module = load_script("inline_three_context", "run_inline_realign_experiment.py")

    def fake_agreement(left, right, indices, *, tolerance_sec):
        left_name = left[0]["trial"]
        right_name = right[0]["trial"]
        supported = {left_name, right_name} == {"plus2", "plus4"}
        return {"supported": supported, "max_boundary_delta_sec": 0.0 if supported else 1.0}

    monkeypatch.setattr(module, "agreement_between_trials", fake_agreement)
    trials = {
        name: {"decoded_rows": [{"trial": name}]}
        for name in ("exact", "plus2", "plus4")
    }
    result = module.three_context_consensus(trials, [0], tolerance_sec=0.24)
    assert result["supported"] is True
    assert result["selected_trial"] == "plus2"
    assert result["supported_pairs"] == [["plus2", "plus4"]]


def test_clean_control_spans_are_interior_and_bounded() -> None:
    module = load_script("inline_clean_controls", "run_inline_realign_experiment.py")
    rows = [row(index, index * 0.4, index * 0.4 + 0.2) for index in range(18)]
    gt = [
        {"character_index": index, "start_sec": source["start_sec"], "end_sec": source["end_sec"]}
        for index, source in enumerate(rows)
    ]
    spans = module.clean_control_spans(rows, gt, threshold_sec=0.08, minimum_units=2, limit=2)
    assert spans
    assert all(span["candidate_source"] == "clean_control" for span in spans)
    assert all(span["character_start"] > 0 for span in spans)
    assert all(span["character_end"] < len(rows) - 1 for span in spans)


def test_publish_demo_outputs_uses_symlinks_without_duplicate_video(tmp_path: Path) -> None:
    module = load_script("inline_publish", "publish_inline_realign_demo_outputs.py")
    experiment = tmp_path / "experiment"
    item = experiment / "items" / "demo_English_song"
    alignment = item / "branches" / "B2_30_silence_official" / "alignment.json"
    render = item / "render" / "official.mp4"
    alignment.parent.mkdir(parents=True)
    render.parent.mkdir(parents=True)
    alignment.write_text("{}", encoding="utf-8")
    render.write_bytes(b"video")
    (item / "item_summary.json").write_text("{}", encoding="utf-8")
    (experiment / "experiment_summary.json").write_text("{}", encoding="utf-8")
    source = tmp_path / "test" / "English"
    source.mkdir(parents=True)
    manifest = experiment / "experiment_manifest.jsonl"
    manifest.write_text(json.dumps({
        "dataset": "demo", "item_id": "demo_English_song", "language": "English",
        "demo_source_directory": str(source), "demo_source_stem": "song",
        "source_media_path": str(source / "song.mp3"),
    }) + "\n", encoding="utf-8")
    old_argv = module.argparse.sys.argv if hasattr(module.argparse, "sys") else None
    import sys
    previous = sys.argv
    try:
        sys.argv = [
            "publish", "--manifest", str(manifest), "--experiment-root", str(experiment),
            "--layout", "adjacent",
        ]
        assert module.main() == 0
    finally:
        sys.argv = previous
    published = source / "song_inline_realign" / "official.mp4"
    assert published.is_symlink()
    assert published.resolve() == render.resolve()
    assert (source / "song_inline_realign" / "publish_manifest.json").is_file()


def test_m4_long_targets_are_multiple_duration_buckets() -> None:
    module = load_script("inline_m4_targets", "build_inline_realign_manifest.py")
    args = module.parser().parse_args([
        "--mode", "formal", "--out-root", "/tmp/o",
        "--m4-long-target-secs", "60,120,180,120",
    ])
    assert module._m4_long_targets(args) == [60.0, 120.0, 180.0]
