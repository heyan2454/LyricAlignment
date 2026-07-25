from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("quick_collector", COLLECTOR_PATH)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def test_tailpad_zero_means_native_duration(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "a.wav"
    source.write_bytes(b"fake")
    created: list[tuple[float, float]] = []

    def fake_make(source_path: Path, output: Path, *, source_duration: float, target_duration: float) -> None:
        created.append((source_duration, target_duration))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake")

    monkeypatch.setattr(collector, "make_silence_tail", fake_make)
    args = SimpleNamespace(
        out_dir=tmp_path / "out",
        audio_root=tmp_path,
        experiment="tailpad",
        target_durations="0,60,120",
    )
    records = [
        {
            "item_id": "a",
            "song_id": "song",
            "audio_relpath": "a.wav",
            "lyrics_normalized": "甲",
            "duration_sec": 10.0,
        }
    ]
    by_item = {
        "a": [
            {
                "item_id": "a",
                "character_index": 0,
                "normalized_character": "甲",
                "start_sec": 1.0,
                "end_sec": 2.0,
            }
        ]
    }
    variants = collector.build_variants(args, records, by_item, {})
    assert [row["duration_sec"] for row in variants] == [10.0, 60.0, 120.0]
    assert [row["probe_condition"]["requested_total_duration_sec"] for row in variants] == [0.0, 60.0, 120.0]
    assert created == [(10.0, 10.0), (10.0, 60.0), (10.0, 120.0)]
