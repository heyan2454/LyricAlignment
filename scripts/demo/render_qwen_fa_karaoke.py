#!/usr/bin/env python3
"""Render 12 KTV videos plus four 3-way and three 4-way comparisons."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.demo.karaoke import ass_escape, ass_time

SCHEMA_VERSION = "qwen_fa_karaoke_render_v2_multilingual_units"


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


def build_ass(
    alignment: dict[str, Any],
    *,
    label: str,
    font: str,
    width: int,
    height: int,
) -> str:
    characters = alignment["characters"]
    line_specs = alignment["lines"]
    by_line: dict[int, list[dict[str, Any]]] = {}
    for row in characters:
        by_line.setdefault(int(row["line_index"]), []).append(row)
    duration = float(alignment["summary"]["audio_duration_sec"])
    font_size = 52 if width >= 1280 else 42
    outline = 3
    y_positions = [int(height * 0.72), int(height * 0.86)]
    events: list[str] = []
    events.append(
        f"Dialogue: 0,{ass_time(0)},{ass_time(duration)},Meta,,0,0,0,,"
        f"{{\\an7\\pos(36,32)}}{ass_escape(label)}"
    )

    starts: list[float] = []
    ends: list[float] = []
    for line in line_specs:
        rows = sorted(by_line.get(int(line["line_index"]), []), key=lambda row: int(row["index_in_line"]))
        if not rows:
            starts.append(duration)
            ends.append(duration)
        else:
            starts.append(float(rows[0]["start_sec"]))
            ends.append(float(rows[-1]["end_sec"]))

    for index, line in enumerate(line_specs):
        rows = sorted(by_line.get(int(line["line_index"]), []), key=lambda row: int(row["index_in_line"]))
        if not rows:
            continue
        line_start = max(0.0, starts[index])
        line_end = max(line_start + 0.01, ends[index])
        next_start = starts[index + 1] if index + 1 < len(starts) else duration
        active_end = max(line_end, min(duration, next_start))
        preview_start = starts[index - 1] if index > 0 else 0.0
        preview_end = line_start
        y = y_positions[index % 2]
        display_text = "".join(str(row.get("display_prefix", "")) + str(row.get("display_text") or row.get("alignment_unit") or row["character"]) + str(row.get("display_suffix", "")) for row in rows)
        visual_units = sum(0.5 if char.isspace() else 1.0 for char in display_text)
        line_font_size = min(font_size, max(30, int((width - 100) / max(visual_units, 1.0))))
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
                duration_cs = max(1, int(round(max(float(row["end_sec"]) - current_start, 0.01) * 100)))
            visible = ass_escape(str(row.get("display_prefix", "")) + str(row.get("display_text") or row.get("alignment_unit") or row["character"]) + str(row.get("display_suffix", "")))
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
            f"Style: Preview,{font},{font_size},&H00A0A0A0,&H00A0A0A0,&H00101010,&H00000000,"
            f"0,0,0,0,100,100,2,0,1,{outline},0,2,40,40,20,1",
            f"Style: Karaoke,{font},{font_size},&H0000E8FF,&H00909090,&H00101010,&H00000000,"
            f"1,0,0,0,100,100,2,0,1,{outline},0,2,40,40,20,1",
            f"Style: Meta,{font},26,&H00D0D0D0,&H00D0D0D0,&H00101010,&H00000000,"
            "0,0,0,0,100,100,1,0,1,2,0,7,20,20,20,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )


def current(path: Path, identity_path: Path, request_hash: str) -> bool:
    if not path.is_file() or not identity_path.is_file():
        return False
    try:
        data = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("request_hash") == request_hash


def run_ffmpeg(command: list[str], *, cwd: Path | None = None) -> None:
    print(json.dumps({"ffmpeg": command}, ensure_ascii=False), flush=True)
    subprocess.run(command, check=True, cwd=cwd)


def render_individual(
    *,
    alignment_path: Path,
    audio_path: Path,
    output_path: Path,
    ass_path: Path,
    label: str,
    font: str,
    width: int,
    height: int,
    fps: int,
    force: bool,
) -> dict[str, Any]:
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    request = {
        "schema_version": SCHEMA_VERSION,
        "alignment_request_hash": alignment["identity"]["request_hash"],
        "audio_sha256": sha256(audio_path),
        "label": label,
        "font": font,
        "width": width,
        "height": height,
        "fps": fps,
    }
    request_hash = canonical_hash(request)
    identity_path = output_path.with_suffix(output_path.suffix + ".identity.json")
    if not force and current(output_path, identity_path, request_hash):
        return {"path": str(output_path), "request_hash": request_hash, "skipped": True}
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(
        build_ass(alignment, label=label, font=font, width=width, height=height),
        encoding="utf-8",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.mp4")
    duration = float(alignment["summary"]["audio_duration_sec"])
    run_ffmpeg(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "warning",
            "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}:d={duration:.6f}",
            "-i", str(audio_path),
            "-vf", f"ass={ass_path.name}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
            str(temporary),
        ],
        cwd=ass_path.parent,
    )
    temporary.replace(output_path)
    atomic_json(identity_path, {**request, "request_hash": request_hash})
    return {"path": str(output_path), "request_hash": request_hash, "skipped": False}


def render_composite(
    *,
    sources: list[Path],
    source_hashes: list[str],
    output_path: Path,
    layout: str,
    force: bool,
) -> dict[str, Any]:
    request = {
        "schema_version": SCHEMA_VERSION,
        "source_request_hashes": source_hashes,
        "layout": layout,
    }
    request_hash = canonical_hash(request)
    identity_path = output_path.with_suffix(output_path.suffix + ".identity.json")
    if not force and current(output_path, identity_path, request_hash):
        return {"path": str(output_path), "request_hash": request_hash, "skipped": True}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.mp4")
    command = ["ffmpeg", "-nostdin", "-y", "-v", "warning"]
    for source in sources:
        command.extend(["-i", str(source)])
    if layout == "three":
        filters = (
            "[0:v]scale=960:540[v0];[1:v]scale=960:540[v1];[2:v]scale=960:540[v2];"
            "[v0][v1][v2]xstack=inputs=3:layout=0_0|w0_0|0_h0:fill=black[v]"
        )
    elif layout == "four":
        filters = (
            "[0:v]scale=960:540[v0];[1:v]scale=960:540[v1];"
            "[2:v]scale=960:540[v2];[3:v]scale=960:540[v3];"
            "[v0][v1][v2][v3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0:fill=black[v]"
        )
    else:
        raise ValueError(layout)
    command.extend(
        [
            "-filter_complex", filters,
            "-map", "[v]", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
            str(temporary),
        ]
    )
    run_ffmpeg(command)
    temporary.replace(output_path)
    atomic_json(identity_path, {**request, "request_hash": request_hash})
    return {"path": str(output_path), "request_hash": request_hash, "skipped": False}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--mix-audio", type=Path, required=True)
    parser.add_argument("--vocal-audio", type=Path, required=True)
    parser.add_argument("--font", default="Noto Sans CJK SC")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required")
    font = detect_font(args.font)
    audio_paths = {"mix": args.mix_audio, "vocal": args.vocal_audio}
    audio_labels = {"mix": "原音频", "vocal": "分离人声"}
    mode_labels = {"full": "不分窗", "windowed": "串行分窗"}
    results: dict[tuple[str, str, str], dict[str, Any]] = {}
    manifest_rows: list[dict[str, Any]] = []
    for model in ("r0", "r1", "r2"):
        for audio in ("mix", "vocal"):
            for mode in ("full", "windowed"):
                alignment = args.out_root / "alignments" / model / audio / mode / "alignment.json"
                if not alignment.is_file():
                    raise FileNotFoundError(alignment)
                stem = f"{model}_{audio}_{mode}"
                rendered = render_individual(
                    alignment_path=alignment,
                    audio_path=audio_paths[audio],
                    output_path=args.out_root / "videos" / "individual" / f"{stem}.mp4",
                    ass_path=args.out_root / "subtitles" / f"{stem}.ass",
                    label=f"{model.upper()} · {audio_labels[audio]} · {mode_labels[mode]}",
                    font=font,
                    width=args.width,
                    height=args.height,
                    fps=args.fps,
                    force=args.force,
                )
                results[(model, audio, mode)] = rendered
                manifest_rows.append({"kind": "individual", "model": model, "audio": audio, "mode": mode, **rendered})

    for audio in ("mix", "vocal"):
        for mode in ("full", "windowed"):
            keys = [(model, audio, mode) for model in ("r0", "r1", "r2")]
            composite = render_composite(
                sources=[Path(results[key]["path"]) for key in keys],
                source_hashes=[str(results[key]["request_hash"]) for key in keys],
                output_path=args.out_root / "videos" / "comparisons" / f"compare_models_{audio}_{mode}.mp4",
                layout="three",
                force=args.force,
            )
            manifest_rows.append({"kind": "three_way", "audio": audio, "mode": mode, **composite})

    for model in ("r0", "r1", "r2"):
        keys = [
            (model, "mix", "full"),
            (model, "mix", "windowed"),
            (model, "vocal", "full"),
            (model, "vocal", "windowed"),
        ]
        composite = render_composite(
            sources=[Path(results[key]["path"]) for key in keys],
            source_hashes=[str(results[key]["request_hash"]) for key in keys],
            output_path=args.out_root / "videos" / "comparisons" / f"compare_inputs_{model}.mp4",
            layout="four",
            force=args.force,
        )
        manifest_rows.append({"kind": "four_way", "model": model, "audio_track": "mix", **composite})

    atomic_json(
        args.out_root / "render_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "font": font,
            "individual_video_count": 12,
            "three_way_video_count": 4,
            "four_way_video_count": 3,
            "four_way_audio_policy": "original mix audio is used as the shared comparison timeline",
            "outputs": manifest_rows,
        },
    )


if __name__ == "__main__":
    main()
