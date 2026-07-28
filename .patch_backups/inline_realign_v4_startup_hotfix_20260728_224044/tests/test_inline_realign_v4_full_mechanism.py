from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lyricalign.demo.run_state import RunState, canonical_hash
from lyricalign.demo.visual_diagnostics import duration_bin_labels, duration_pmf
from lyricalign.demo.window_planning import (
    build_strict_silence_boundary_window_plan,
    compress_silence_audio,
    map_compressed_time_to_original,
)


def _activity_profile(duration: float = 12.0, hop: float = 1.0) -> dict:
    # Active 0-4, strict silence 4-7, active 7-12.
    return {"hop_sec": hop, "sustained": [True, True, True, True, False, False, False, True, True, True, True, True]}


def test_strict_silence_windows_never_cross_gap() -> None:
    plan = build_strict_silence_boundary_window_plan(
        12.0,
        _activity_profile(),
        target_core_sec=3.0,
        left_context_sec=2.0,
        right_context_sec=2.0,
        min_silence_sec=1.0,
        strong_silence_sec=2.0,
        strict_silence_sec=2.0,
        minimum_core_sec=1.0,
        tail_min_core_sec=1.0,
    )
    assert plan["strict_silence_intervals"]
    assert plan["active_span_duration_sec"] == pytest.approx(9.0)
    assert {row["region_index"] for row in plan["windows"]} == {0, 1}
    region_finals = [row for row in plan["windows"] if row["is_final_region_core"]]
    assert len(region_finals) == 2
    assert region_finals[0]["is_final_core"] is False
    assert region_finals[0]["strict_boundary_cursor_policy"] == "continue_from_committed_cursor_after_region"
    assert region_finals[-1]["is_final_core"] is True
    for row in plan["windows"]:
        assert row["strict_region_start_sec"] <= row["input_start_sec"]
        assert row["input_end_sec"] <= row["strict_region_end_sec"]
        assert row["context_crosses_strict_silence"] is False
        assert not (row["input_start_sec"] < 4.0 and row["input_end_sec"] > 7.0)


def test_silence_compression_mapping_is_reversible_on_kept_audio() -> None:
    audio = np.arange(12 * 16000, dtype=np.float32)
    compressed, mapping = compress_silence_audio(
        audio,
        _activity_profile(),
        min_silence_sec=1.0,
        strong_silence_sec=2.0,
        remove_silence_sec=2.0,
        keep_edge_padding_sec=0.0,
    )
    assert len(compressed) == 9 * 16000
    assert mapping["removed_duration_sec"] == pytest.approx(3.0)
    assert map_compressed_time_to_original(3.0, mapping) == pytest.approx(3.0)
    assert map_compressed_time_to_original(4.0, mapping, boundary_side="left") == pytest.approx(4.0)
    assert map_compressed_time_to_original(4.0, mapping, boundary_side="right") == pytest.approx(7.0)
    assert map_compressed_time_to_original(4.5, mapping) == pytest.approx(7.5)
    assert map_compressed_time_to_original(9.0, mapping) == pytest.approx(12.0)


def test_duration_pmf_keeps_negative_zero_positive_in_one_denominator() -> None:
    rows = [
        {"global_character_index": 0, "start_sec": 1.0, "end_sec": 0.9},
        {"global_character_index": 1, "start_sec": 1.0, "end_sec": 1.0},
        {"global_character_index": 2, "start_sec": 1.0, "end_sec": 1.01},
        {"global_character_index": 3, "start_sec": 1.0, "end_sec": 1.50},
    ]
    result = duration_pmf(rows)
    labels = duration_bin_labels()
    assert labels[0] == "<0"
    assert labels[1] == "=0"
    assert result["counts"][0] == 1
    assert result["counts"][1] == 1
    assert sum(result["counts"]) == 4
    assert sum(result["probabilities"]) == pytest.approx(1.0)


def test_run_state_requires_identical_identity_and_outputs(tmp_path: Path) -> None:
    state = RunState(tmp_path)
    identity = {"config": {"core": 30}, "model": "x"}
    state.initialize(identity, resume=False)
    output = tmp_path / "artifact.json"
    request = {"stage": "experiment", "identity": canonical_hash(identity)}
    request_hash = state.begin_stage("experiment", request=request, outputs=[output])
    output.write_text("{}\n", encoding="utf-8")
    state.finish_stage("experiment", status="complete", request_hash=request_hash, outputs=[output], returncode=0)
    assert state.stage_is_complete("experiment", request_hash=request_hash, outputs=[output])
    state.initialize(identity, resume=True)
    with pytest.raises(RuntimeError, match="identity mismatch"):
        state.initialize({"config": {"core": 60}, "model": "x"}, resume=True)
    output.unlink()
    assert not state.stage_is_complete("experiment", request_hash=request_hash, outputs=[output])


