#!/usr/bin/env python3
"""Select and materialize a reproducible MIR-1K demo-diagnostic subset.

Selection uses only dataset/GT complexity descriptors, never model predictions.
The 17 manually character-aligned MIR-1K OOD songs remain test-only.  The
result separates an exploration subset from a held-out confirmation subset so
separator/context choices cannot be selected and reported on the same songs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_tie(seed: int, item_id: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{item_id}".encode()).digest()[:8], "big")


def _features(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: int(row["character_index"]))
    starts = [float(row["start_sec"]) for row in ordered]
    ends = [float(row["end_sec"]) for row in ordered]
    durations = [max(0.0, end - start) for start, end in zip(starts, ends, strict=True)]
    gaps = [max(0.0, starts[index] - ends[index - 1]) for index in range(1, len(ordered))]
    span = max(ends[-1] - starts[0], 1e-9)
    return {
        "item_id": str(manifest["item_id"]),
        "song_id": str(manifest["song_id"]),
        "singer_id": str(manifest.get("singer_id") or str(manifest["song_id"]).split("_", 1)[0]),
        "duration_sec": float(manifest["duration_sec"]),
        "annotated_start_sec": starts[0],
        "annotated_end_sec": ends[-1],
        "annotated_span_sec": span,
        "character_count": len(ordered),
        "character_rate_per_sec": len(ordered) / span,
        "mean_character_duration_sec": sum(durations) / len(durations),
        "p90_character_duration_sec": sorted(durations)[max(0, math.ceil(0.9 * len(durations)) - 1)],
        "gap_ratio": sum(gaps) / span,
        "max_gap_sec": max(gaps, default=0.0),
        "mean_gap_sec": sum(gaps) / len(gaps) if gaps else 0.0,
        "coverage_ratio": sum(durations) / span,
        "lyrics": str(manifest["lyrics_normalized"]),
        "audio_relpath": str(manifest["audio_relpath"]),
    }


def _normalized(items: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, tuple[float, ...]]:
    bounds: dict[str, tuple[float, float]] = {}
    for key in keys:
        values = [float(item[key]) for item in items]
        bounds[key] = (min(values), max(values))
    result = {}
    for item in items:
        coordinates = []
        for key in keys:
            low, high = bounds[key]
            coordinates.append(0.0 if math.isclose(low, high) else (float(item[key]) - low) / (high - low))
        result[str(item["item_id"])] = tuple(coordinates)
    return result


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def select_subset(
    items: list[dict[str, Any]], *, development_count: int, heldout_count: int, seed: int
) -> list[dict[str, Any]]:
    if development_count + heldout_count > len(items):
        raise ValueError("requested subset exceeds available MIR-1K aligned songs")
    keys = (
        "duration_sec",
        "character_rate_per_sec",
        "gap_ratio",
        "mean_character_duration_sec",
        "coverage_ratio",
    )
    coordinates = _normalized(items, keys)
    by_id = {str(item["item_id"]): item for item in items}
    reasons: dict[str, list[str]] = defaultdict(list)

    extreme_specs = [
        ("longest", "duration_sec", max),
        ("shortest", "duration_sec", min),
        ("highest_character_rate", "character_rate_per_sec", max),
        ("lowest_character_rate", "character_rate_per_sec", min),
        ("highest_gap_ratio", "gap_ratio", max),
        ("lowest_gap_ratio", "gap_ratio", min),
    ]
    development: list[str] = []
    for label, key, function in extreme_specs:
        target = function(float(item[key]) for item in items)
        candidates = [item for item in items if math.isclose(float(item[key]), target)]
        chosen = min(candidates, key=lambda item: _stable_tie(seed, str(item["item_id"])))
        item_id = str(chosen["item_id"])
        reasons[item_id].append(label)
        if item_id not in development and len(development) < development_count:
            development.append(item_id)

    def fill(selected: list[str], target_count: int, excluded: set[str]) -> None:
        while len(selected) < target_count:
            candidates = [item for item in items if str(item["item_id"]) not in excluded and str(item["item_id"]) not in selected]
            if not candidates:
                raise RuntimeError("selection exhausted unexpectedly")
            existing = selected or list(excluded)
            existing_singers = {str(by_id[item_id]["singer_id"]) for item_id in existing if item_id in by_id}

            def score(item: dict[str, Any]) -> tuple[float, int]:
                item_id = str(item["item_id"])
                if existing:
                    minimum = min(_distance(coordinates[item_id], coordinates[other]) for other in existing if other in coordinates)
                else:
                    minimum = 1.0
                singer_bonus = 0.20 if str(item["singer_id"]) not in existing_singers else 0.0
                return (minimum + singer_bonus, -_stable_tie(seed, item_id))

            chosen = max(candidates, key=score)
            item_id = str(chosen["item_id"])
            selected.append(item_id)
            reasons[item_id].append("farthest_point_feature_diversity")

    fill(development, development_count, set())
    heldout: list[str] = []
    fill(heldout, heldout_count, set(development))

    rows = []
    for item in sorted(items, key=lambda row: str(row["item_id"])):
        item_id = str(item["item_id"])
        if item_id in development:
            role = "development"
            order = development.index(item_id)
        elif item_id in heldout:
            role = "heldout"
            order = heldout.index(item_id)
        else:
            role = "spare"
            order = None
        rows.append({**item, "selection_role": role, "selection_order": order, "selection_reasons": reasons.get(item_id, [])})
    return rows


def _run_ffmpeg(source: Path, output: Path, audio_filter: str, *, force: bool) -> None:
    if output.is_file() and not force:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.wav")
    command = [
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source),
        "-vn", "-af", audio_filter, "-ar", "44100", "-ac", "1",
        "-c:a", "pcm_s16le", str(temporary),
    ]
    subprocess.run(command, check=True)
    temporary.replace(output)


def _chunk_lyrics(text: str, units_per_line: int) -> str:
    return "\n".join(text[index:index + units_per_line] for index in range(0, len(text), units_per_line)) + "\n"


def materialize(
    selection: list[dict[str, Any]],
    characters_by_item: dict[str, list[dict[str, Any]]],
    *, mir1k_root: Path, out_dir: Path, units_per_line: int, force: bool,
) -> None:
    for row in selection:
        if row["selection_role"] == "spare":
            continue
        item_id = str(row["item_id"])
        song_id = str(row["song_id"])
        source = mir1k_root / "UndividedWavfile" / song_id
        if not source.is_file():
            raise FileNotFoundError(source)
        item_root = out_dir / "items" / item_id
        audio_root = item_root / "audio"
        item_root.mkdir(parents=True, exist_ok=True)
        lyrics = str(row["lyrics"])
        (item_root / "lyrics.continuous.txt").write_text(lyrics + "\n", encoding="utf-8")
        (item_root / "lyrics.txt").write_text(_chunk_lyrics(lyrics, units_per_line), encoding="utf-8")
        write_jsonl(item_root / "ground_truth.characters.jsonl", characters_by_item[item_id])

        # MIR-1K UndividedWavfile convention retained by the project: channel 0
        # accompaniment, channel 1 vocal.  The diagnostic mix is a mono sum so
        # separators receive an actual mixture rather than isolated stereo sides.
        _run_ffmpeg(source, audio_root / "mix.wav", "pan=mono|c0=0.5*c0+0.5*c1", force=force)
        _run_ffmpeg(source, audio_root / "official_vocal.wav", "pan=mono|c0=0.5*c1", force=force)
        _run_ffmpeg(source, audio_root / "accompaniment.wav", "pan=mono|c0=0.5*c0", force=force)
        atomic_json(
            item_root / "item.json",
            {
                **row,
                "source_undivided_wav": str(source.resolve()),
                "source_sha256": sha256(source),
                "lyrics_units_per_line": units_per_line,
                "audio_mix_contract": {
                    "mix_formula": "0.5*channel0_accompaniment + 0.5*channel1_vocal",
                    "official_vocal_formula": "0.5*channel1_vocal",
                    "accompaniment_formula": "0.5*channel0_accompaniment",
                    "reason": "preserve exact additive reconstruction and comparable stem scale",
                },
                "audio_variants": {
                    "mix": {"path": str((audio_root / "mix.wav").resolve()), "sha256": sha256(audio_root / "mix.wav")},
                    "official_vocal": {"path": str((audio_root / "official_vocal.wav").resolve()), "sha256": sha256(audio_root / "official_vocal.wav")},
                    "accompaniment": {"path": str((audio_root / "accompaniment.wav").resolve()), "sha256": sha256(audio_root / "accompaniment.wav")},
                },
                "channel_contract": {
                    "accompaniment_channel_index": 0,
                    "vocal_channel_index": 1,
                    "confirmation": "project_retained_manual_review_20260722",
                },
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--mir1k-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--development-count", type=int, default=8)
    parser.add_argument("--heldout-count", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--units-per-line", type=int, default=12)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required")
    manifests = read_jsonl(args.manifest)
    characters = read_jsonl(args.characters)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in characters:
        grouped[str(row["item_id"])].append(row)
    items = []
    for manifest in manifests:
        item_id = str(manifest["item_id"])
        if item_id not in grouped:
            raise ValueError(f"missing character GT for {item_id}")
        items.append(_features(manifest, grouped[item_id]))
    selection = select_subset(
        items,
        development_count=args.development_count,
        heldout_count=args.heldout_count,
        seed=args.seed,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    materialize(
        selection,
        grouped,
        mir1k_root=args.mir1k_root,
        out_dir=args.out_dir,
        units_per_line=args.units_per_line,
        force=args.force,
    )
    write_jsonl(args.out_dir / "selection.jsonl", selection)
    summary = {
        "schema_version": "mir1k_demo_subset_v1",
        "selection_policy": "extremes_plus_farthest_point_without_model_results",
        "seed": args.seed,
        "source_manifest": str(args.manifest.resolve()),
        "source_manifest_sha256": sha256(args.manifest),
        "source_characters": str(args.characters.resolve()),
        "source_characters_sha256": sha256(args.characters),
        "mir1k_root": str(args.mir1k_root.resolve()),
        "available_song_count": len(selection),
        "development_count": sum(row["selection_role"] == "development" for row in selection),
        "heldout_count": sum(row["selection_role"] == "heldout" for row in selection),
        "spare_count": sum(row["selection_role"] == "spare" for row in selection),
        "units_per_line": args.units_per_line,
        "roles": {
            role: [row["item_id"] for row in sorted(selection, key=lambda value: (value["selection_role"], value["selection_order"] if value["selection_order"] is not None else 999)) if row["selection_role"] == role]
            for role in ("development", "heldout", "spare")
        },
        "test_only": True,
        "must_not_train_or_validate": True,
    }
    atomic_json(args.out_dir / "selection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
