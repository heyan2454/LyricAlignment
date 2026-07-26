from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .karaoke import ass_escape, ass_time

RENDER_SCHEMA_VERSION = "qwen_fa_media_render_v2_multilingual_units"


@dataclass(frozen=True)
class VideoGeometry:
    width: int
    source_height: int
    canvas_height: int
    subtitle_band_height: int
    fps: float


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def detect_font(preferred: str) -> str:
    if not shutil.which("fc-match"):
        return preferred
    result = subprocess.run(
        ["fc-match", "-f", "%{family}\n", preferred],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.splitlines()[0].split(",")[0].strip() or preferred


def _parse_rate(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 30.0
    return float(value)


def probe_video(path: Path, *, subtitle_band_height: int | None = None) -> VideoGeometry:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate",
        "-of", "json", str(path),
    ]
    payload = json.loads(subprocess.run(command, check=True, text=True, capture_output=True).stdout)
    streams = payload.get("streams", [])
    if not streams:
        raise RuntimeError(f"no video stream found: {path}")
    stream = streams[0]
    width = int(stream["width"])
    height = int(stream["height"])
    if width <= 0 or height <= 0:
        raise RuntimeError(f"invalid video geometry: {width}x{height}")
    requested_band = subtitle_band_height or max(220, int(round(height * 0.28)))
    band = max(220, int(requested_band))
    # H.264/yuv420p requires even dimensions.
    width += width % 2
    height += height % 2
    band += band % 2
    return VideoGeometry(
        width=width,
        source_height=height,
        canvas_height=height + band,
        subtitle_band_height=band,
        fps=max(1.0, _parse_rate(str(stream.get("avg_frame_rate", "30/1")))),
    )


def audio_geometry(*, width: int = 1280, height: int = 720) -> VideoGeometry:
    width += width % 2
    height += height % 2
    return VideoGeometry(
        width=width,
        source_height=0,
        canvas_height=height,
        subtitle_band_height=height,
        fps=30.0,
    )


def build_bottom_ass(
    alignment: dict[str, Any],
    *,
    label: str,
    font: str,
    geometry: VideoGeometry,
) -> str:
    """Build two non-overlapping outlined karaoke rows in a bottom black band."""

    width = geometry.width
    height = geometry.canvas_height
    band_top = geometry.source_height
    band = geometry.subtitle_band_height
    rows_y = [
        int(band_top + band * 0.38),
        int(band_top + band * 0.78),
    ]
    max_font = max(28, min(58, int(band * 0.20)))
    outline = max(2, int(round(max_font / 18)))
    meta_size = max(18, int(max_font * 0.48))

    characters = alignment["characters"]
    line_specs = alignment["lines"]
    by_line: dict[int, list[dict[str, Any]]] = {}
    for row in characters:
        by_line.setdefault(int(row["line_index"]), []).append(row)
    duration = float(alignment["summary"]["audio_duration_sec"])

    events: list[str] = [
        f"Dialogue: 0,{ass_time(0)},{ass_time(duration)},Meta,,0,0,0,,"
        f"{{\\an7\\pos(24,{band_top + 18})}}{ass_escape(label)}"
    ]

    starts: list[float] = []
    ends: list[float] = []
    ordered_lines: list[list[dict[str, Any]]] = []
    for line in line_specs:
        rows = sorted(
            by_line.get(int(line["line_index"]), []),
            key=lambda row: int(row["index_in_line"]),
        )
        ordered_lines.append(rows)
        if rows:
            starts.append(float(rows[0]["start_sec"]))
            ends.append(float(rows[-1]["end_sec"]))
        else:
            starts.append(duration)
            ends.append(duration)

    for index, rows in enumerate(ordered_lines):
        if not rows:
            continue
        line_start = max(0.0, starts[index])
        line_end = max(line_start + 0.01, ends[index])
        next_start = starts[index + 1] if index + 1 < len(starts) else duration
        active_end = max(line_end, min(duration, next_start))
        preview_start = starts[index - 1] if index > 0 else 0.0
        preview_end = line_start
        y = rows_y[index % 2]
        display_text = "".join(
            str(row.get("display_prefix", ""))
            + str(row.get("display_text") or row.get("alignment_unit") or row["character"])
            + str(row.get("display_suffix", ""))
            for row in rows
        )
        visual_units = sum(0.5 if character.isspace() else 1.0 for character in display_text)
        line_font_size = min(max_font, max(24, int((width - 96) / max(visual_units, 1.0))))

        if preview_end - preview_start > 0.01:
            events.append(
                f"Dialogue: 0,{ass_time(preview_start)},{ass_time(preview_end)},Preview,,0,0,0,,"
                f"{{\\an5\\pos({width // 2},{y})\\fs{line_font_size}}}{ass_escape(display_text)}"
            )

        karaoke_parts: list[str] = []
        for char_index, row in enumerate(rows):
            current_start = float(row["start_sec"])
            if char_index + 1 < len(rows):
                next_char_start = float(rows[char_index + 1]["start_sec"])
                duration_cs = max(1, int(round(max(next_char_start - current_start, 0.01) * 100)))
            else:
                duration_cs = max(
                    1,
                    int(round(max(float(row["end_sec"]) - current_start, 0.01) * 100)),
                )
            visible = ass_escape(
                str(row.get("display_prefix", ""))
                + str(row.get("display_text") or row.get("alignment_unit") or row["character"])
                + str(row.get("display_suffix", ""))
            )
            karaoke_parts.append(f"{{\\kf{duration_cs}}}{visible}")
        events.append(
            f"Dialogue: 1,{ass_time(line_start)},{ass_time(active_end)},Karaoke,,0,0,0,,"
            f"{{\\an5\\pos({width // 2},{y})\\fs{line_font_size}}}{''.join(karaoke_parts)}"
        )

    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "ScaledBorderAndShadow: yes",
            "WrapStyle: 2",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding",
            f"Style: Preview,{font},{max_font},&H00A0A0A0,&H00A0A0A0,&H00101010,&H00000000,"
            f"0,0,0,0,100,100,2,0,1,{outline},0,2,40,40,20,1",
            f"Style: Karaoke,{font},{max_font},&H0000E8FF,&H00909090,&H00101010,&H00000000,"
            f"1,0,0,0,100,100,2,0,1,{outline},0,2,40,40,20,1",
            f"Style: Meta,{font},{meta_size},&H00D0D0D0,&H00D0D0D0,&H00101010,&H00000000,"
            "0,0,0,0,100,100,1,0,1,2,0,7,20,20,20,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )


def _output_is_current(output: Path, identity: Path, request_hash: str) -> bool:
    if not output.is_file() or not identity.is_file():
        return False
    try:
        payload = json.loads(identity.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("request_hash") == request_hash


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    print(json.dumps({"ffmpeg": command}, ensure_ascii=False), flush=True)
    subprocess.run(command, check=True, cwd=cwd)


def render_media_video(
    *,
    alignment_path: Path,
    visual_source: Path | None,
    audio_track: Path,
    output_path: Path,
    ass_path: Path,
    label: str,
    font: str,
    force: bool = False,
    subtitle_band_height: int | None = None,
    audio_width: int = 1280,
    audio_height: int = 720,
) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    geometry = (
        probe_video(visual_source, subtitle_band_height=subtitle_band_height)
        if visual_source is not None
        else audio_geometry(width=audio_width, height=audio_height)
    )
    request = {
        "schema_version": RENDER_SCHEMA_VERSION,
        "alignment_request_hash": alignment["identity"]["request_hash"],
        "visual_source": str(visual_source.resolve()) if visual_source else None,
        "visual_source_sha256": sha256(visual_source) if visual_source else None,
        "audio_track": str(audio_track.resolve()),
        "audio_track_sha256": sha256(audio_track),
        "label": label,
        "font": font,
        "geometry": geometry.__dict__,
    }
    request_hash = canonical_hash(request)
    identity_path = output_path.with_suffix(output_path.suffix + ".identity.json")
    if not force and _output_is_current(output_path, identity_path, request_hash):
        return {"path": str(output_path), "request_hash": request_hash, "skipped": True}

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(
        build_bottom_ass(alignment, label=label, font=font, geometry=geometry),
        encoding="utf-8",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.mp4")
    duration = float(alignment["summary"]["audio_duration_sec"])

    if visual_source is None:
        command = [
            "ffmpeg", "-nostdin", "-y", "-v", "warning",
            "-f", "lavfi", "-i",
            f"color=c=black:s={geometry.width}x{geometry.canvas_height}:r=30:d={duration:.6f}",
            "-i", str(audio_track),
            "-vf", f"ass={ass_path.name}",
            "-map", "0:v:0", "-map", "1:a:0",
        ]
    else:
        filter_graph = (
            f"[0:v]scale={geometry.width}:{geometry.source_height}:force_original_aspect_ratio=decrease,"
            f"pad={geometry.width}:{geometry.source_height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"pad={geometry.width}:{geometry.canvas_height}:0:0:black,ass={ass_path.name}[v]"
        )
        command = [
            "ffmpeg", "-nostdin", "-y", "-v", "warning",
            "-i", str(visual_source), "-i", str(audio_track),
            "-filter_complex", filter_graph,
            "-map", "[v]", "-map", "1:a:0",
        ]
    command.extend(
        [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
            str(temporary),
        ]
    )
    _run(command, cwd=ass_path.parent)
    temporary.replace(output_path)
    atomic_json(identity_path, {**request, "request_hash": request_hash})
    return {"path": str(output_path), "request_hash": request_hash, "skipped": False}


def render_composite(
    *,
    sources: Sequence[Path],
    source_hashes: Sequence[str],
    output_path: Path,
    layout: str,
    force: bool = False,
) -> dict[str, Any]:
    if layout not in ("three", "four"):
        raise ValueError(layout)
    expected = 3 if layout == "three" else 4
    if len(sources) != expected or len(source_hashes) != expected:
        raise ValueError(f"{layout} composite requires {expected} sources")
    request = {
        "schema_version": RENDER_SCHEMA_VERSION,
        "source_request_hashes": list(source_hashes),
        "layout": layout,
    }
    request_hash = canonical_hash(request)
    identity_path = output_path.with_suffix(output_path.suffix + ".identity.json")
    if not force and _output_is_current(output_path, identity_path, request_hash):
        return {"path": str(output_path), "request_hash": request_hash, "skipped": True}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.mp4")
    command = ["ffmpeg", "-nostdin", "-y", "-v", "warning"]
    for source in sources:
        command.extend(["-i", str(source)])
    if layout == "three":
        filters = (
            "[0:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black[v0];"
            "[1:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black[v1];"
            "[2:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black[v2];"
            "[v0][v1][v2]xstack=inputs=3:layout=0_0|w0_0|0_h0:fill=black[v]"
        )
    else:
        filters = (
            "[0:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black[v0];"
            "[1:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black[v1];"
            "[2:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black[v2];"
            "[3:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black[v3];"
            "[v0][v1][v2][v3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0:fill=black[v]"
        )
    command.extend(
        [
            "-filter_complex", filters,
            "-map", "[v]", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
            str(temporary),
        ]
    )
    _run(command)
    temporary.replace(output_path)
    atomic_json(identity_path, {**request, "request_hash": request_hash})
    return {"path": str(output_path), "request_hash": request_hash, "skipped": False}
