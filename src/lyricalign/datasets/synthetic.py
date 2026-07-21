"""Safe same-song synthetic-long construction with shifted character timelines."""

from __future__ import annotations

import hashlib
import subprocess
import wave
from pathlib import Path
from typing import Any


SYNTHETIC_VERSION = "synthetic_long_v1"


def segment_order(item_id: str) -> int:
    try:
        return int(item_id.rsplit("#", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"item id has no numeric segment suffix: {item_id}") from exc


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


def concat_wavs(sources: list[Path], output: Path) -> float:
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
        return duration
    with wave.open(str(temporary), "wb") as handle:
        handle.setparams(params)
        for payload in frames:
            handle.writeframes(payload)
    temporary.replace(output)
    return total_frames / params.framerate


def build_synthetic_manifest(source_rows: list[dict[str, Any]], duration_sec: float, output_relpath: str) -> dict[str, Any]:
    if not source_rows or len({str(row["song_id"]) for row in source_rows}) != 1 or len({str(row["singer_id"]) for row in source_rows}) != 1:
        raise ValueError("synthetic sources must be non-empty and from exactly one song and singer")
    ordered = sorted(source_rows, key=lambda row: segment_order(str(row["item_id"])))
    orders = [segment_order(str(row["item_id"])) for row in ordered]
    if orders != list(range(orders[0], orders[0] + len(orders))):
        raise ValueError("synthetic sources must be adjacent segments")
    offsets, cursor = {}, 0.0
    for row in ordered:
        offsets[str(row["item_id"])] = cursor
        cursor += float(row["duration_sec"])
    item_id = "synthetic:" + "+".join(str(row["item_id"]) for row in ordered)
    return {
        "schema_version": 1, "dataset_id": "m4singer_synthetic_long", "item_id": item_id,
        "song_id": ordered[0]["song_id"], "singer_id": ordered[0]["singer_id"], "audio_relpath": output_relpath,
        "duration_sec": duration_sec, "split": ordered[0]["split"], "length_source": "synthetic_concat",
        "source_item_ids": [row["item_id"] for row in ordered], "source_order": orders,
        "cumulative_offsets": offsets, "join_points_sec": [offsets[row["item_id"]] for row in ordered[1:]],
        "seam_mask": [[offsets[row["item_id"]], offsets[row["item_id"]]] for row in ordered[1:]],
        "silence_inserted_sec": 0.0, "status": "accepted", "quality_tier": "A_high_confidence",
        "synthetic_version": SYNTHETIC_VERSION,
    }