def test_canonical_metric_penalizes_missing_prediction(tmp_path: Path) -> None:
    # Load the script module without requiring a model runtime.
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "demo" / "run_inline_realign_experiment.py"
    spec = importlib.util.spec_from_file_location("inline_exp_v4_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    gt = [
        {"character_index": 0, "character": "你", "start_sec": 0.0, "end_sec": 0.1},
        {"character_index": 1, "character": "好", "start_sec": 0.1, "end_sec": 0.2},
    ]
    pred = [
        {"global_character_index": 0, "character": "你", "start_sec": 0.0, "end_sec": 0.1},
    ]
    result = module.metrics_without_details(pred, gt)
    assert result["metric_schema_version"] == "character_interval_metrics_v3_tolerant"
    assert result["missing_prediction_count"] == 1
    assert result["character_coverage"] == pytest.approx(0.5)
    assert result["boundary_mae_sec"] > result["valid_only_boundary_mae_sec"]


def _load_script_module(name: str, relative: str):
    import importlib.util
    script = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_branch_summary_weights_canonical_full_reference_count(tmp_path: Path) -> None:
    module = _load_script_module(
        "inline_summary_v4_test", "scripts/demo/summarize_inline_realign_followup.py"
    )
    item_root = tmp_path / "items" / "x" / "branches" / "B2_30_silence_official"
    item_root.mkdir(parents=True)
    (item_root / "alignment.json").write_text(
        json.dumps({"characters": [{"global_character_index": 0, "start_sec": 0.0, "end_sec": 0.1}]}) + "\n",
        encoding="utf-8",
    )
    (item_root / "summary.json").write_text(
        json.dumps({
            "variant": "B2_30_silence_official",
            "character_count": 1,
            "gt": {
                "metric_schema_version": "character_interval_metrics_v3_tolerant",
                "character_count": 10,
                "valid_prediction_count": 1,
                "all_item_penalized_boundary_mae_sec": 0.9,
                "boundary_mae_sec": 0.9,
            },
        }) + "\n",
        encoding="utf-8",
    )
    rows = module.branch_aggregates(tmp_path, [{"item_id": "x", "dataset": "d", "language": "Chinese"}])
    total = next(row for row in rows if row["dataset"] == "__TOTAL__")
    assert total["gt_character_count"] == 10
    assert total["gt_boundary_mae_micro_sec"] == pytest.approx(0.9)
    assert total["metric_schema_version"] == "character_interval_metrics_v3_tolerant"


def test_timeline_track_can_carry_its_own_window_plan(tmp_path: Path) -> None:
    from lyricalign.demo.visual_diagnostics import render_timeline_page

    output = tmp_path / "timeline.png"
    rows = [
        {"global_character_index": 0, "character": "A", "start_sec": 0.2, "end_sec": 0.5},
        {"global_character_index": 1, "character": "B", "start_sec": 0.5, "end_sec": 0.5},
        {"global_character_index": 2, "character": "C", "start_sec": 0.8, "end_sec": 0.7},
    ]
    windows = [{
        "window_index": 0,
        "core_start_sec": 0.0,
        "core_end_sec": 1.0,
        "input_start_sec": 0.0,
        "input_end_sec": 1.2,
        "window_plan_policy": "strict_silence_boundary_v1",
        "strict_region_start_sec": 0.0,
        "strict_region_end_sec": 1.2,
    }]
    meta = render_timeline_page(
        output=output,
        tracks=[("方案A", rows, windows)],
        windows=[],
        start=0.0,
        end=1.2,
        title="test",
        pixel_width=900,
        pixel_height=500,
    )
    assert output.is_file() and output.stat().st_size > 0
    assert meta["width"] == 900


