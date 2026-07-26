from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.batch import IndividualMode, build_output_plan, discover_jobs
from lyricalign.demo.media_render import (
    VideoGeometry,
    build_bottom_ass,
    render_media_video,
)


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_discovery_pairs_same_stem_video_audio_and_txt(tmp_path: Path) -> None:
    _touch(tmp_path / "song.txt", "歌词")
    _touch(tmp_path / "song.mp4")
    _touch(tmp_path / "song.wav")
    _touch(tmp_path / "incomplete.txt", "无媒体")

    jobs = discover_jobs(tmp_path)
    assert len(jobs) == 1
    assert jobs[0].stem == "song"
    assert jobs[0].video == (tmp_path / "song.mp4").resolve()
    assert jobs[0].audio == (tmp_path / "song.wav").resolve()
    assert jobs[0].mix_source == jobs[0].audio


def test_default_and_composite_plans_expand_required_individuals() -> None:
    default = build_output_plan()
    assert default.individuals == (IndividualMode("r2", "vocal", "windowed"),)

    compare = build_output_plan(compare_models=["vocal:windowed"])
    assert set(compare.individuals) == {
        IndividualMode("r0", "vocal", "windowed"),
        IndividualMode("r1", "vocal", "windowed"),
        IndividualMode("r2", "vocal", "windowed"),
    }
    assert compare.compare_models == (("vocal", "windowed"),)

    inputs = build_output_plan(compare_inputs=["r2"])
    assert set(inputs.individuals) == {
        IndividualMode("r2", "mix", "full"),
        IndividualMode("r2", "mix", "windowed"),
        IndividualMode("r2", "vocal", "full"),
        IndividualMode("r2", "vocal", "windowed"),
    }


def _alignment() -> dict:
    return {
        "identity": {"request_hash": "alignment-hash"},
        "summary": {"audio_duration_sec": 1.0},
        "lines": [
            {"line_index": 0, "display_text": "甲乙", "character_start": 0, "character_end": 2},
            {"line_index": 1, "display_text": "丙丁", "character_start": 2, "character_end": 4},
        ],
        "characters": [
            {"global_character_index": 0, "line_index": 0, "index_in_line": 0, "character": "甲", "display_suffix": "", "start_sec": 0.0, "end_sec": 0.2},
            {"global_character_index": 1, "line_index": 0, "index_in_line": 1, "character": "乙", "display_suffix": "", "start_sec": 0.2, "end_sec": 0.45},
            {"global_character_index": 2, "line_index": 1, "index_in_line": 0, "character": "丙", "display_suffix": "", "start_sec": 0.5, "end_sec": 0.7},
            {"global_character_index": 3, "line_index": 1, "index_in_line": 1, "character": "丁", "display_suffix": "", "start_sec": 0.7, "end_sec": 0.95},
        ],
    }


def test_bottom_ass_rows_are_inside_separate_subtitle_band() -> None:
    geometry = VideoGeometry(width=1280, source_height=720, canvas_height=980, subtitle_band_height=260, fps=30.0)
    ass = build_bottom_ass(_alignment(), label="demo", font="DejaVu Sans", geometry=geometry)
    positions = [int(value) for value in re.findall(r"\\pos\(640,(\d+)\)", ass)]
    assert positions
    assert min(positions) > geometry.source_height
    assert len(set(positions)) == 2
    assert max(positions) - min(positions) >= 80
    assert "Outline" in ass


def test_video_render_adds_bottom_band_without_overlay(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    audio = tmp_path / "audio.wav"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ar", "44100", str(audio),
        ],
        check=True,
    )
    alignment = tmp_path / "alignment.json"
    alignment.write_text(json.dumps(_alignment(), ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "rendered.mp4"
    render_media_video(
        alignment_path=alignment,
        visual_source=video,
        audio_track=audio,
        output_path=output,
        ass_path=tmp_path / "subtitle.ass",
        label="demo",
        font="DejaVu Sans",
        force=True,
        subtitle_band_height=120,
    )
    probe = json.loads(
        subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "json", str(output),
            ],
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    )
    stream = probe["streams"][0]
    assert stream["width"] == 320
    assert stream["height"] == 400


def test_bottom_ass_uses_visible_word_text_not_model_only_tokens() -> None:
    alignment = {
        "identity": {"request_hash": "english"},
        "summary": {"audio_duration_sec": 1.0},
        "lines": [
            {"line_index": 0, "display_text": "Hello, world!", "character_start": 0, "character_end": 2}
        ],
        "characters": [
            {
                "global_character_index": 0,
                "line_index": 0,
                "index_in_line": 0,
                "character": "Hello",
                "alignment_unit": "Hello",
                "unit_type": "word",
                "display_prefix": "",
                "display_text": "Hello",
                "display_suffix": ", ",
                "start_sec": 0.0,
                "end_sec": 0.4,
            },
            {
                "global_character_index": 1,
                "line_index": 0,
                "index_in_line": 1,
                "character": "world",
                "alignment_unit": "world",
                "unit_type": "word",
                "display_prefix": "",
                "display_text": "world",
                "display_suffix": "!",
                "start_sec": 0.4,
                "end_sec": 0.9,
            },
        ],
    }
    geometry = VideoGeometry(
        width=1280,
        source_height=720,
        canvas_height=980,
        subtitle_band_height=260,
        fps=30.0,
    )
    ass = build_bottom_ass(alignment, label="English", font="Noto Sans", geometry=geometry)
    assert "{\\kf40}Hello, " in ass
    assert "{\\kf50}world!" in ass


def _write_tf_checkpoint(model_dir: Path, *, marker: bool = False) -> None:
    _touch(model_dir / "checkpoint", 'model_checkpoint_path: "model"\n')
    _touch(model_dir / "model.index", "index")
    _touch(model_dir / "model.data-00000-of-00001", "weights")
    if marker:
        _touch(model_dir / ".probe", "")


def test_spleeter_explicit_checkpoint_does_not_require_probe(tmp_path: Path) -> None:
    from lyricalign.demo.spleeter_model import resolve_spleeter_model

    model_dir = tmp_path / "models" / "2stems"
    _write_tf_checkpoint(model_dir, marker=False)
    info = resolve_spleeter_model(tmp_path / "models")
    assert info.model_dir == model_dir
    assert info.model_root == tmp_path / "models"
    assert info.layout == "tensorflow_checkpoint"
    assert info.marker_present is False
    assert info.as_dict()["identity_sha256"]


def test_spleeter_accepts_explicit_2stems_directory(tmp_path: Path) -> None:
    from lyricalign.demo.spleeter_model import resolve_spleeter_model

    model_dir = tmp_path / "explicit" / "2stems"
    _write_tf_checkpoint(model_dir, marker=True)
    info = resolve_spleeter_model(model_dir)
    assert info.model_dir == model_dir
    assert info.model_root == model_dir.parent
    assert info.marker_present is True


def test_spleeter_rejects_probe_without_weights(tmp_path: Path) -> None:
    import pytest
    from lyricalign.demo.spleeter_model import resolve_spleeter_model

    model_dir = tmp_path / "models" / "2stems"
    _touch(model_dir / ".probe", "")
    with pytest.raises(FileNotFoundError, match="complete Spleeter model weights"):
        resolve_spleeter_model(tmp_path / "models")
