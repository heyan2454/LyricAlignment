from __future__ import annotations

import json
from pathlib import Path

from lyricalign.demo.alignment_artifacts import build_quality_report, write_alignment_bundle


def _row(index: int, start: float, end: float, *, selected_start: float | None = None, compressed: bool = False):
    return {
        "global_character_index": index,
        "character": str(index),
        "raw_global_start_sec": start - 0.02,
        "raw_global_end_sec": end - 0.02,
        "fixed_global_start_sec": start,
        "fixed_global_end_sec": end,
        "selected_start_sec": start if selected_start is None else selected_start,
        "selected_end_sec": end,
        "start_sec": start,
        "end_sec": end,
        "raw_start_top1_probability": 0.8,
        "raw_end_top1_probability": 0.7,
        "raw_boundary_margin_mean": 0.4,
        "raw_start_entropy": 0.5,
        "raw_end_entropy": 0.6,
        "overlap_compressed": compressed,
        "overlap_compression_sec": 0.1 if compressed else 0.0,
        "overlap_compression_collapsed_to_zero": compressed and start == end,
    }


def test_quality_report_surfaces_zero_duration_and_compression() -> None:
    rows = [_row(0, 0.0, 0.5), _row(1, 0.5, 0.5, selected_start=0.4, compressed=True)]
    report = build_quality_report(
        rows=rows,
        trace=[],
        expected_unit_count=2,
        audio_duration_sec=1.0,
        mode="windowed",
    )
    assert report["status"] == "warning"
    assert "final_zero_duration" in report["warnings"]
    assert "cross_window_overlap_compression" in report["warnings"]
    assert report["commit_diagnostics"]["collapsed_to_zero_count"] == 1


def test_write_alignment_bundle_writes_all_stages(tmp_path: Path) -> None:
    output = tmp_path / "alignment.json"
    payload = {
        "identity": {"mode": "windowed"},
        "summary": {"alignment_unit_count": 2, "audio_duration_sec": 2.0},
        "window_trace": [],
        "characters": [_row(0, 0.0, 0.5), _row(1, 0.5, 1.0)],
    }
    bundle = write_alignment_bundle(output, payload)
    expected = {
        "alignment.raw.json",
        "alignment.processor_decoded.json",
        "alignment.selected.json",
        "alignment.json",
        "alignment.quality.json",
    }
    assert expected == {path.name for path in tmp_path.iterdir()}
    final = json.loads(output.read_text(encoding="utf-8"))
    assert final["artifact_stage"] == "final"
    assert final["artifact_bundle"]["quality_status"] == "passed_structural"
    assert bundle["quality"]["status"] == "passed_structural"
