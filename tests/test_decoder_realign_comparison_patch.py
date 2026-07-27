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


def test_comparison_branches_use_their_own_serial_decoder() -> None:
    module = load_script(
        "decoder_realign_comparison_own_trajectory_test_module",
        "align_qwen_fa_decoder_realign_comparison.py",
    )
    args = module.parser().parse_args([
        "--lyrics", "/tmp/x.txt", "--audio", "/tmp/x.wav", "--out-root", "/tmp/out",
    ])
    official = module.branch_args(args, "official")
    raw = module.branch_args(args, "raw")
    assert official.serial_control_decoder_kind == "same"
    assert raw.serial_control_decoder_kind == "same"


def test_pairwise_rendering_is_opt_in() -> None:
    module = load_script(
        "decoder_realign_render_default_test_module",
        "render_decoder_realign_comparison.py",
    )
    args = module.parser().parse_args([
        "--alignment-root", "/tmp/a", "--mix-audio", "/tmp/m.wav", "--out-root", "/tmp/o",
    ])
    assert args.render_pairs is False
