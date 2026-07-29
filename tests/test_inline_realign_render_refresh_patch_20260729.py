from __future__ import annotations

from pathlib import Path

from lyricalign.demo.timeline_video import _audio_input_layout_options, _progress_x_expression
from lyricalign.demo.visual_diagnostics import _row_display_label


def test_timeline_label_uses_space_not_colon() -> None:
    row = {"global_character_index": 17, "display_text": "字", "start_sec": 1.0, "end_sec": 1.2}
    assert _row_display_label(row) == "17 字"
    assert ":" not in _row_display_label(row)


def test_progress_pointer_resets_for_each_page() -> None:
    pages = [
        {
            "start_sec": 0.0,
            "end_sec": 1.0,
            "width": 1920,
            "height": 1080,
            "timeline_axis_px": {"left": 100, "right": 1800, "top": 100, "bottom": 800},
        },
        {
            "start_sec": 1.0,
            "end_sec": 2.0,
            "width": 1920,
            "height": 1080,
            "timeline_axis_px": {"left": 120, "right": 1750, "top": 100, "bottom": 800},
        },
    ]
    expression = _progress_x_expression(pages, line_width=3, fps=12)
    assert "n-0" in expression
    assert "n-12" in expression
    assert "if(lt(n,12)" in expression
    assert "if(lt(n,24)" in expression


def test_missing_stereo_layout_is_declared(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "lyricalign.demo.timeline_video._probe_media",
        lambda _: {
            "duration_sec": 1.0,
            "streams": [{"codec_type": "audio", "channels": 2}],
        },
    )
    options, probe = _audio_input_layout_options(tmp_path / "audio.wav")
    assert options == ["-channel_layout", "stereo"]
    assert probe["streams"][0]["channels"] == 2
