"""E3 catastrophic-commit discovery tests (WP C2, CPU acceptance).

Pure function over frozen baseline rows: no GT, no model, no disk writes
except the caller-provided temporary JSONL fixture.
"""
from __future__ import annotations

import json

from lyricalign.realign_recovery.catastrophic_commit import (
    discover_catastrophic_commits,
)


def _row(song_id, window_index, shadow=None):
    return {
        "id": f"{song_id}-{window_index}",
        "song_id": song_id,
        "window_index": window_index,
        "window": {"text_unit_ids": []},
        "detector_shadow": shadow,
    }


def _continuations():
    return {"1": None, "2": None, "3": None, "5": None}


def test_no_catastrophic_windows():
    rows = [
        _row("s1", 0, {}),
        _row("s1", 1, None),
        _row("s1", 2),
    ]
    result = discover_catastrophic_commits(rows)
    assert result == [
        {
            "song_id": "s1",
            "first_catastrophic_window_index": None,
            "catastrophic_window_indices": [],
            "continuation": _continuations(),
            "n_windows": 3,
        }
    ]


def test_first_commit_in_middle_window():
    rows = [
        _row("s1", 0, {"unsafe_intervals": []}),
        _row("s1", 1, {"unsafe_intervals": [[10.0, 50.0]]}),
        _row("s1", 2, {"unsafe_intervals": [[20.0, 40.0]]}),
        _row("s1", 3, {"unsafe_intervals": [[30.0, 60.0]]}),
        _row("s1", 4, {"unsafe_intervals": []}),
    ]
    result = discover_catastrophic_commits(rows)
    song = result[0]
    assert song["first_catastrophic_window_index"] == 1
    assert song["catastrophic_window_indices"] == [1, 2, 3]
    assert song["continuation"] == {
        "1": True,   # window 2 catastrophic
        "2": True,   # windows 2,3 catastrophic
        "3": False,  # windows 2,3,4 -> 4 not catastrophic
        "5": None,   # only 3 windows follow the first commit
    }
    assert song["n_windows"] == 5


def test_continuation_true_when_all_following_catastrophic():
    rows = [
        _row("s1", w, {"unsafe_intervals": [[10.0, 50.0]]}) for w in range(10)
    ]
    song = discover_catastrophic_commits(rows)[0]
    assert song["first_catastrophic_window_index"] == 0
    assert song["continuation"] == {"1": True, "2": True, "3": True, "5": True}


def test_continuation_none_when_windows_insufficient():
    # first commit is the last window -> no following windows at all
    rows = [
        _row("s1", 0, {"unsafe_intervals": []}),
        _row("s1", 1, {"unsafe_intervals": []}),
        _row("s1", 2, {"unsafe_intervals": [[10.0, 50.0]]}),
    ]
    song = discover_catastrophic_commits(rows)[0]
    assert song["first_catastrophic_window_index"] == 2
    assert song["continuation"] == _continuations()

    # only 1 following window -> k>=2 None, k=1 judged
    rows2 = [
        _row("s1", 0, {"unsafe_intervals": []}),
        _row("s1", 1, {"unsafe_intervals": [[10.0, 50.0]]}),
        _row("s1", 2, {"unsafe_intervals": [[10.0, 50.0]]}),
    ]
    song2 = discover_catastrophic_commits(rows2)[0]
    assert song2["continuation"] == {"1": True, "2": None, "3": None, "5": None}


def test_legacy_bad_window_shape_compatible():
    rows = [
        _row("s1", 0, {"bad_window": [10.0, 50.0]}),
        _row("s1", 1, {"bad_window": []}),
        _row("s1", 2, {"bad_window": [5.0, 6.0]}),
    ]
    song = discover_catastrophic_commits(rows)[0]
    assert song["first_catastrophic_window_index"] == 0
    assert song["catastrophic_window_indices"] == [0, 2]
    assert song["continuation"] == {"1": False, "2": False, "3": None, "5": None}


def test_path_and_list_input_equivalent(tmp_path):
    rows = [
        _row("s1", 0, {"unsafe_intervals": []}),
        _row("s1", 1, {"unsafe_intervals": [[10.0, 50.0]]}),
        _row("s1", 2, {"unsafe_intervals": [[10.0, 50.0]]}),
    ]
    path = tmp_path / "baseline.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    assert discover_catastrophic_commits(str(path)) == discover_catastrophic_commits(rows)


def test_multi_song_grouping():
    rows = [
        _row("songA", 0, {"unsafe_intervals": []}),
        _row("songB", 0, {"unsafe_intervals": [[10.0, 50.0]]}),
        _row("songA", 1, {"unsafe_intervals": [[10.0, 50.0]]}),
        _row("songB", 1, {"unsafe_intervals": [[10.0, 50.0]]}),
        _row("songA", 2, {"unsafe_intervals": [[10.0, 50.0]]}),
    ]
    by_song = {r["song_id"]: r for r in discover_catastrophic_commits(rows)}
    assert set(by_song) == {"songA", "songB"}

    a = by_song["songA"]
    assert a["first_catastrophic_window_index"] == 1
    assert a["catastrophic_window_indices"] == [1, 2]
    assert a["continuation"] == {"1": True, "2": None, "3": None, "5": None}
    assert a["n_windows"] == 3

    b = by_song["songB"]
    assert b["first_catastrophic_window_index"] == 0
    assert b["catastrophic_window_indices"] == [0, 1]
    assert b["continuation"] == {"1": True, "2": None, "3": None, "5": None}
    assert b["n_windows"] == 2


def test_custom_keys_and_predicate():
    rows = [
        {"song": "s1", "win": 0, "shadow": {"score": 0.1}},
        {"song": "s1", "win": 1, "shadow": {"score": 0.9}},
        {"song": "s1", "win": 2, "shadow": {"score": 0.8}},
    ]
    result = discover_catastrophic_commits(
        rows,
        window_index_key="win",
        song_key="song",
        shadow_key="shadow",
        is_catastrophic=lambda s: s.get("score", 0.0) >= 0.5,
    )
    song = result[0]
    assert song["song"] == "s1"
    assert song["first_catastrophic_window_index"] == 1
    assert song["catastrophic_window_indices"] == [1, 2]
    assert song["continuation"] == {"1": True, "2": None, "3": None, "5": None}


def test_out_of_order_input_still_sorted_by_window_index():
    rows = [
        _row("s1", 3, {"unsafe_intervals": [[30.0, 60.0]]}),
        _row("s1", 0, {"unsafe_intervals": []}),
        _row("s1", 2, {"unsafe_intervals": [[20.0, 40.0]]}),
        _row("s1", 1, {"unsafe_intervals": [[10.0, 50.0]]}),
    ]
    song = discover_catastrophic_commits(rows)[0]
    assert song["first_catastrophic_window_index"] == 1
    assert song["catastrophic_window_indices"] == [1, 2, 3]
    assert song["continuation"] == {"1": True, "2": True, "3": None, "5": None}
