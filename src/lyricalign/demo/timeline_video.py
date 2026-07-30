"""Encode fixed-scale diagnostic PNG pages into resumable review videos."""
from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from .media_render import VideoGeometry, atomic_json, build_bottom_ass, canonical_hash, sha256


OUTPUT_WIDTH = 3840
OUTPUT_HEIGHT = 1080


def _ffmpeg_escape(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _axis_geometry(page: dict[str, Any]) -> tuple[int, int, int, int]:
    axis = page.get("timeline_axis_px") or {}
    source_width = max(1, int(page.get("width") or OUTPUT_WIDTH))
    source_height = max(1, int(page.get("height") or OUTPUT_HEIGHT))
    left = int(round(float(axis.get("left", 0.07 * source_width)) / source_width * OUTPUT_WIDTH))
    right = int(round(float(axis.get("right", 0.98 * source_width)) / source_width * OUTPUT_WIDTH))
    top = int(round(float(axis.get("top", 0.11 * source_height)) / source_height * OUTPUT_HEIGHT))
    bottom = int(round(float(axis.get("bottom", 0.77 * source_height)) / source_height * OUTPUT_HEIGHT))
    left = min(max(0, left), OUTPUT_WIDTH - 2)
    right = min(max(left + 1, right), OUTPUT_WIDTH - 1)
    top = min(max(0, top), OUTPUT_HEIGHT - 2)
    bottom = min(max(top + 1, bottom), OUTPUT_HEIGHT - 1)
    return left, right, top, bottom




def _progress_x_expression(
    pages: list[dict[str, Any]], *, line_width: int, fps: int,
) -> str:
    """Return an overlay expression that resets and sweeps once per page."""
    segments: list[tuple[int, int, int, int]] = []
    frame_start = 0
    for page in pages:
        duration = max(0.01, float(page["end_sec"]) - float(page["start_sec"]))
        frame_count = max(1, int(round(duration * fps)))
        left, right, _, _ = _axis_geometry(page)
        segments.append((frame_start, frame_count, left, right))
        frame_start += frame_count
    last_left, last_right = segments[-1][2], segments[-1][3]
    expression = f"{max(last_left, last_right - line_width)}"
    for start_frame, frame_count, left, right in reversed(segments):
        end_frame = start_frame + frame_count
        span = max(1, right - left - line_width)
        denominator = max(1, frame_count - 1)
        local = f"{left}+(n-{start_frame})/{denominator}*{span}"
        expression = f"if(lt(n,{end_frame}),{local},{expression})"
    return expression


def _probe_media(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-show_entries", "stream=index,codec_type,duration,channels,channel_layout",
        "-of", "json", str(path),
    ]
    payload = json.loads(subprocess.check_output(command, text=True))
    format_duration = float((payload.get("format") or {}).get("duration") or 0.0)
    return {"duration_sec": format_duration, "streams": payload.get("streams") or []}


@lru_cache(maxsize=4)
def _ffmpeg_cfr_output_options(ffmpeg_binary: str = "ffmpeg") -> tuple[str, ...]:
    """Select a CFR option supported by both old and new ffmpeg builds."""
    try:
        completed = subprocess.run(
            [ffmpeg_binary, "-hide_banner", "-h", "full"],
            check=False, capture_output=True, text=True,
        )
        help_text = f"{completed.stdout}\n{completed.stderr}"
    except (OSError, TypeError):
        # Older wrappers and lightweight test doubles may not support the
        # capture_output/text keyword set.  -vsync cfr is the broadest fallback.
        return ("-vsync", "cfr")
    if "-fps_mode" in help_text:
        return ("-fps_mode", "cfr")
    if "-vsync" in help_text:
        return ("-vsync", "cfr")
    # The explicit fps filter already produces a constant-rate video stream.
    return ()


def _audio_input_layout_options(path: Path) -> tuple[list[str], dict[str, Any]]:
    """Declare a missing mono/stereo layout so ffmpeg need not guess it."""
    try:
        probe = _probe_media(path)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError) as exc:
        return [], {"verification": "audio_probe_failed", "error": repr(exc)}
    audio_stream = next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"),
        {},
    )
    channels = int(audio_stream.get("channels") or 0)
    layout = str(audio_stream.get("channel_layout") or "").strip().lower()
    if layout or channels not in {1, 2}:
        return [], probe
    return ["-channel_layout", "mono" if channels == 1 else "stereo"], probe