def test_visualizer_resolves_authoritative_primary_and_matrix(tmp_path: Path) -> None:
    module = _load_script_module(
        "inline_visual_v4_test", "scripts/demo/analyze_inline_realign_visuals.py"
    )
    (tmp_path / "resolved_config.json").write_text(json.dumps({
        "source_config": {"variants": {"primary": "B1_30_fixed_official"}},
        "effective": {
            "primary_variant": "B1_30_fixed_official",
            "baseline_matrix_variants": "B1_30_fixed_official,B5_30_strict_silence_official",
        },
    }) + "\n", encoding="utf-8")
    primary, matrix = module.resolved_variant_settings(tmp_path)
    assert primary == "B1_30_fixed_official"
    assert matrix == ["B1_30_fixed_official", "B5_30_strict_silence_official"]


def test_yaml_window_matrix_matches_experiment_variant_registry() -> None:
    import yaml
    experiment = _load_script_module(
        "inline_exp_variant_registry_test", "scripts/demo/run_inline_realign_experiment.py"
    )
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "configs/experiments/inline_realign_multilingual_smoke_20260728.yaml",
        "configs/experiments/inline_realign_multilingual_formal_20260728.yaml",
    ):
        payload = yaml.safe_load((root / relative).read_text(encoding="utf-8"))
        configured = [payload["variants"]["primary"], *payload["variants"]["window_matrix"], payload["variants"]["raw_control"]]
        unknown = [name for name in configured if name not in experiment.VARIANTS]
        assert unknown == []


def test_run_state_rejects_modified_same_path_output(tmp_path: Path) -> None:
    state = RunState(tmp_path)
    identity = {"config": "v4"}
    state.initialize(identity, resume=False)
    output = tmp_path / "artifact.json"
    request = {"stage": "visualization"}
    request_hash = state.begin_stage("visualization", request=request, outputs=[output])
    output.write_text('{"a":1}\n', encoding="utf-8")
    state.finish_stage("visualization", status="complete", request_hash=request_hash, outputs=[output])
    assert state.stage_is_complete("visualization", request_hash=request_hash, outputs=[output])
    # Preserve path and byte length but change the file identity timestamp/content.
    output.write_text('{"b":2}\n', encoding="utf-8")
    assert not state.stage_is_complete("visualization", request_hash=request_hash, outputs=[output])


def test_decoder_summary_uses_resolved_primary_variant(tmp_path: Path) -> None:
    module = _load_script_module(
        "inline_summary_primary_v4_test", "scripts/demo/summarize_inline_realign_followup.py"
    )
    (tmp_path / "resolved_config.json").write_text(json.dumps({
        "effective": {"primary_variant": "B1_30_fixed_official"},
    }) + "\n", encoding="utf-8")
    branch = tmp_path / "items" / "x" / "branches" / "B1_30_fixed_official"
    branch.mkdir(parents=True)
    payload = {"characters": [{"global_character_index": 0, "start_sec": 0.0, "end_sec": 0.1}]}
    (branch / "alignment.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    result = module.decoder_stage_aggregates(tmp_path, [{"item_id": "x"}])
    assert result["primary_variant"] == "B1_30_fixed_official"
    assert any(row["stage"] == "D4_final_committed" for row in result["stage_results"])


def test_visual_source_identity_changes_when_alignment_changes(tmp_path: Path) -> None:
    module = _load_script_module(
        "inline_visual_identity_v4_test", "scripts/demo/analyze_inline_realign_visuals.py"
    )
    (tmp_path / "resolved_config.json").write_text("{}\n", encoding="utf-8")
    item_root = tmp_path / "items" / "x"
    branch = item_root / "branches" / "B2_30_silence_official"
    branch.mkdir(parents=True)
    alignment = branch / "alignment.json"
    alignment.write_text('{"characters":[]}\n', encoding="utf-8")
    first = canonical_hash(module.visual_source_identity(tmp_path, item_root))
    alignment.write_text('{"characters":[1]}\n', encoding="utf-8")
    second = canonical_hash(module.visual_source_identity(tmp_path, item_root))
    assert first != second


def test_itemized_stage_resume_enters_controller_even_when_top_summary_is_complete(tmp_path: Path) -> None:
    module = _load_script_module(
        "inline_pipeline_itemized_resume_test", "scripts/demo/run_inline_realign_pipeline.py"
    )
    from lyricalign.demo.run_state import RunState
    import sys

    root = tmp_path / "run"
    root.mkdir()
    state = RunState(root)
    state.initialize({"run": "x"}, resume=False)
    expected = root / "experiment_summary.json"
    expected.write_text('{}\n', encoding="utf-8")
    request = {"command": "mock"}
    request_hash = state.begin_stage("experiment", request=request, outputs=[expected])
    state.finish_stage(
        "experiment", status="complete", request_hash=request_hash,
        outputs=[expected], returncode=0,
    )
    marker = root / "controller_entered.txt"
    script = root / "controller.py"
    script.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('yes')\n"
        f"Path({str(expected)!r}).write_text('{{}}\\n')\n",
        encoding="utf-8",
    )
    module.run_stage(
        name="experiment", command=[sys.executable, str(script)], root=root,
        status_path=root / "pipeline_status.jsonl", state=state,
        request=request, expected_outputs=[expected], resume=True,
        allow_stage_resume_skip=False,
    )
    assert marker.read_text(encoding="utf-8") == "yes"


