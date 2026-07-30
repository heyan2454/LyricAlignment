from __future__ import annotations

import importlib.util
from pathlib import Path

from lyricalign.demo.visual_diagnostics import _group_collapsed_rows, render_inconsistency


def load_script(name: str, script_name: str):
    root = Path(__file__).resolve().parents[1]
    path = root / 'scripts' / 'demo' / script_name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_group_collapsed_rows_compacts_adjacent_zero_and_negative() -> None:
    rows = [
        {"global_character_index": 0, "character": "A", "start_sec": 0.0, "end_sec": 0.2},
        {"global_character_index": 1, "character": "B", "start_sec": 0.3, "end_sec": 0.3},
        {"global_character_index": 2, "character": "C", "start_sec": 0.35, "end_sec": 0.35},
        {"global_character_index": 3, "character": "D", "start_sec": 0.6, "end_sec": 0.5},
        {"global_character_index": 4, "character": "E", "start_sec": 0.7, "end_sec": 0.6},
    ]
    positive, collapsed = _group_collapsed_rows(rows)
    assert len(positive) == 1
    assert len(collapsed) == 2
    assert collapsed[0]["kind"] == "zero"
    assert collapsed[0]["start_index"] == 1 and collapsed[0]["end_index"] == 2
    assert collapsed[1]["kind"] == "negative"
    assert collapsed[1]["start_index"] == 3 and collapsed[1]["end_index"] == 4


def test_full_timeline_pixel_width_is_wider_and_bounded() -> None:
    module = load_script('inline_visual_full_timeline_patch', 'analyze_inline_realign_visuals.py')
    assert module.full_timeline_pixel_width(5.0) == 12000
    assert module.full_timeline_pixel_width(240.0) == 38400
    assert module.full_timeline_pixel_width(1000.0) == 64000


def test_render_inconsistency_supports_shared_index_axis(tmp_path: Path) -> None:
    out = tmp_path / 'inconsistency.png'
    tracks = [
        ('A', [
            {"global_character_index": 0, "character": '你', "start_sec": 0.0, "end_sec": 0.2},
            {"global_character_index": 1, "character": '好', "start_sec": 0.2, "end_sec": 0.4},
        ]),
        ('B', [
            {"global_character_index": 0, "character": '你', "start_sec": 0.01, "end_sec": 0.19},
            {"global_character_index": 1, "character": '好', "start_sec": 0.22, "end_sec": 0.42},
        ]),
    ]
    meta = render_inconsistency(output=out, tracks=tracks, title='test')
    assert out.is_file() and out.stat().st_size > 0
    assert meta['unit_count'] == 2
