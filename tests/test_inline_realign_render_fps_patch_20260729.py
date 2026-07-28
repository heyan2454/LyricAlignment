from __future__ import annotations

import json
from pathlib import Path

from lyricalign.demo.timeline_video import render_page_video


def test_render_page_video_identity_can_include_karaoke_without_typeerror(tmp_path: Path, monkeypatch):
    page = tmp_path / "page.png"
    page.write_bytes(b"png")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"wav")
    out = tmp_path / "out.mp4"

    calls = {}

    def fake_which(name: str):
        return "/usr/bin/" + name

    def fake_run(command, check, cwd):
        calls["command"] = command
        temporary = out.with_suffix(".tmp.mp4")
        temporary.write_bytes(b"mp4")
        return None

    monkeypatch.setattr("lyricalign.demo.timeline_video.shutil.which", fake_which)
    monkeypatch.setattr("lyricalign.demo.timeline_video.subprocess.run", fake_run)
    monkeypatch.setattr("lyricalign.demo.timeline_video.build_bottom_ass", lambda alignment, label, font, geometry: "ASS")

    result = render_page_video(
        pages=[{"path": str(page), "start_sec": 0.0, "end_sec": 1.0}],
        alignment={"summary": {"audio_duration_sec": 1.0}, "characters": []},
        audio_track=audio,
        output_path=out,
        work_root=tmp_path / "work",
        font="Noto Sans CJK SC",
        title="test",
        include_karaoke=True,
    )

    assert out.is_file()
    assert result["skipped"] is False
    identity = json.loads(out.with_suffix(".mp4.identity.json").read_text(encoding="utf-8"))
    assert identity["settings"]["fps"] == 12