def test_script_identity_ignores_mtime_but_keeps_sha256(tmp_path: Path) -> None:
    module = _load_script_module(
        "inline_pipeline_script_identity_test", "scripts/demo/run_inline_realign_pipeline.py"
    )
    script = module.ROOT / "scripts" / "demo" / "run_inline_realign_pipeline.py"
    identity = module._script_identity([script])
    row = identity[str(script.relative_to(module.ROOT))]
    assert "sha256" in row
    assert "mtime_ns" not in row


def test_pipeline_yaml_controls_full_variant_and_mechanism_settings(tmp_path: Path) -> None:
    module = _load_script_module(
        "inline_pipeline_config_v4_test", "scripts/demo/run_inline_realign_pipeline.py"
    )
    root = Path(__file__).resolve().parents[1]
    config = root / "configs/experiments/inline_realign_multilingual_formal_20260728.yaml"
    argv = [
        "--mode", "formal", "--config", str(config), "--out-root", str(tmp_path / "out"),
        "--mir1k-subset-root", str(tmp_path / "mir"), "--m4-labels", str(tmp_path / "m4.jsonl"),
        "--m4-audio-root", str(tmp_path / "audio"), "--model", "model", "--revision", "rev",
        "--r2-checkpoint", str(tmp_path / "ckpt"),
    ]
    args = module.parser().parse_args(argv)
    payload = module._apply_config(args, argv)
    assert payload["variants"]["primary"] == "B2_30_silence_official"
    assert "B5_30_strict_silence_official" in args.baseline_matrix_variants
    assert "C0_30_silence_compressed_diagnostic" in args.baseline_matrix_variants
    assert args.strict_silence_boundary_sec == pytest.approx(1.5)
    assert args.text_dosage_trials is True
    assert args.pending_confirmation_shadow is True
    assert args.text_dosage_end_deltas == "-8,-4,-2,0,2,4,8,16"


def test_partial_stage_is_not_resume_complete(tmp_path: Path) -> None:
    module = _load_script_module(
        "inline_pipeline_stage_v4_test", "scripts/demo/run_inline_realign_pipeline.py"
    )
    state = RunState(tmp_path)
    state.initialize({"run": "x"}, resume=False)
    output = tmp_path / "summary.json"
    command = [
        "python", "-c",
        f"from pathlib import Path; Path({str(output)!r}).write_text('{{}}\\n'); raise SystemExit(1)",
    ]
    rc = module.run_stage(
        name="visualization", command=command, root=tmp_path,
        status_path=tmp_path / "status.jsonl", state=state,
        request={"semantic": "x"}, expected_outputs=[output], resume=False,
        allowed_returncodes={0, 1}, allow_stage_resume_skip=False,
    )
    assert rc == 1
    stage = json.loads((tmp_path / "state/stages/visualization.json").read_text())
    assert stage["status"] == "partial_failure"
    assert not state.stage_is_complete(
        "visualization", request_hash=canonical_hash({"semantic": "x"}), outputs=[output]
    )


def test_final_pipeline_status_does_not_hide_partial_analysis_when_render_is_deferred() -> None:
    module = _load_script_module(
        "inline_pipeline_final_status_v4_test", "scripts/demo/run_inline_realign_pipeline.py"
    )
    assert module.final_pipeline_status(
        render_mode="skip", partial_failure=True, render_failure=False
    ) == "partial_failure_render_deferred"
    assert module.final_pipeline_status(
        render_mode="skip", partial_failure=False, render_failure=False
    ) == "analysis_complete_render_deferred"
    assert module.final_pipeline_status(
        render_mode="after", partial_failure=False, render_failure=True
    ) == "render_partial_failure"
