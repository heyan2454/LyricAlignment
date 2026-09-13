from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "export_review_gating", ROOT / "scripts" / "evaluation" / "export_review_gating.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _song(name: str, scores_and_defects: list[tuple[float, int]]) -> dict:
    return {"song": name, "units": [{"position": index, "line_index": 0, "character": "x",
                                     "signal": "raw_end_entropy", "score": score, "defect": defect,
                                     "start_sec": float(index), "end_sec": float(index)}
                                    for index, (score, defect) in enumerate(scores_and_defects)]}


def test_held_out_song_does_not_influence_its_own_threshold():
    """The defining property of the leave-one-song-out gate: a song cannot move its own cut-off."""
    flat = [(float(index % 10) / 10.0, index % 3 == 0) for index in range(60)]
    baseline = [_song("a", flat), _song("b", list(flat)), _song("c", list(flat))]
    base_thresholds, base_caught, base_dropped = MODULE.out_of_sample_thresholds(baseline, 0.20)

    moved = [(0.9 + (index % 5) / 100.0, 1) for index in range(60)]        # a 变成高风险且全是缺陷
    altered = [_song("a", moved), _song("b", list(flat)), _song("c", list(flat))]
    thresholds, caught, dropped = MODULE.out_of_sample_thresholds(altered, 0.20)
    assert thresholds["a"] == base_thresholds["a"]                         # 只由 b、c 决定
    assert thresholds["b"] != base_thresholds["b"] or thresholds["c"] != base_thresholds["c"]
    assert 0 < dropped < sum(len(s["units"]) for s in altered)
    assert caught <= sum(unit["defect"] for s in altered for unit in s["units"])


def test_load_songs_skips_short_and_missing_signal_songs(tmp_path: Path):
    batch = tmp_path / "batch"
    good = batch / "song_ok" / Path(MODULE.ALIGN_SUFFIX)
    good.parent.mkdir(parents=True)
    characters = [{"character": "字", "line_index": 0, "raw_global_start_sec": float(i),
                   "raw_global_end_sec": (float(i) if i % 4 == 0 else float(i) + 0.3),
                   "raw_end_entropy": float(i % 7)} for i in range(25)]
    good.write_text(json.dumps({"characters": characters}), encoding="utf-8")
    tiny = batch / "song_tiny" / Path(MODULE.ALIGN_SUFFIX)
    tiny.parent.mkdir(parents=True)
    tiny.write_text(json.dumps({"characters": characters[:5]}), encoding="utf-8")
    songs = MODULE.load_songs(batch)
    assert [song["song"] for song in songs] == ["song_ok"]
    units = songs[0]["units"]
    assert len(units) == 25 and sum(unit["defect"] for unit in units) == 7   # i % 4 == 0
    assert all(unit["signal"] == "raw_end_entropy" for unit in units)
