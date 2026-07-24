from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selection = load_module(
    "selection",
    ROOT / "scripts/evaluation/prepare_qwen_fa_immediate_all_selection.py",
)
repeat = load_module(
    "repeat",
    ROOT / "scripts/evaluation/collect_qwen_fa_repeat_probe.py",
)
error_blocks = load_module(
    "error_blocks",
    ROOT / "scripts/evaluation/analyze_qwen_fa_error_blocks.py",
)


def test_repeat_variants_preserve_occurrence_positions(tmp_path: Path) -> None:
    a_path = tmp_path / "a.wav"
    b_path = tmp_path / "b.wav"
    sf.write(a_path, np.zeros(16000, dtype=np.float32), 16000)
    sf.write(b_path, np.zeros(32000, dtype=np.float32), 16000)
    a = {"item_id": "A", "song_id": "sA", "lyrics_normalized": "甲乙", "resolved_audio_path": str(a_path)}
    b = {"item_id": "B", "song_id": "sB", "lyrics_normalized": "丙丁", "resolved_audio_path": str(b_path)}
    a_refs = [
        {"character_index": 0, "normalized_character": "甲", "start_sec": 0.0, "end_sec": 0.5},
        {"character_index": 1, "normalized_character": "乙", "start_sec": 0.5, "end_sec": 1.0},
    ]
    b_refs = [
        {"character_index": 0, "normalized_character": "丙", "start_sec": 0.0, "end_sec": 1.0},
        {"character_index": 1, "normalized_character": "丁", "start_sec": 1.0, "end_sec": 2.0},
    ]
    variants = repeat.build_repeat_variants(
        out_dir=tmp_path / "out",
        a=a,
        b=b,
        a_refs=a_refs,
        b_refs=b_refs,
        gaps=[2.0],
    )
    aa = next(row for row in variants if row["variant_kind"] == "repeat_AA")
    ab = next(row for row in variants if row["variant_kind"] == "control_AB")
    assert aa["duration_sec"] == 4.0
    assert ab["duration_sec"] == 5.0
    assert min(row["start_sec"] for row in aa["refs"] if row["segment_role"] == "A2") == 3.0
    assert min(row["start_sec"] for row in ab["refs"] if row["segment_role"] == "B") == 3.0


def test_selection_uses_diverse_songs(tmp_path: Path) -> None:
    labels = []
    characters = []
    for index, song in enumerate(("s1", "s2", "s3", "s1")):
        item = f"item-{index}"
        sf.write(tmp_path / f"{item}.wav", np.zeros(16000 * 6, dtype=np.float32), 16000)
        labels.append(
            {
                "item_id": item,
                "song_id": song,
                "split": "test",
                "duration_sec": 6.0,
                "audio_relpath": f"{item}.wav",
            }
        )
        characters.extend(
            {"item_id": item, "character_index": char}
            for char in range(15)
        )
    selected = selection.select_shift_items(
        labels,
        characters,
        tmp_path,
        count=3,
        seed=7,
        min_duration=5,
        max_duration=15,
        min_characters=15,
        max_characters=40,
    )
    assert len(selected) == 3
    assert len({row["song_id"] for row in selected}) == 3


def test_error_block_summary_detects_backward_jump_and_block() -> None:
    rows = []
    raw = [(0, 1), (2, 3), (1, 2), (4, 5)]
    for index, (start, end) in enumerate(raw):
        rows.append(
            {
                "character_index": index,
                "raw_start_class": start,
                "raw_end_class": end,
                "gt_start_class": index * 2,
                "gt_end_class": index * 2 + 1,
                "raw_start_entropy": 1.0,
                "raw_end_entropy": 1.0,
                "raw_start_margin": 0.5,
                "raw_end_margin": 0.5,
                "fixed_start_abs_error_sec": 0.1,
                "fixed_end_abs_error_sec": 0.1,
                "raw_start_abs_error_sec": 0.2,
                "raw_end_abs_error_sec": 0.2,
                "start_repaired": index in (1, 2),
                "end_repaired": index in (1, 2),
                "gt_start_sec": index * 0.2,
                "gt_end_sec": index * 0.2 + 0.1,
            }
        )
    summary = error_blocks.summarize_variant(rows, 0.08)
    assert summary["backward_jump_count"] >= 1
    assert summary["max_repair_block_characters"] == 2
