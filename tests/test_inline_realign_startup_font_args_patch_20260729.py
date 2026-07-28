from __future__ import annotations

import importlib.util
import warnings
from pathlib import Path


def load_script(name: str, relative: str):
    root = Path(__file__).resolve().parents[1]
    path = root / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_direct_timeline_api_registers_exact_sc_face_without_glyph_warning(tmp_path: Path) -> None:
    from lyricalign.demo.visual_diagnostics import render_timeline_page

    output = tmp_path / "timeline_sc.png"
    rows = [{
        "global_character_index": 0,
        "character": "案",
        "start_sec": 0.1,
        "end_sec": 0.4,
    }]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        render_timeline_page(
            output=output,
            tracks=[("方案", rows)],
            windows=[],
            start=0.0,
            end=0.5,
            title="简体中文字体测试",
            pixel_width=700,
            pixel_height=420,
        )
    messages = [str(item.message) for item in caught]
    assert output.is_file() and output.stat().st_size > 0
    assert not any("Glyph" in message and "missing" in message for message in messages), messages
    assert not any("findfont" in message for message in messages), messages


def test_negative_csv_options_use_equals_syntax_and_parse() -> None:
    pipeline = load_script(
        "inline_pipeline_negative_csv_merged_patch",
        "scripts/demo/run_inline_realign_pipeline.py",
    )
    end_token = pipeline.option_assignment(
        "--text-dosage-end-deltas", "-8,-4,-2,0,2,4,8,16"
    )
    start_token = pipeline.option_assignment(
        "--text-dosage-start-deltas", "-4,-2,0,2,4"
    )
    assert end_token == "--text-dosage-end-deltas=-8,-4,-2,0,2,4,8,16"
    assert start_token == "--text-dosage-start-deltas=-4,-2,0,2,4"

    experiment = load_script(
        "inline_experiment_negative_csv_merged_patch",
        "scripts/demo/run_inline_realign_experiment.py",
    )
    parsed = experiment.parser().parse_args([
        "--manifest", "manifest.jsonl",
        "--out-root", "out",
        "--model", "model",
        "--revision", "main",
        "--r2-checkpoint", "checkpoint",
        end_token,
        start_token,
    ])
    assert parsed.text_dosage_end_deltas == "-8,-4,-2,0,2,4,8,16"
    assert parsed.text_dosage_start_deltas == "-4,-2,0,2,4"


def test_merge_preserves_latest_control_and_visual_features() -> None:
    pipeline = load_script(
        "inline_pipeline_merge_preservation",
        "scripts/demo/run_inline_realign_pipeline.py",
    )
    assert pipeline.experiment_force_requested(
        force=False, invalidated_stages=["experiment"]
    )
    source = Path(pipeline.__file__).read_text(encoding="utf-8")
    assert '"--video-pages-mode", "off" if args.render_mode == "skip" else "on"' in source

    visual_source = (
        Path(__file__).resolve().parents[1]
        / "scripts/demo/analyze_inline_realign_visuals.py"
    ).read_text(encoding="utf-8")
    assert '"full_timeline.png"' in visual_source
