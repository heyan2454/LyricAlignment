from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

from lyricalign.demo.realign_diagnostics import bounded_splice, select_anchor_pair

ROOT = Path(__file__).resolve().parents[1]


def load_serial_module():
    path = ROOT / "scripts" / "demo" / "align_qwen_fa_serial_demo.py"
    spec = importlib.util.spec_from_file_location("serial_demo_patch_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_zero_decoder_movement_is_valid_a4_stability_evidence() -> None:
    rows = []
    for index in range(5):
        rows.append({
            "global_character_index": index,
            "selected_start_sec": float(index),
            "selected_end_sec": float(index) + 0.5,
            "confidence_margin_min": 0.9,
            "overlap_observation_count": 2,
            "overlap_fixed_start_range_sec": 0.0,
            "overlap_fixed_end_range_sec": 0.0,
            "raw_decoded_movement_max_sec": 0.0,
            "compressed": False,
            "collapsed": False,
        })
    policy = {
        "family": "A4",
        "confidence_margin_min": 0.8,
        "overlap_tolerance_sec": 0.16,
        "stability_tolerance_sec": 0.08,
    }
    left, right, _ = select_anchor_pair(
        rows, policy, 2, 2,
        max_distance_units=4, max_pair_span_units=8, max_pair_span_sec=8.0, guard_units=0,
    )
    assert left is not None and left["global_character_index"] == 1
    assert right is not None and right["global_character_index"] == 3


def test_official_control_projection_does_not_replace_raw_evidence() -> None:
    serial = load_serial_module()
    rows = [{
        "global_character_index": 0,
        "raw_local_start_sec": 0.8,
        "raw_local_end_sec": 1.0,
        "raw_global_start_sec": 10.8,
        "raw_global_end_sec": 11.0,
        "official_fixed_local_start_sec": 1.2,
        "official_fixed_local_end_sec": 1.5,
        "official_fixed_global_start_sec": 11.2,
        "official_fixed_global_end_sec": 11.5,
        "fixed_local_start_sec": 0.8,
        "fixed_local_end_sec": 1.0,
        "fixed_global_start_sec": 10.8,
        "fixed_global_end_sec": 11.0,
    }]
    projected = serial.project_rows_for_decoder(rows, "official")[0]
    assert projected["fixed_global_start_sec"] == 11.2
    assert projected["fixed_global_end_sec"] == 11.5
    assert projected["raw_global_start_sec"] == 10.8
    assert rows[0]["fixed_global_start_sec"] == 10.8


def test_vocal_activity_profile_skips_only_near_silence() -> None:
    serial = load_serial_module()
    audio = np.zeros(16000 * 4, dtype=np.float32)
    audio[16000 * 2:16000 * 3] = 0.1 * np.sin(
        2 * np.pi * 220 * np.arange(16000, dtype=np.float32) / 16000
    )
    profile = serial.build_vocal_activity_profile(audio)
    silent = serial.vocal_activity_for_interval(profile, 0.0, 1.0)
    active = serial.vocal_activity_for_interval(profile, 2.0, 3.0)
    assert silent["active_ratio"] < active["active_ratio"]
    assert silent["peak_db"] < silent["threshold_db"] + 3.0
    assert active["peak_db"] > active["threshold_db"] + 3.0

    quiet_constant = np.full(16000, 10 ** (-45 / 20), dtype=np.float32)
    quiet_profile = serial.build_vocal_activity_profile(quiet_constant)
    quiet = serial.vocal_activity_for_interval(quiet_profile, 0.0, 1.0)
    assert quiet["active_ratio"] > 0.5


def test_isotonic_local_projection_preserves_non_target_rows_and_order() -> None:
    baseline = [
        {"global_character_index": 0, "start_sec": 0.0, "end_sec": 1.0},
        {"global_character_index": 1, "start_sec": 1.0, "end_sec": 1.5},
        {"global_character_index": 2, "start_sec": 1.5, "end_sec": 2.0},
        {"global_character_index": 3, "start_sec": 3.0, "end_sec": 3.5},
    ]
    replacement = [
        {"global_character_index": 1, "start_sec": 2.6, "end_sec": 1.4},
        {"global_character_index": 2, "start_sec": 1.2, "end_sec": 3.4},
    ]
    output, diagnostic = bounded_splice(
        baseline, replacement,
        replace_start=1, replace_end=2, remerge=True,
        projection="isotonic", minimum_duration_sec=0.0,
    )
    assert diagnostic["valid"]
    assert output[0] == baseline[0]
    assert output[3] == baseline[3]
    assert output[1]["start_sec"] >= baseline[0]["end_sec"]
    assert output[1]["end_sec"] <= output[2]["start_sec"] + 1e-9
    assert output[2]["end_sec"] <= baseline[3]["start_sec"] + 1e-9
    assert output[1]["quick_realign_projection"] == "isotonic"


def load_script(name: str, filename: str):
    path = ROOT / "scripts" / "demo" / filename
    scripts_dir = str(path.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_trajectory_projection_ignores_output_timestamp_values() -> None:
    module = load_script(
        "decoder_realign_comparison_patch_test_module",
        "align_qwen_fa_decoder_realign_comparison.py",
    )
    base = [{
        "window_index": 0,
        "input_character_start_before": 0,
        "committed_cursor_before": 0,
        "committed_cursor_after": 2,
        "candidate_character_start": 0,
        "candidate_character_end": 4,
        "committed_character_start": 0,
        "committed_character_end": 2,
        "next_window_input_character_start": 1,
        "next_uncommitted_character_start": 2,
        "shadow_rows": [{"fixed_global_start_sec": 1.0}],
        "attempts": [{
            "status": "accepted",
            "candidate_character_start": 0,
            "candidate_character_end": 4,
            "committed_prefix_count": 2,
            "next_window_input_character_start": 1,
        }],
    }]
    changed = [{**base[0], "shadow_rows": [{"fixed_global_start_sec": 99.0}]}]
    assert module.trajectory_projection(base) == module.trajectory_projection(changed)


def test_reuse_prepared_suffix_resolves_existing_audio(tmp_path: Path) -> None:
    module = load_script(
        "decoder_realign_batch_patch_test_module",
        "run_decoder_realign_comparison_batch.py",
    )
    source = tmp_path / "song_qwen_fa" / "work" / "audio"
    source.mkdir(parents=True)
    for name in ("mix.wav", "vocals.wav", "accompaniment.wav"):
        (source / name).write_bytes(b"x")
    job = type("Job", (), {"parent": tmp_path, "stem": "song"})()
    paths = module.reused_prepared_paths(job, "_qwen_fa")
    assert paths["mix"] == source / "mix.wav"
    assert paths["vocal"] == source / "vocals.wav"


def test_collector_severity_fallback_focuses_on_zero_and_modified_rows() -> None:
    module = load_script(
        "decoder_realign_collector_patch_test_module",
        "collect_decoder_realign_evidence.py",
    )
    ordinary = {"duration": 0.08, "overlap_compressed": False, "realign_projection": None}
    zero = {"duration": 0.0, "compressed_to_zero": True, "realign_projection": None}
    changed = {"duration": 0.2, "compressed_to_zero": False, "realign_projection": "isotonic"}
    assert module.is_anomaly(ordinary)
    assert not module.is_severe(ordinary)
    assert module.is_severe(zero)
    assert module.is_severe(changed)


def test_activity_profile_reports_sustained_onset_after_long_intro() -> None:
    serial = load_serial_module()
    audio = np.zeros(16000 * 6, dtype=np.float32)
    tone = 0.1 * np.sin(2 * np.pi * 220 * np.arange(16000 * 2, dtype=np.float32) / 16000)
    audio[16000 * 3:16000 * 5] = tone
    profile = serial.build_vocal_activity_profile(audio)
    assert profile["first_sustained_activity_sec"] is not None
    assert 2.5 <= profile["first_sustained_activity_sec"] <= 3.5
    intro = serial.vocal_activity_for_interval(profile, 0.0, 2.0)
    vocal = serial.vocal_activity_for_interval(profile, 3.0, 5.0)
    assert intro["sustained_active_duration_sec"] < 0.4
    assert vocal["sustained_active_duration_sec"] > 1.0


def test_comparison_uses_raw_shared_planner_design() -> None:
    module = load_script(
        "decoder_realign_comparison_shared_planner_test_module",
        "align_qwen_fa_decoder_realign_comparison.py",
    )
    args = module.parser().parse_args([
        "--lyrics", "/tmp/x.txt", "--audio", "/tmp/x.wav", "--out-root", "/tmp/out",
    ])
    raw = module.branch_args(args, "raw")
    assert raw.decoder_kind == "raw"
    assert raw.serial_control_decoder_kind == "same"


def test_shared_trace_replay_changes_decoder_not_ownership() -> None:
    module = load_script(
        "decoder_realign_comparison_replay_test_module",
        "align_qwen_fa_decoder_realign_comparison.py",
    )
    document = type("Document", (), {
        "characters": [
            type("Char", (), {
                "global_index": 0, "text": "甲", "unit_type": "cjk_character",
                "line_index": 0, "index_in_line": 0, "display_prefix": "",
                "display_text": "甲", "display_suffix": "",
            })(),
            type("Char", (), {
                "global_index": 1, "text": "乙", "unit_type": "cjk_character",
                "line_index": 0, "index_in_line": 1, "display_prefix": "",
                "display_text": "乙", "display_suffix": "",
            })(),
        ],
    })()
    base_rows = []
    for index in range(2):
        base_rows.append({
            "global_character_index": index,
            "character": "甲乙"[index],
            "raw_local_start_sec": float(index),
            "raw_local_end_sec": float(index) + 0.5,
            "raw_global_start_sec": float(index),
            "raw_global_end_sec": float(index) + 0.5,
            "official_fixed_local_start_sec": 0.0,
            "official_fixed_local_end_sec": 0.0 if index == 0 else 1.5,
            "official_fixed_global_start_sec": 0.0,
            "official_fixed_global_end_sec": 0.0 if index == 0 else 1.5,
            "fixed_local_start_sec": float(index),
            "fixed_local_end_sec": float(index) + 0.5,
            "fixed_global_start_sec": float(index),
            "fixed_global_end_sec": float(index) + 0.5,
        })
    trace = [{
        "window_index": 0,
        "core_start_sec": 0.0,
        "core_end_sec": 30.0,
        "committed_character_start": 0,
        "committed_character_end": 2,
        "shadow_rows": base_rows,
        "silent_core_skipped": False,
    }]
    raw_trace = module.project_trace_for_decoder(trace, "raw")
    official_trace = module.project_trace_for_decoder(trace, "official")
    raw = module.replay_decoder_on_shared_trace(
        raw_trace, decoder_kind="raw", document=document,
        duration_sec=30.0, seam_tolerance_sec=0.16,
    )
    official = module.replay_decoder_on_shared_trace(
        official_trace, decoder_kind="official", document=document,
        duration_sec=30.0, seam_tolerance_sec=0.16,
    )
    assert [row["owner_window_index"] for row in raw] == [0, 0]
    assert [row["owner_window_index"] for row in official] == [0, 0]
    assert raw[0]["end_sec"] == 0.5
    assert official[0]["end_sec"] == 0.0


def test_pairwise_rendering_is_opt_in() -> None:
    module = load_script(
        "decoder_realign_render_default_test_module",
        "render_decoder_realign_comparison.py",
    )
    args = module.parser().parse_args([
        "--alignment-root", "/tmp/a", "--mix-audio", "/tmp/m.wav", "--out-root", "/tmp/o",
    ])
    assert args.render_pairs is False


def _profile_from_sustained(mask: list[bool], hop_sec: float = 1.0) -> dict:
    import numpy as _np
    values = _np.asarray(mask, dtype=bool)
    return {
        "hop_sec": hop_sec,
        "sustained": values,
        "active": values,
        "frame_db": _np.where(values, -20.0, -80.0),
        "threshold_db": -40.0,
        "reliable_threshold_db": -35.0,
    }


def test_silence_aware_plan_skips_long_intro_and_keeps_anchor() -> None:
    from lyricalign.demo.window_planning import build_silence_aware_window_plan

    profile = _profile_from_sustained([False] * 40 + [True] * 70)
    plan = build_silence_aware_window_plan(
        110.0, profile, target_core_sec=30.0,
        left_context_sec=10.0, right_context_sec=10.0,
        min_silence_sec=0.8, leading_silence_min_sec=2.0,
        tail_min_core_sec=18.0,
    )
    assert plan["active_span_start_sec"] == 40.0
    assert plan["leading_silence_skipped"]["start_sec"] == 0.0
    assert plan["leading_silence_skipped"]["end_sec"] == 40.0
    assert plan["windows"][0]["core_start_sec"] == 40.0
    assert plan["windows"][0]["input_start_sec"] == 30.0


def test_short_tail_is_shared_by_two_previous_windows() -> None:
    from lyricalign.demo.window_planning import build_silence_aware_window_plan

    profile = _profile_from_sustained([False] * 10 + [True] * 70)
    plan = build_silence_aware_window_plan(
        80.0, profile, target_core_sec=30.0,
        left_context_sec=10.0, right_context_sec=10.0,
        boundary_search_sec=0.0, tail_min_core_sec=18.0,
    )
    assert plan["initial_boundaries_sec"] == [10.0, 40.0, 70.0, 80.0]
    assert plan["final_boundaries_sec"] == [10.0, 45.0, 80.0]
    assert [row["core_duration_sec"] for row in plan["windows"]] == [35.0, 35.0]
    assert plan["tail_adjustment"]["action"] == "distribute_tail_across_two_previous_windows"


def test_short_tail_with_one_previous_window_is_merged() -> None:
    from lyricalign.demo.window_planning import build_silence_aware_window_plan

    profile = _profile_from_sustained([True] * 40)
    plan = build_silence_aware_window_plan(
        40.0, profile, target_core_sec=30.0,
        left_context_sec=10.0, right_context_sec=10.0,
        boundary_search_sec=0.0, tail_min_core_sec=18.0,
    )
    assert plan["final_boundaries_sec"] == [0.0, 40.0]
    assert plan["tail_adjustment"]["action"] == "merge_tail_with_only_previous_window"


def test_strong_silence_marks_adjacent_character_anchors() -> None:
    from lyricalign.demo.raw_guarded import attach_silence_anchor_evidence

    rows = [
        {"global_character_index": 0, "selected_start_sec": 0.0, "selected_end_sec": 1.0, "collapsed": False},
        {"global_character_index": 1, "selected_start_sec": 3.0, "selected_end_sec": 4.0, "collapsed": False},
    ]
    marked = attach_silence_anchor_evidence(rows, [{
        "silence_id": "s0", "start_sec": 1.0, "end_sec": 3.0,
        "duration_sec": 2.0, "strength": "strong",
    }])
    assert marked[0]["silence_anchor_after"]["silence_id"] == "s0"
    assert marked[1]["silence_anchor_before"]["silence_id"] == "s0"
    assert marked[0]["silence_anchor_strength"] == "strong"
