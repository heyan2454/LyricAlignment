from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from lyricalign.demo.timeline_video import _ffmpeg_cfr_output_options
from lyricalign.demo.visual_diagnostics import draw_track_windows, render_timeline_page
from lyricalign.demo.window_planning import (
    map_original_time_to_compressed,
    project_silence_aware_plan_to_compressed_timeline,
)


def _load_visualizer():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts/demo/analyze_inline_realign_visuals.py"
    spec = importlib.util.spec_from_file_location("visualizer_followup_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stable_selected_input_and_commit_same_interval_are_combined(tmp_path: Path) -> None:
    module = _load_visualizer()
    (tmp_path / "stable_window_assistance.json").write_text(
        json.dumps({
            "transitions": [{
                "from_window_index": 0,
                "to_window_index": 1,
                "prefix_segment": {"start_sec": 10.0, "end_sec": 11.0},
                "safe_commit_segment": {"start_sec": 10.0, "end_sec": 11.0},
            }],
        }),
        encoding="utf-8",
    )
    spans = module.stable_spans(tmp_path, {"stable_segments": {"segments": []}})
    selected = [row for row in spans if str(row.get("kind", "")).startswith("stable_selected")]
    assert selected == [{
        "from_window": 0,
        "to_window": 1,
        "start_sec": 10.0,
        "end_sec": 11.0,
        "label": "选中的输入稳定区／安全提交区",
        "kind": "stable_selected_both",
    }]


class _FakeAxis:
    def __init__(self) -> None:
        self.fills: list[tuple[tuple, dict]] = []
        self.lines: list[tuple[tuple, dict]] = []
        self.texts: list[tuple[tuple, dict]] = []

    def fill_between(self, *args, **kwargs):
        self.fills.append((args, kwargs))

    def vlines(self, *args, **kwargs):
        self.lines.append((args, kwargs))

    def text(self, *args, **kwargs):
        self.texts.append((args, kwargs))


def test_track_window_lines_are_confined_and_input_edges_are_short_ticks() -> None:
    axis = _FakeAxis()
    draw_track_windows(
        axis,
        [{
            "window_index": 0,
            "core_start_sec": 2.0,
            "core_end_sec": 8.0,
            "input_start_sec": 1.0,
            "input_end_sec": 9.0,
        }],
        start=0.0,
        end=10.0,
        y_bottom=3.0,
        y_top=5.0,
        color="#123456",
    )
    assert axis.fills
    input_lines = [row for row in axis.lines if row[1].get("linestyle") == ":"]
    core_lines = [row for row in axis.lines if row[1].get("linestyle") != ":"]
    assert len(input_lines) == 2
    assert len(core_lines) == 2
    assert all(float(args[1]) > 4.5 and float(args[2]) == 5.0 for args, _ in input_lines)
    assert all(float(args[1]) == 3.0 and float(args[2]) == 5.0 for args, _ in core_lines)


def test_compressed_removed_silence_is_visually_marked_inside_track() -> None:
    axis = _FakeAxis()
    draw_track_windows(
        axis,
        [{
            "window_index": 0,
            "core_start_sec": 0.0,
            "core_end_sec": 4.0,
            "input_start_sec": 0.0,
            "input_end_sec": 4.0,
            "silence_compression_mapping": {
                "removed_intervals": [{"start_sec": 1.0, "end_sec": 2.0}],
            },
        }],
        start=0.0, end=4.0, y_bottom=2.0, y_top=3.0, color="#123456",
    )
    removed = [row for row in axis.fills if row[1].get("hatch") == "////"]
    assert len(removed) == 1
    assert removed[0][0][0] == [1.0, 2.0]
    assert any(args[2] == "输入中已移除静音" for args, _ in axis.texts)


def test_timeline_geometry_uses_collapsed_rows_for_track_window_extent(tmp_path: Path) -> None:
    output = tmp_path / "timeline.png"
    rows = [
        {"global_character_index": 0, "character": "短", "start_sec": 0.1, "end_sec": 0.2},
        {"global_character_index": 1, "character": "零", "start_sec": 0.4, "end_sec": 0.4},
        {"global_character_index": 2, "character": "叠", "start_sec": 0.4, "end_sec": 0.4},
    ]
    windows = [{
        "window_index": 0,
        "core_start_sec": 0.0,
        "core_end_sec": 1.0,
        "input_start_sec": 0.0,
        "input_end_sec": 1.0,
    }]
    meta = render_timeline_page(
        output=output,
        tracks=[("方案A", rows, windows), ("方案B", rows, windows)],
        windows=[],
        start=0.0,
        end=1.0,
        title="geometry",
        pixel_width=1000,
        pixel_height=700,
    )
    first, second = meta["track_geometry"]
    assert first["block_height"] > 0.45
    assert first["y_bottom"] >= second["y_top"]
    assert output.is_file() and output.stat().st_size > 0


def test_old_ffmpeg_falls_back_to_vsync(monkeypatch) -> None:
    import lyricalign.demo.timeline_video as module

    module._ffmpeg_cfr_output_options.cache_clear()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="-vsync set video sync method", stderr=""),
    )
    assert module._ffmpeg_cfr_output_options("ffmpeg-old") == ("-vsync", "cfr")
    module._ffmpeg_cfr_output_options.cache_clear()


def test_new_ffmpeg_prefers_fps_mode(monkeypatch) -> None:
    import lyricalign.demo.timeline_video as module

    module._ffmpeg_cfr_output_options.cache_clear()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="-fps_mode set framerate mode\n-vsync legacy", stderr=""),
    )
    assert module._ffmpeg_cfr_output_options("ffmpeg-new") == ("-fps_mode", "cfr")
    module._ffmpeg_cfr_output_options.cache_clear()


def test_compressed_windows_use_original_silence_snap_boundary() -> None:
    mapping = {
        "compressed_duration_sec": 30.0,
        "kept_segments": [
            {
                "compressed_start_sec": 0.0,
                "compressed_end_sec": 10.0,
                "original_start_sec": 0.0,
                "original_end_sec": 10.0,
            },
            {
                "compressed_start_sec": 10.0,
                "compressed_end_sec": 30.0,
                "original_start_sec": 20.0,
                "original_end_sec": 40.0,
            },
        ],
    }
    original_plan = {
        "target_core_sec": 30.0,
        "windows": [
            {
                "window_index": 0,
                "core_start_sec": 0.0,
                "core_end_sec": 15.0,
                "input_start_sec": 0.0,
                "input_end_sec": 25.0,
                "is_final_core": False,
                "window_plan_policy": "silence_aware_global_v1",
            },
            {
                "window_index": 1,
                "core_start_sec": 15.0,
                "core_end_sec": 40.0,
                "input_start_sec": 5.0,
                "input_end_sec": 40.0,
                "is_final_core": True,
                "window_plan_policy": "silence_aware_global_v1",
            },
        ],
    }
    assert map_original_time_to_compressed(15.0, mapping, boundary_side="left") == 10.0
    assert map_original_time_to_compressed(15.0, mapping, boundary_side="right") == 10.0
    projected = project_silence_aware_plan_to_compressed_timeline(original_plan, mapping)
    first, second = projected["windows"]
    assert first["core_end_sec"] == second["core_start_sec"] == 10.0
    assert first["original_core_end_sec"] == second["original_core_start_sec"] == 15.0
    assert all(row["input_excludes_removed_silence"] for row in projected["windows"])
    assert projected["policy"] == "original_silence_snap_then_project_to_compressed_audio"
