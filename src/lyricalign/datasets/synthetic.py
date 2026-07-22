"""Safe same-song synthetic-long construction with shifted character timelines."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any
from lyricalign.datasets.m4singer import sha256_file


SYNTHETIC_VERSION = "synthetic_long_v2"


def segment_order(item_id: str) -> int:
    try:
        return int(item_id.rsplit("#", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"item id has no numeric segment suffix: {item_id}") from exc


def validate_source_annotations(source_rows: list[dict[str, Any]], annotations: dict[str, list[dict[str, Any]]]) -> None:
    for source in source_rows:
        item_id = str(source["item_id"])
        expected = len(str(source.get("lyrics_normalized", "")))
        rows = annotations.get(item_id, [])
        indices = [row.get("character_index") for row in rows]
        duration = float(source["duration_sec"])
        if len(rows) != expected or sorted(indices) != list(range(expected)):
            raise ValueError(f"incomplete or duplicate character annotations for {item_id}")
        previous_start = previous_end = -1.0
        for row in sorted(rows, key=lambda r: int(r["character_index"])):
            start, end = row.get("start_sec"), row.get("end_sec")
            if start is None or end is None or float(start) < 0 or float(start) >= float(end) or float(start) < previous_start or float(end) < previous_end or float(end) > duration + 0.001:
                raise ValueError(f"invalid character interval for {item_id}")
            previous_start, previous_end = float(start), float(end)


def shifted_annotations(rows: list[dict[str, Any]], offsets: dict[str, float]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if row.get("start_sec") is None or row.get("end_sec") is None:
            raise ValueError(f"missing character interval for {row.get('item_id')}")
        copied = dict(row)
        offset = offsets[str(row["item_id"])]
        copied["start_sec"] = float(row["start_sec"]) + offset
        copied["end_sec"] = float(row["end_sec"]) + offset
        result.append(copied)
    return result


def concat_wavs(sources: list[Path], output: Path) -> tuple[float, list[tuple[float, float]]]:
    if not sources:
        raise ValueError("no sources")
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(sources[0]), "rb") as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
        total_frames = first.getnframes()
        compatible = True
    for path in sources[1:]:
        with wave.open(str(path), "rb") as handle:
            if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getcomptype()) != (params.nchannels, params.sampwidth, params.framerate, params.comptype):
                compatible = False
            frames.append(handle.readframes(handle.getnframes()))
            total_frames += handle.getnframes()
    temporary = output.with_suffix(".tmp.wav")
    if not compatible:
        filters = []
        for index in range(len(sources)):
            filters.append(f"[{index}:a]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono[a{index}]")
        filters.append("".join(f"[a{index}]" for index in range(len(sources))) + f"concat=n={len(sources)}:v=0:a=1[out]")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", *sum((["-i", str(path)] for path in sources), []), "-filter_complex", ";".join(filters), "-map", "[out]", "-c:a", "pcm_s16le", str(temporary)],
            check=True, capture_output=True, text=True,
        )
        with wave.open(str(temporary), "rb") as handle:
            duration = handle.getnframes() / handle.getframerate()
        temporary.replace(output)
        return duration, []
    with wave.open(str(temporary), "wb") as handle:
        handle.setparams(params)
        for payload in frames:
            handle.writeframes(payload)
    temporary.replace(output)
    cursor = 0
    ranges = []
    for path in sources:
        with wave.open(str(path), "rb") as handle:
            start, cursor = cursor, cursor + handle.getnframes()
            ranges.append((start / params.framerate, cursor / params.framerate))
    return total_frames / params.framerate, ranges


def build_synthetic_manifest(source_rows: list[dict[str, Any]], duration_sec: float, output_relpath: str, *, source_ranges: list[tuple[float, float]] | None = None, output_audio_sha256: str | None = None, annotation_sha256: str | None = None) -> dict[str, Any]:
    if not source_rows or len({str(row["song_id"]) for row in source_rows}) != 1 or len({str(row["singer_id"]) for row in source_rows}) != 1:
        raise ValueError("synthetic sources must be non-empty and from exactly one song and singer")
    if len({str(row.get("split", "")) for row in source_rows}) != 1:
        raise ValueError("synthetic sources must have exactly one split")
    ordered = sorted(source_rows, key=lambda row: segment_order(str(row["item_id"])))
    orders = [segment_order(str(row["item_id"])) for row in ordered]
    if orders != list(range(orders[0], orders[0] + len(orders))):
        raise ValueError("synthetic sources must be adjacent segments")
    offsets, cursor = {}, 0.0
    if source_ranges is None:
        source_ranges = []
        for row in ordered:
            source_ranges.append((cursor, cursor + float(row["duration_sec"])))
            cursor += float(row["duration_sec"])
    if len(source_ranges) != len(ordered): raise ValueError("source range count mismatch")
    for row, (start, end) in zip(ordered, source_ranges, strict=True):
        offsets[str(row["item_id"])] = start
    item_id = "synthetic:" + "+".join(str(row["item_id"]) for row in ordered)
    return {
        "schema_version": 1, "dataset_id": "m4singer_synthetic_long", "item_id": item_id,
        "song_id": ordered[0]["song_id"], "singer_id": ordered[0]["singer_id"], "audio_relpath": output_relpath,
        "duration_sec": duration_sec, "split": ordered[0]["split"], "length_source": "synthetic_concat",
        "source_item_ids": [row["item_id"] for row in ordered], "source_order": orders,
        "cumulative_offsets": offsets, "join_points_sec": [offsets[row["item_id"]] for row in ordered[1:]],
        "target_duration_sec": None, "actual_duration_sec": duration_sec,
        "source_ranges": [{"item_id": row["item_id"], "source_start_sec": 0.0, "source_end_sec": end - start, "output_start_sec": start, "output_end_sec": end} for row, (start, end) in zip(ordered, source_ranges, strict=True)],
        "source_audio_sha256": [row.get("audio_sha256") for row in ordered], "output_audio_sha256": output_audio_sha256, "annotation_sha256": annotation_sha256,
        "seam_mask": [[offsets[row["item_id"]], offsets[row["item_id"]]] for row in ordered[1:]],
        "silence_inserted_sec": 0.0, "status": "accepted", "quality_tier": "A_high_confidence",
        "synthetic_version": SYNTHETIC_VERSION,
    }
