from __future__ import annotations

import importlib.util
from pathlib import Path

from lyricalign.demo.timeline_video import OUTPUT_HEIGHT, OUTPUT_WIDTH
from lyricalign.demo.visual_diagnostics import _collapsed_group_label, _group_collapsed_rows


def load_script(name: str, relative: str):
    root = Path(__file__).resolve().parents[1]
    path = root / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nearby_zero_rows_group_noncontiguous_indices() -> None:
    rows = [
        {"global_character_index": 120, "character": "我", "start_sec": 10.00, "end_sec": 10.00},
        {"global_character_index": 121, "character": "们", "start_sec": 10.02, "end_sec": 10.02},
        {"global_character_index": 122, "character": "走", "start_sec": 10.03, "end_sec": 10.03},
        {"global_character_index": 123, "character": "向", "start_sec": 10.04, "end_sec": 10.04},
        {"global_character_index": 124, "character": "他", "start_sec": 10.05, "end_sec": 10.05},
        {"global_character_index": 130, "character": "的", "start_sec": 10.06, "end_sec": 10.06},
        {"global_character_index": 132, "character": "给", "start_sec": 10.07, "end_sec": 10.07},
        {"global_character_index": 133, "character": "过", "start_sec": 10.08, "end_sec": 10.08},
        {"global_character_index": 134, "character": "热", "start_sec": 10.09, "end_sec": 10.09},
    ]
    positive, groups = _group_collapsed_rows(rows)
    assert positive == []
    assert len(groups) == 1
    assert _collapsed_group_label(groups[0]) == "零时长 [120-124, 130, 132-134] 我-他，的，给-热"


def test_visual_and_video_widths_are_doubled() -> None:
    analyzer = load_script("wide_analyzer", "scripts/demo/analyze_inline_realign_visuals.py")
    assert analyzer.full_timeline_pixel_width(5.0) == 12000
    assert analyzer.full_timeline_pixel_width(240.0) == 38400
    assert OUTPUT_WIDTH == 3840
    assert OUTPUT_HEIGHT == 1080


def test_defaults_use_60_second_primary_and_comparison() -> None:
    pipeline = load_script("pipeline_60main", "scripts/demo/run_inline_realign_pipeline.py")
    args = pipeline.parser().parse_args([
        "--mode", "formal",
        "--out-root", "/tmp/out",
        "--mir1k-subset-root", "/tmp/mir",
        "--m4-labels", "/tmp/labels",
        "--m4-audio-root", "/tmp/m4",
        "--model", "/tmp/model",
        "--revision", "rev",
        "--r2-checkpoint", "/tmp/ckpt",
    ])
    assert args.primary_variant == "B4_60_silence_official"
    assert args.comparison_branches == (
        "B0_60_fixed_official,B4_60_silence_official,"
        "C1_60_silence_compressed_diagnostic,B6_60_strict_silence_official"
    )
