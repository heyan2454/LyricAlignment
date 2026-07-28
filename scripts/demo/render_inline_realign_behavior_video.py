#!/usr/bin/env python3
"""Render a K-song video with per-window raw/official/decoder behavior overlays."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.karaoke import ass_escape, ass_time
from lyricalign.demo.media_render import (
    VideoGeometry, atomic_json, audio_geometry, build_bottom_ass, canonical_hash,
    detect_font, probe_video, sha256,
)


def _unit_text(row: dict[str, Any]) -> str:
    return str(row.get("display_text") or row.get("alignment_unit") or row.get("character") or "")


def _compact_units(rows: list[dict[str, Any]], start: int, end: int, limit: int = 28) -> str:
    chosen = [row for row in rows if start <= int(row.get("global_character_index", -1)) < end]
    text = "".join(_unit_text(row) for row in chosen[:limit])
    return text + ("…" if len(chosen) > limit else "")


def _progress_bar(duration: float, cells: int = 32) -> str:
    centiseconds = max(1, int(round(max(duration, 0.01) * 100 / cells)))
    return "".join(f"{{\\kf{centiseconds}}}■" for _ in range(cells))


def build_behavior_ass(alignment: dict[str, Any], *, font: str, geometry: VideoGeometry, label: str) -> str:
    base = build_bottom_ass(alignment, label=label, font=font, geometry=geometry)
    lines = base.splitlines()
    style_index = lines.index("[Events]")
    debug_styles = [
        f"Style: Debug,{font},20,&H00F2F2F2,&H00F2F2F2,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,2,1,7,18,18,12,1",
        f"Style: DebugSmall,{font},16,&H00D8D8D8,&H00D8D8D8,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,2,1,7,18,18,12,1",
        f"Style: Progress,{font},18,&H0000E8FF,&H00606060,&H00101010,&H90000000,1,0,0,0,100,100,0,0,1,2,1,7,18,18,12,1",
    ]
    # Add styles just before [Events].
    lines[style_index:style_index] = debug_styles + [""]
    alignment_rows = list(alignment.get("characters", []))
    events: list[str] = []
    for position, window in enumerate(alignment.get("window_trace", [])):
        if window.get("silent_core_skipped"):
            continue
        start = float(window.get("core_start_sec", window.get("input_start_sec", 0.0)))
        end = float(window.get("core_end_sec", window.get("input_end_sec", start + 0.01)))
        if position + 1 < len(alignment.get("window_trace", [])):
            next_start = float(alignment["window_trace"][position + 1].get("core_start_sec", end))
            end = max(end, min(next_start, end + 2.0))
        unit_start = int(window.get("input_character_start_before", window.get("committed_character_start", 0)))
        unit_end = int(window.get("candidate_character_end", window.get("committed_character_end", unit_start)))
        committed_before = int(window.get("committed_cursor_before", 0))
        committed_after = int(window.get("committed_cursor_after", window.get("committed_character_end", 0)))
        shadow = list(window.get("shadow_rows") or [])
        raw_text = _compact_units(shadow, unit_start, unit_end)
        official_text = _compact_units(alignment_rows, unit_start, unit_end)
        diagnostic = window.get("precommit_diagnostic") or {}
        reasons = ",".join(str(value) for value in diagnostic.get("reasons", [])[:3]) or "none"
        zero_count = sum(
            float(row.get("end_sec", row.get("fixed_global_end_sec", 0.0)))
            <= float(row.get("start_sec", row.get("fixed_global_start_sec", 0.0))) + 1e-9
            for row in alignment_rows
            if int(window.get("committed_character_start", 0))
            <= int(row.get("global_character_index", -1))
            < int(window.get("committed_character_end", 0))
        )
        prefix = window.get("stable_suffix_candidate") or {}
        stable_text = str(prefix.get("text") or "-")
        planner = str(window.get("serial_control_decoder_kind") or "official")
        title = (
            f"W{window.get('window_index')}  time {start:.1f}-{end:.1f}s  "
            f"input {unit_start}:{unit_end}  commit {committed_before}->{committed_after}  planner={planner}"
        )
        details = f"detector={reasons}  zero(commit)={zero_count}  stable={stable_text[:24]}"
        raw_line = f"RAW: {raw_text}"
        official_line = f"OFFICIAL: {official_text}"
        y0 = 24
        for layer, (text, y, style) in enumerate([
            (title, y0, "Debug"), (details, y0 + 26, "DebugSmall"),
            (raw_line, y0 + 50, "DebugSmall"), (official_line, y0 + 73, "DebugSmall"),
        ]):
            events.append(
                f"Dialogue: {5 + layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,"
                f"{{\\an7\\pos(20,{y})}}{ass_escape(text)}"
            )
        events.append(
            f"Dialogue: 10,{ass_time(start)},{ass_time(end)},Progress,,0,0,0,,"
            f"{{\\an7\\pos(20,{y0 + 98})}}{_progress_bar(end - start)}"
        )
    # Append events after the Events format row.
    event_format_index = next(index for index, value in enumerate(lines) if value.startswith("Format: Layer"))
    lines[event_format_index + 1:event_format_index + 1] = events
    return "\n".join(lines) + "\n"


def render_behavior_video(
    *, alignment_path: Path, visual_source: Path | None, audio_track: Path,
    output_path: Path, ass_path: Path, font: str, profile: str, force: bool,
) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    settings = {
        "review": {"fps": 24, "preset": "veryfast", "crf": 28, "audio_bitrate": "96k"},
        "final": {"fps": 30, "preset": "veryfast", "crf": 20, "audio_bitrate": "192k"},
    }[profile]
    geometry = probe_video(visual_source, subtitle_band_height=250) if visual_source else audio_geometry(width=1280, height=720)
    request = {
        "schema_version": "inline_realign_behavior_video_v1",
        "alignment_sha256": sha256(alignment_path),
        "visual_sha256": sha256(visual_source) if visual_source else None,
        "audio_sha256": sha256(audio_track), "font": font, "profile": profile,
        "geometry": geometry.__dict__, "settings": settings,
    }
    request_hash = canonical_hash(request)
    identity_path = output_path.with_suffix(output_path.suffix + ".identity.json")
    if not force and output_path.is_file() and identity_path.is_file():
        old = json.loads(identity_path.read_text(encoding="utf-8"))
        if old.get("request_hash") == request_hash:
            return {"path": str(output_path), "request_hash": request_hash, "skipped": True}
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(build_behavior_ass(alignment, font=font, geometry=geometry, label="B2 current · raw/official/window behavior"), encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.mp4")
    duration = float(alignment["summary"]["audio_duration_sec"])
    if visual_source:
        filter_graph = (
            f"[0:v]scale={geometry.width}:{geometry.source_height}:force_original_aspect_ratio=decrease,"
            f"pad={geometry.width}:{geometry.source_height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"pad={geometry.width}:{geometry.canvas_height}:0:0:black,ass={ass_path.name}[v]"
        )
        command = ["ffmpeg", "-nostdin", "-y", "-v", "warning", "-i", str(visual_source), "-i", str(audio_track), "-filter_complex", filter_graph, "-map", "[v]", "-map", "1:a:0"]
    else:
        command = ["ffmpeg", "-nostdin", "-y", "-v", "warning", "-f", "lavfi", "-i", f"color=c=black:s={geometry.width}x{geometry.canvas_height}:r={settings['fps']}:d={duration:.6f}", "-i", str(audio_track), "-vf", f"ass={ass_path.name}", "-map", "0:v:0", "-map", "1:a:0"]
    command.extend(["-r", str(settings["fps"]), "-c:v", "libx264", "-preset", settings["preset"], "-crf", str(settings["crf"]), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", settings["audio_bitrate"], "-shortest", "-movflags", "+faststart", str(temporary)])
    print(json.dumps({"ffmpeg": command}, ensure_ascii=False), flush=True)
    subprocess.run(command, check=True, cwd=ass_path.parent)
    temporary.replace(output_path)
    atomic_json(identity_path, {**request, "request_hash": request_hash})
    return {"path": str(output_path), "request_hash": request_hash, "skipped": False}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--alignment", type=Path, required=True)
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--visual-source", type=Path)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--profile", choices=("review", "final"), default="review")
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args(); font = detect_font(args.font)
    result = render_behavior_video(
        alignment_path=args.alignment.expanduser().resolve(),
        visual_source=args.visual_source.expanduser().resolve() if args.visual_source else None,
        audio_track=args.audio.expanduser().resolve(), output_path=args.output.expanduser().resolve(),
        ass_path=args.output.expanduser().resolve().parent / "work" / "behavior.ass",
        font=font, profile=args.profile, force=args.force,
    )
    print(json.dumps({"status": "complete", **result}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
