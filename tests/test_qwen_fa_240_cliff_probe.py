from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/evaluation/collect_qwen_fa_240_cliff_probe.py"
SPEC = importlib.util.spec_from_file_location("cliff_probe", PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_equal_total_controls_hold_b_at_same_absolute_position(tmp_path: Path) -> None:
    a_path = tmp_path / "a.wav"
    b_path = tmp_path / "b.wav"
    sf.write(a_path, np.zeros(16000, dtype=np.float32), 16000)
    sf.write(b_path, np.zeros(32000, dtype=np.float32), 16000)
    a = {
        "item_id": "A",
        "song_id": "song-a",
        "lyrics_normalized": "甲乙",
        "resolved_audio_path": str(a_path),
    }
    b = {
        "item_id": "B",
        "song_id": "song-b",
        "lyrics_normalized": "丙丁",
        "resolved_audio_path": str(b_path),
    }
    refs = [
        {"character_index": 0, "normalized_character": "甲", "start_sec": 0.0, "end_sec": 0.5},
        {"character_index": 1, "normalized_character": "乙", "start_sec": 0.5, "end_sec": 1.0},
    ]
    b_refs = [
        {"character_index": 0, "normalized_character": "丙", "start_sec": 0.0, "end_sec": 1.0},
        {"character_index": 1, "normalized_character": "丁", "start_sec": 1.0, "end_sec": 2.0},
    ]
    variants = probe.build_variants(
        out_dir=tmp_path / "out",
        a=a,
        b=b,
        a_refs=refs,
        b_refs=b_refs,
        offsets=[0.0],
        late_start_sec=240.0,
        mid_start_sec=180.0,
    )
    controls = [row for row in variants if row["variant_kind"] == "equal_total_control"]
    assert len(controls) == 3
    assert {round(row["duration_sec"], 6) for row in controls} == {243.0}
    starts = {}
    for control in controls:
        a_start = min(row["start_sec"] for row in control["refs"] if row["segment_role"] == "A")
        b_start = min(row["start_sec"] for row in control["refs"] if row["segment_role"] == "B")
        starts[control["probe_condition"]] = (a_start, b_start)
    assert starts["equal_total_late_A"] == (240.0, 241.0)
    assert starts["equal_total_mid_A"] == (180.0, 241.0)
    assert starts["equal_total_early_A"] == (0.0, 241.0)


def test_select_pair_is_distinct_and_deterministic(tmp_path: Path) -> None:
    records = []
    by_item = {}
    for index, song in enumerate(("s1", "s2", "s3")):
        item = f"item-{index}"
        path = tmp_path / f"{item}.wav"
        sf.write(path, np.zeros(16000 * (6 + index), dtype=np.float32), 16000)
        records.append(
            {
                "item_id": item,
                "song_id": song,
                "split": "test",
                "duration_sec": 6 + index,
                "audio_relpath": path.name,
            }
        )
        by_item[item] = [
            {"character_index": char, "normalized_character": "字", "start_sec": 0.0, "end_sec": 0.1}
            for char in range(15)
        ]
    first = probe.select_pair(
        records,
        by_item,
        tmp_path,
        split="test",
        min_duration=5,
        max_duration=15,
        min_characters=15,
        max_characters=40,
        seed=123,
        a_item_id=None,
        b_item_id=None,
    )
    second = probe.select_pair(
        records,
        by_item,
        tmp_path,
        split="test",
        min_duration=5,
        max_duration=15,
        min_characters=15,
        max_characters=40,
        seed=123,
        a_item_id=None,
        b_item_id=None,
    )
    assert first[0]["item_id"] == second[0]["item_id"]
    assert first[1]["item_id"] == second[1]["item_id"]
    assert first[0]["item_id"] != first[1]["item_id"]
    assert first[0]["song_id"] != first[1]["song_id"]
