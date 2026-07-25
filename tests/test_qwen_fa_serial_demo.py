from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.karaoke import (
    ass_time,
    build_serial_windows,
    candidate_character_range,
    merge_window_candidates,
    parse_lyrics_text,
)


def test_parse_lyrics_preserves_repeated_occurrences_and_phrase_spaces() -> None:
    document = parse_lyrics_text("甲乙 丙\n\n甲乙 丙\n")
    assert document.transcript == "甲乙丙甲乙丙"
    assert len(document.lines) == 2
    assert document.characters[1].display_suffix == " "
    assert document.characters[0].global_index != document.characters[3].global_index


def test_serial_windows_use_sixty_second_cores_with_context() -> None:
    windows = build_serial_windows(151.0, core_sec=60, left_context_sec=15, right_context_sec=15)
    assert windows == [
        {"window_index": 0, "core_start_sec": 0.0, "core_end_sec": 60.0, "input_start_sec": 0.0, "input_end_sec": 75.0},
        {"window_index": 1, "core_start_sec": 60.0, "core_end_sec": 120.0, "input_start_sec": 45.0, "input_end_sec": 135.0},
        {"window_index": 2, "core_start_sec": 120.0, "core_end_sec": 151.0, "input_start_sec": 105.0, "input_end_sec": 151.0},
    ]


def test_candidate_range_snaps_to_whole_lines() -> None:
    document = parse_lyrics_text("甲乙丙\n丁戊己\n庚辛壬\n癸子丑\n")
    start, end = candidate_character_range(
        document,
        duration_sec=120,
        input_start_sec=45,
        input_end_sec=90,
        cursor=4,
        line_padding=0,
        character_backtrack=0,
        minimum_forward_characters=1,
    )
    assert start % 3 == 0
    assert end % 3 == 0
    assert 0 <= start < end <= len(document.characters)


def test_merge_prefers_core_candidate_and_repairs_cross_window_order() -> None:
    candidates = [
        {
            "global_character_index": 0,
            "fixed_global_start_sec": 10.0,
            "fixed_global_end_sec": 11.0,
            "core_start_sec": 0.0,
            "core_end_sec": 60.0,
            "input_start_sec": 0.0,
            "input_end_sec": 75.0,
            "raw_boundary_margin_mean": 0.1,
        },
        {
            "global_character_index": 0,
            "fixed_global_start_sec": 62.0,
            "fixed_global_end_sec": 63.0,
            "core_start_sec": 60.0,
            "core_end_sec": 120.0,
            "input_start_sec": 45.0,
            "input_end_sec": 135.0,
            "raw_boundary_margin_mean": 0.9,
        },
        {
            "global_character_index": 1,
            "fixed_global_start_sec": 9.0,
            "fixed_global_end_sec": 9.5,
            "core_start_sec": 0.0,
            "core_end_sec": 60.0,
            "input_start_sec": 0.0,
            "input_end_sec": 75.0,
            "raw_boundary_margin_mean": 0.2,
        },
    ]
    rows = merge_window_candidates(candidates, duration_sec=100.0)
    assert rows[0]["selected_start_sec"] == 62.0
    assert rows[1]["start_sec"] >= rows[0]["end_sec"]
    assert rows[1]["cross_window_repaired"] is True


def test_ass_time_is_centisecond_based() -> None:
    assert ass_time(61.234) == "0:01:01.23"