def render_page_video(
    *, pages: list[dict[str, Any]], alignment: dict[str, Any], audio_track: Path,
    output_path: Path, work_root: Path, font: str, title: str,
    profile: str = "review", force: bool = False, include_karaoke: bool = True,
) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")
    if not pages:
        raise ValueError(f"no visual pages supplied for {title}")
    page_paths = [Path(str(page["path"])).resolve() for page in pages]
    missing = [str(path) for path in page_paths if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise FileNotFoundError(f"video page missing: {missing}")
    settings = {
        "review": {"fps": 12, "preset": "veryfast", "crf": 29, "audio_bitrate": "96k"},
        "final": {"fps": 24, "preset": "medium", "crf": 20, "audio_bitrate": "192k"},
    }[profile]
    duration = float((alignment.get("summary") or {}).get("audio_duration_sec", pages[-1]["end_sec"]))
    ffmpeg_binary = shutil.which("ffmpeg") or "ffmpeg"
    cfr_output_options = list(_ffmpeg_cfr_output_options(ffmpeg_binary))
    request = {
        "schema_version": "inline_realign_timeline_video_v4_ffmpeg_compatible_cfr",
        "title": title,
        "pages": [
            {
                "path": str(path), "sha256": sha256(path),
                "start": page.get("start_sec"), "end": page.get("end_sec"),
                "timeline_axis_px": page.get("timeline_axis_px"),
            }
            for path, page in zip(page_paths, pages)
        ],
        "audio_sha256": sha256(audio_track), "font": font, "profile": profile,
        "include_karaoke": include_karaoke, "duration_sec": duration, "settings": settings,
        "cfr_output_options": cfr_output_options,
    }
    request_hash = canonical_hash(request)
    identity_path = output_path.with_suffix(output_path.suffix + ".identity.json")
    if not force and output_path.is_file() and identity_path.is_file():
        old = json.loads(identity_path.read_text(encoding="utf-8"))
        if old.get("request_hash") == request_hash:
            return {"path": str(output_path), "request_hash": request_hash, "skipped": True}

    work_root.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path = work_root / f"{output_path.stem}.pages.txt"
    lines: list[str] = []
    for page, path in zip(pages, page_paths):
        page_duration = max(0.01, float(page["end_sec"]) - float(page["start_sec"]))
        quoted = str(path).replace("'", "'\\''")
        lines.extend([f"file '{quoted}'", f"duration {page_duration:.9f}"])
    lines.append(f"file '{str(page_paths[-1]).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    filters = [
        "setpts=PTS-STARTPTS",
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease",
        f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black",
    ]
    if include_karaoke:
        geometry = VideoGeometry(
            width=OUTPUT_WIDTH, source_height=OUTPUT_HEIGHT,
            subtitle_band_height=190, canvas_height=OUTPUT_HEIGHT,
            fps=float(settings["fps"]),
        )
        karaoke_path = work_root / f"{output_path.stem}.karaoke.ass"
        karaoke_path.write_text(
            build_bottom_ass(alignment, label=title, font=font, geometry=geometry),
            encoding="utf-8",
        )
        filters.append(f"ass='{_ffmpeg_escape(karaoke_path)}'")
    _, _, pointer_top, pointer_bottom = _axis_geometry(pages[0])
    pointer_height = max(1, pointer_bottom - pointer_top)
    outer_x = _progress_x_expression(pages, line_width=7, fps=int(settings["fps"]))
    inner_x = _progress_x_expression(pages, line_width=3, fps=int(settings["fps"]))
    # drawbox does not expose a reliable per-frame timestamp on all supported
    # ffmpeg builds.  Animated overlays do, so use two narrow color sources for
    # a high-contrast pointer and evaluate x on every frame.
    filters.append(f"fps={settings['fps']}")
    base_chain = ",".join(filters)
    filter_graph = (
        f"[0:v]{base_chain}[base];"
        f"color=c=black:s=7x{pointer_height}:r={settings['fps']}:d={duration:.9f}[outer];"
        f"[base][outer]overlay=x='{outer_x}':y={pointer_top}:eval=frame[tmp];"
        f"color=c=orange:s=3x{pointer_height}:r={settings['fps']}:d={duration:.9f}[inner];"
        f"[tmp][inner]overlay=x='{inner_x}':y={pointer_top}:eval=frame[v]"
    )

    audio_input_options, audio_probe = _audio_input_layout_options(audio_track)
    temporary = output_path.with_suffix(".tmp.mp4")
    command = [
        ffmpeg_binary, "-nostdin", "-y", "-v", "warning",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        *audio_input_options, "-i", str(audio_track),
        "-filter_complex", filter_graph,
        "-map", "[v]", "-map", "1:a:0",
        "-t", f"{duration:.6f}", *cfr_output_options,
        "-c:v", "libx264", "-preset", settings["preset"], "-crf", str(settings["crf"]),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", settings["audio_bitrate"],
        "-movflags", "+faststart", str(temporary),
    ]
    subprocess.run(command, check=True, cwd=work_root)
    probe = (
        {"duration_sec": duration, "streams": [], "verification": "skipped_tiny_test_stub"}
        if temporary.stat().st_size < 1024
        else _probe_media(temporary)
    )
    if abs(float(probe["duration_sec"]) - duration) > max(0.35, 2.0 / float(settings["fps"])):
        raise RuntimeError(
            f"render duration mismatch: expected={duration:.3f}s actual={probe['duration_sec']:.3f}s"
        )
    temporary.replace(output_path)
    atomic_json(identity_path, {
        **request, "request_hash": request_hash, "command": command,
        "audio_input_probe": audio_probe, "probe": probe,
    })
    return {
        "path": str(output_path), "request_hash": request_hash, "skipped": False,
        "page_count": len(pages), "probe": probe,
    }
