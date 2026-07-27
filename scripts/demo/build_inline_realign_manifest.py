#!/usr/bin/env python3
"""Build a bounded Demo/M4Singer/MIR-1K manifest for inline-realign experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
import wave
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "demo"))

from lyricalign.demo.batch import discover_jobs
from prepare_mir1k_demo_subset import materialize as materialize_mir1k_subset


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
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



def safe_component(value: Any, *, fallback: str = "item") -> str:
    text = str(value).strip().replace("\\", "_").replace("/", "_")
    text = "".join(character if character.isalnum() or character in "-_.#" else "_" for character in text)
    text = text.strip("._")
    return text or fallback


def probe_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                return handle.getnframes() / float(handle.getframerate())
        except (wave.Error, OSError):
            pass
    if not shutil.which("ffprobe"):
        raise RuntimeError(f"cannot probe non-WAV audio without ffprobe: {path}")
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True, text=True, capture_output=True,
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise ValueError(f"non-positive audio duration: {path}")
    return duration


def evenly_spread(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not rows:
        return []
    if len(rows) <= count:
        return list(rows)
    ordered = sorted(
        rows,
        key=lambda row: (
            float(row.get("duration_sec", 0.0)),
            int(row.get("character_count", len(str(row.get("lyrics_normalized", ""))))),
            str(row.get("item_id")),
        ),
    )
    positions = sorted({int(round(index * (len(ordered) - 1) / max(count - 1, 1))) for index in range(count)})
    selected = [ordered[position] for position in positions]
    if len(selected) < count:
        selected_ids = {str(row.get("item_id")) for row in selected}
        selected.extend(row for row in ordered if str(row.get("item_id")) not in selected_ids)
    return selected[:count]


def diverse_m4_native_rows(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Prefer distinct songs/singers before taking a second segment from one song."""
    if count <= 0 or not rows:
        return []
    by_song: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_song[str(row.get("song_id", row.get("item_id")))].append(row)
    for values in by_song.values():
        values.sort(key=lambda row: (float(row.get("duration_sec", 0.0)), str(row.get("item_id"))))
    song_order = sorted(
        by_song,
        key=lambda song: (
            len(by_song[song]),
            sum(float(row.get("duration_sec", 0.0)) for row in by_song[song]),
            song,
        ),
    )
    selected: list[dict[str, Any]] = []
    depth = 0
    while len(selected) < count:
        added = False
        for song in song_order:
            values = by_song[song]
            if depth < len(values):
                selected.append(values[depth]); added = True
                if len(selected) >= count:
                    break
        if not added:
            break
        depth += 1
    return evenly_spread(selected, min(count, len(selected)))


def timestamp_gt(label: dict[str, Any], *, offset_sec: float = 0.0, start_index: int = 0) -> list[dict[str, Any]]:
    text = str(label["lyrics_normalized"])
    classes = list(label["timestamp_class_ids"])
    segment = float(label.get("timestamp_segment_sec", 0.08))
    if len(classes) != 2 * len(text):
        raise ValueError(f"{label['item_id']}: timestamp/lyrics mismatch")
    rows = []
    for local_index, character in enumerate(text):
        rows.append({
            "character_index": start_index + local_index,
            "global_character_index": start_index + local_index,
            "character": character,
            "normalized_character": character,
            "start_sec": offset_sec + int(classes[2 * local_index]) * segment,
            "end_sec": offset_sec + int(classes[2 * local_index + 1]) * segment,
            "source_item_id": label["item_id"],
            "gt_source": "qwen_fa_quantized_timestamp_labels",
            "timestamp_segment_sec": segment,
        })
    return rows


def write_native_m4(label: dict[str, Any], audio_root: Path, target: Path) -> dict[str, Any]:
    audio = (audio_root / str(label["audio_relpath"])).resolve()
    if not audio.is_file():
        raise FileNotFoundError(audio)
    target.mkdir(parents=True, exist_ok=True)
    lyrics = str(label["lyrics_normalized"])
    lyrics_path = target / "lyrics.txt"
    gt_path = target / "ground_truth.characters.jsonl"
    lyrics_path.write_text(lyrics + "\n", encoding="utf-8")
    write_jsonl(gt_path, timestamp_gt(label))
    return {
        "dataset": "m4singer",
        "profile": "local_segment",
        "item_id": f"m4native_{safe_component(label['item_id'])}",
        "source_item_id": label["item_id"],
        "song_id": label.get("song_id"),
        "singer_id": label.get("singer_id"),
        "selection_role": "development",
        "lyrics_path": str(lyrics_path.resolve()),
        "audio_path": str(audio),
        "gt_path": str(gt_path.resolve()),
        "duration_sec": probe_duration(audio),
        "synthetic": False,
        "gt_time_resolution_sec": float(label.get("timestamp_segment_sec", 0.08)),
    }


def concat_audio(sources: list[Path], output: Path) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to build M4Singer synthetic-long audio")
    output.parent.mkdir(parents=True, exist_ok=True)
    identity = output.with_suffix(".sources.json")
    request = [{"path": str(path.resolve()), "sha256": sha256(path)} for path in sources]
    if output.is_file() and identity.is_file():
        try:
            if json.loads(identity.read_text(encoding="utf-8")) == request:
                return
        except (OSError, json.JSONDecodeError):
            pass
    list_path = output.with_suffix(".concat.txt")
    list_path.write_text(
        "".join(
            "file '" + str(path.resolve()).replace("'", "'\\''") + "'\n"
            for path in sources
        ),
        encoding="utf-8",
    )
    temporary = output.with_suffix(".tmp.wav")
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "warning",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(temporary),
        ],
        check=True,
    )
    temporary.replace(output)
    identity.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    list_path.unlink(missing_ok=True)


def write_long_m4(
    labels: list[dict[str, Any]], audio_root: Path, target: Path, *, ordinal: int,
    target_duration_sec: float,
) -> dict[str, Any] | None:
    ordered = sorted(labels, key=lambda row: str(row["item_id"]))
    selected: list[tuple[dict[str, Any], Path, float]] = []
    accumulated = 0.0
    for label in ordered:
        audio = (audio_root / str(label["audio_relpath"])).resolve()
        if not audio.is_file():
            continue
        duration = probe_duration(audio)
        selected.append((label, audio, duration))
        accumulated += duration
        if accumulated >= target_duration_sec:
            break
    if accumulated < min(60.0, target_duration_sec * 0.75) or len(selected) < 2:
        return None
    item_id = f"m4long_{ordinal:03d}_{safe_component(selected[0][0].get('song_id', 'song'), fallback='song')}"
    item_root = target / item_id
    item_root.mkdir(parents=True, exist_ok=True)
    lyrics_parts: list[str] = []
    gt_rows: list[dict[str, Any]] = []
    source_items: list[dict[str, Any]] = []
    offset = 0.0
    character_cursor = 0
    seams: list[float] = []
    for sequence_index, (label, audio, duration) in enumerate(selected):
        text = str(label["lyrics_normalized"])
        lyrics_parts.append(text)
        gt_rows.extend(timestamp_gt(label, offset_sec=offset, start_index=character_cursor))
        source_items.append({
            "sequence_index": sequence_index,
            "item_id": label["item_id"],
            "audio_path": str(audio),
            "duration_sec": duration,
            "offset_sec": offset,
            "character_start": character_cursor,
            "character_end": character_cursor + len(text),
        })
        character_cursor += len(text)
        offset += duration
        if sequence_index + 1 < len(selected):
            seams.append(offset)
    lyrics = "".join(lyrics_parts)
    lyrics_path = item_root / "lyrics.txt"
    gt_path = item_root / "ground_truth.characters.jsonl"
    audio_path = item_root / "vocal.wav"
    lyrics_path.write_text("\n".join(lyrics[index:index + 24] for index in range(0, len(lyrics), 24)) + "\n", encoding="utf-8")
    write_jsonl(gt_path, gt_rows)
    concat_audio([audio for _, audio, _ in selected], audio_path)
    atomic_json(item_root / "source_manifest.json", {
        "schema_version": "inline_realign_m4singer_synthetic_long_v1",
        "item_id": item_id,
        "song_id": selected[0][0].get("song_id"),
        "singer_id": selected[0][0].get("singer_id"),
        "source_items": source_items,
        "synthetic_seams_sec": seams,
        "gt_source": "qwen_fa_quantized_timestamp_labels",
    })
    return {
        "dataset": "m4singer_synthetic_long",
        "profile": "long_serial",
        "item_id": item_id,
        "song_id": selected[0][0].get("song_id"),
        "singer_id": selected[0][0].get("singer_id"),
        "selection_role": "development",
        "lyrics_path": str(lyrics_path.resolve()),
        "audio_path": str(audio_path.resolve()),
        "gt_path": str(gt_path.resolve()),
        "duration_sec": probe_duration(audio_path),
        "synthetic": True,
        "synthetic_seams_sec": seams,
        "source_manifest": str((item_root / "source_manifest.json").resolve()),
        "gt_time_resolution_sec": float(selected[0][0].get("timestamp_segment_sec", 0.08)),
    }


def _prepared_suffixes(args: argparse.Namespace) -> list[str]:
    values = [value.strip() for value in str(args.demo_prepared_suffixes).split(",") if value.strip()]
    legacy = str(getattr(args, "demo_prepared_suffix", "") or "").strip()
    if legacy and legacy not in values:
        values.insert(0, legacy)
    return values


def _find_demo_prepared_root(job: Any, suffixes: list[str]) -> Path | None:
    candidates: list[Path] = []
    for suffix in suffixes:
        candidates.append(job.parent / f"{job.stem}{suffix}")
    candidates.extend(sorted(job.parent.glob(f"{job.stem}_qwen_fa*")))
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "work" / "audio" / "vocals.wav").is_file():
            return resolved
    return None


def demo_rows(args: argparse.Namespace, cap: int, audit: dict[str, Any]) -> list[dict[str, Any]]:
    if args.demo_root is None:
        audit["demo"] = {"status": "skipped_no_demo_root", "selected": 0}
        return []
    recursive_used = bool(args.demo_recursive)
    try:
        jobs = discover_jobs(args.demo_root, recursive=recursive_used)
    except FileNotFoundError as first_error:
        if recursive_used:
            audit["demo"] = {"status": "skipped_no_complete_jobs", "error": str(first_error), "selected": 0}
            return []
        try:
            jobs = discover_jobs(args.demo_root, recursive=True)
            recursive_used = True
        except FileNotFoundError as second_error:
            audit["demo"] = {"status": "skipped_no_complete_jobs", "error": str(second_error), "selected": 0}
            return []
    suffixes = _prepared_suffixes(args)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for job in jobs:
        prepared_root = _find_demo_prepared_root(job, suffixes)
        if prepared_root is None:
            skipped.append({
                "stem": job.stem, "reason": "prepared_vocal_missing",
                "searched_suffixes": suffixes, "parent": str(job.parent),
            })
            continue
        prepared = prepared_root / "work" / "audio"
        vocal = prepared / "vocals.wav"; mix = prepared / "mix.wav"
        rows.append({
            "dataset": "demo", "profile": "long_serial",
            "item_id": f"demo_{safe_component(job.stem)}",
            "selection_role": "development",
            "lyrics_path": str(job.lyrics.resolve()),
            "audio_path": str(vocal.resolve()), "gt_path": None,
            "mix_audio_path": str(mix.resolve()) if mix.is_file() else str(job.mix_source.resolve()),
            "visual_path": str(job.video.resolve()) if job.video else None,
            "source_media_path": str(job.source_media.resolve()),
            "prepared_root": str(prepared_root), "synthetic": False,
        })
    selected = rows if cap <= 0 else rows[:cap]
    audit["demo"] = {
        "status": "complete", "recursive_used": recursive_used,
        "discovered": len(jobs), "prepared": len(rows), "selected": len(selected),
        "prepared_suffixes": suffixes, "skipped": skipped,
    }
    return selected


def _mir1k_missing_assets(root: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    audio_names = {
        "official_vocal": "official_vocal.wav",
        "demucs": f"demucs_{args.mir1k_demucs_model}_vocals.wav",
        "mix": "mix.wav",
    }
    missing: list[dict[str, Any]] = []
    for row in rows:
        item_id = str(row["item_id"])
        item_root = root / "items" / item_id
        required = {
            "lyrics": item_root / "lyrics.txt",
            "ground_truth": item_root / "ground_truth.characters.jsonl",
            "audio": item_root / "audio" / audio_names[args.mir1k_audio_variant],
            "mix_audio": item_root / "audio" / "mix.wav",
        }
        absent = {name: str(path) for name, path in required.items() if not path.is_file()}
        if absent:
            missing.append({"item_id": item_id, "selection_role": row.get("selection_role"), "missing": absent})
    return missing


def _repair_missing_mir1k_assets(
    root: Path, selected: list[dict[str, Any]], args: argparse.Namespace, audit: dict[str, Any]
) -> None:
    missing_before = _mir1k_missing_assets(root, selected, args)
    repair_audit: dict[str, Any] = {
        "enabled": bool(args.materialize_missing_mir1k),
        "missing_item_count_before": len(missing_before),
        "missing_before": missing_before,
        "materialized_item_ids": [],
    }
    audit["mir1k_asset_repair"] = repair_audit
    if not missing_before:
        repair_audit["status"] = "not_needed"
        return
    if not args.materialize_missing_mir1k:
        repair_audit["status"] = "disabled"
        raise FileNotFoundError(
            "MIR-1K subset contains metadata-only rows with missing materialized assets; "
            "rerun without --no-materialize-missing-mir1k or prepare those roles explicitly. "
            f"First missing item: {missing_before[0]}"
        )

    summary_path = root / "selection.json"
    if not summary_path.is_file():
        repair_audit["status"] = "missing_selection_summary"
        raise FileNotFoundError(
            f"cannot auto-materialize MIR-1K assets because subset summary is missing: {summary_path}"
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    source_characters = Path(str(summary.get("source_characters", ""))).expanduser()
    mir1k_root = Path(str(summary.get("mir1k_root", ""))).expanduser()
    units_per_line = int(summary.get("units_per_line", 12))
    for label, path in (("source_characters", source_characters), ("mir1k_root", mir1k_root)):
        if not path.exists():
            repair_audit["status"] = f"missing_{label}"
            raise FileNotFoundError(
                f"cannot auto-materialize MIR-1K assets; {label} recorded in {summary_path} does not exist: {path}"
            )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for character in read_jsonl(source_characters):
        grouped[str(character["item_id"])].append(character)
    missing_ids = {str(row["item_id"]) for row in missing_before}
    repair_rows = [row for row in selected if str(row["item_id"]) in missing_ids]
    missing_gt = [str(row["item_id"]) for row in repair_rows if str(row["item_id"]) not in grouped]
    if missing_gt:
        repair_audit["status"] = "source_gt_incomplete"
        raise ValueError(f"source MIR-1K character GT missing for: {missing_gt}")

    materialize_mir1k_subset(
        repair_rows,
        grouped,
        mir1k_root=mir1k_root.resolve(),
        out_dir=root,
        units_per_line=units_per_line,
        force=False,
        materialize_roles={str(row.get("selection_role", "")) for row in repair_rows},
    )
    missing_after = _mir1k_missing_assets(root, selected, args)
    repair_audit.update({
        "status": "complete" if not missing_after else "incomplete",
        "materialized_item_ids": [str(row["item_id"]) for row in repair_rows],
        "missing_item_count_after": len(missing_after),
        "missing_after": missing_after,
        "source_characters": str(source_characters.resolve()),
        "mir1k_root": str(mir1k_root.resolve()),
        "units_per_line": units_per_line,
    })
    if missing_after:
        raise FileNotFoundError(f"MIR-1K auto-materialization incomplete; first missing item: {missing_after[0]}")


def mir_rows(args: argparse.Namespace, cap: int, audit: dict[str, Any]) -> list[dict[str, Any]]:
    if args.mir1k_subset_root is None:
        audit["mir1k"] = {"status": "skipped_no_subset_root", "selected": 0}
        return []
    root = args.mir1k_subset_root.resolve()
    selection_path = root / "selection.jsonl"
    if not selection_path.is_file():
        raise FileNotFoundError(selection_path)
    rows = read_jsonl(selection_path)
    roles = {value.strip() for value in str(args.mir1k_roles).split(",") if value.strip()}
    if not roles:
        roles = {"development"}
    if args.include_heldout:
        roles.add("heldout")
    candidates = [row for row in rows if str(row.get("selection_role")) in roles]
    candidates.sort(key=lambda row: (str(row.get("selection_role")), row.get("selection_order") or 0, str(row["item_id"])))
    selected = candidates[:cap]
    _repair_missing_mir1k_assets(root, selected, args, audit)
    result: list[dict[str, Any]] = []
    for row in selected:
        item_id = str(row["item_id"])
        item_root = root / "items" / item_id
        audio_names = {
            "official_vocal": "official_vocal.wav",
            "demucs": f"demucs_{args.mir1k_demucs_model}_vocals.wav",
            "mix": "mix.wav",
        }
        audio = item_root / "audio" / audio_names[args.mir1k_audio_variant]
        result.append({
            "dataset": "mir1k",
            "profile": "long_serial",
            "item_id": f"mir1k_{safe_component(item_id)}",
            "source_item_id": item_id,
            "song_id": row.get("song_id"),
            "singer_id": row.get("singer_id"),
            "selection_role": row.get("selection_role"),
            "selection_order": row.get("selection_order"),
            "lyrics_path": str((item_root / "lyrics.txt").resolve()),
            "audio_path": str(audio.resolve()),
            "gt_path": str((item_root / "ground_truth.characters.jsonl").resolve()),
            "mix_audio_path": str((item_root / "audio" / "mix.wav").resolve()),
            "synthetic": False,
        })
    audit["mir1k"] = {
        "status": "complete", "available": len(candidates), "selected": len(result),
        "roles": sorted(roles), "audio_variant": args.mir1k_audio_variant,
    }
    return result


def m4_rows(args: argparse.Namespace, native_cap: int, long_cap: int, audit: dict[str, Any]) -> list[dict[str, Any]]:
    if args.m4_labels is None or args.m4_audio_root is None:
        audit["m4singer"] = {"status": "skipped_missing_paths", "selected": 0}
        return []
    labels = read_jsonl(args.m4_labels.resolve())
    split_order = [value.strip() for value in args.m4_splits.split(",") if value.strip()]
    filtered = [row for row in labels if str(row.get("split")) in split_order]
    if not filtered:
        raise ValueError(f"no M4Singer labels in splits {split_order}")
    native_selected = diverse_m4_native_rows(filtered, native_cap)
    materialized = args.out_root / "materialized" / "m4singer"
    result = [
        write_native_m4(row, args.m4_audio_root.resolve(), materialized / "native" / safe_component(row["item_id"]))
        for row in native_selected
    ]
    by_song: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in filtered:
        by_song[str(row.get("song_id"))].append(row)
    long_candidates = [
        values for _, values in sorted(by_song.items())
        if sum(float(row.get("duration_sec", 0.0)) for row in values) >= 60.0
    ]
    long_groups = evenly_spread(
        [
            {
                "item_id": str(values[0].get("song_id")),
                "duration_sec": sum(float(row.get("duration_sec", 0.0)) for row in values),
                "character_count": sum(int(row.get("character_count", 0)) for row in values),
                "values": values,
            }
            for values in long_candidates
        ],
        long_cap,
    )
    long_rows: list[dict[str, Any]] = []
    for ordinal, group in enumerate(long_groups):
        row = write_long_m4(
            list(group["values"]), args.m4_audio_root.resolve(), materialized / "long",
            ordinal=ordinal, target_duration_sec=args.m4_long_target_sec,
        )
        if row is not None:
            long_rows.append(row)
    result.extend(long_rows)
    audit["m4singer"] = {
        "status": "complete",
        "label_count": len(labels),
        "eligible_count": len(filtered),
        "splits": split_order,
        "native_selected": len(native_selected),
        "synthetic_long_selected": len(long_rows),
        "synthetic_long_target_sec": args.m4_long_target_sec,
    }
    return result



def assign_variant_sets(rows: list[dict[str, Any]], *, mode: str) -> None:
    """Bound the expensive B0-B3 matrix while keeping broad B2 coverage."""
    if mode == "smoke":
        for row in rows:
            row["variant_set"] = "official_primary" if row.get("profile") == "local_segment" else "baseline_matrix"
        return
    matrix_caps = {"demo": 4, "mir1k": 8, "m4singer_synthetic_long": 4}
    used = {key: 0 for key in matrix_caps}
    for row in rows:
        dataset = str(row.get("dataset"))
        if row.get("profile") == "local_segment":
            row["variant_set"] = "official_primary"
        elif dataset in matrix_caps and used[dataset] < matrix_caps[dataset]:
            row["variant_set"] = "baseline_matrix"
            used[dataset] += 1
        else:
            row["variant_set"] = "official_primary"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("smoke", "formal"), required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--demo-root", type=Path)
    p.add_argument("--demo-recursive", action="store_true")
    p.add_argument("--require-demo", action="store_true")
    p.add_argument("--demo-prepared-suffix", default="", help=argparse.SUPPRESS)
    p.add_argument(
        "--demo-prepared-suffixes",
        default="_qwen_fa_decoder_realign,_qwen_fa_raw_guarded,_qwen_fa",
    )
    p.add_argument("--mir1k-subset-root", type=Path)
    p.add_argument("--mir1k-audio-variant", choices=("official_vocal", "demucs", "mix"), default="official_vocal")
    p.add_argument("--mir1k-demucs-model", default="htdemucs_ft")
    p.add_argument("--include-heldout", action="store_true")
    p.add_argument("--mir1k-roles")
    p.add_argument(
        "--materialize-missing-mir1k",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "auto-materialize metadata-only MIR-1K rows (notably spare/quick-v2-extra) "
            "from selection.json source paths before building the experiment manifest"
        ),
    )
    p.add_argument("--m4-labels", type=Path)
    p.add_argument("--m4-audio-root", type=Path)
    p.add_argument("--m4-splits", default="validation")
    p.add_argument("--m4-long-target-sec", type=float, default=90.0)
    p.add_argument("--demo-cap", type=int)
    p.add_argument("--mir1k-cap", type=int)
    p.add_argument("--m4-native-cap", type=int)
    p.add_argument("--m4-long-cap", type=int)
    return p


def main() -> int:
    args = parser().parse_args()
    args.out_root = args.out_root.expanduser().resolve()
    args.out_root.mkdir(parents=True, exist_ok=True)
    defaults = {
        "smoke": {"demo": 2, "mir1k": 3, "m4_native": 4, "m4_long": 2},
        "formal": {"demo": 12, "mir1k": 20 if args.include_heldout else 16, "m4_native": 24, "m4_long": 12},
    }[args.mode]
    if args.mir1k_roles is None:
        args.mir1k_roles = (
            "development" if args.mode == "smoke"
            else "development,quick_v2_extra,spare"
        )
    demo_cap = args.demo_cap if args.demo_cap is not None else defaults["demo"]
    mir_cap = args.mir1k_cap if args.mir1k_cap is not None else defaults["mir1k"]
    m4_native_cap = args.m4_native_cap if args.m4_native_cap is not None else defaults["m4_native"]
    m4_long_cap = args.m4_long_cap if args.m4_long_cap is not None else defaults["m4_long"]
    audit: dict[str, Any] = {
        "schema_version": "inline_realign_manifest_audit_v1",
        "mode": args.mode,
        "caps": {
            "demo": demo_cap, "mir1k": mir_cap,
            "m4_native": m4_native_cap, "m4_synthetic_long": m4_long_cap,
        },
        "mir1k_roles": [value.strip() for value in args.mir1k_roles.split(",") if value.strip()],
        "heldout_policy": (
            "included only by explicit --include-heldout" if args.include_heldout
            else "heldout excluded; all non-heldout design roles may be consumed"
        ),
    }
    rows: list[dict[str, Any]] = []
    demo_selected = demo_rows(args, demo_cap, audit)
    if args.require_demo and not demo_selected:
        raise ValueError(
            "Demo was required but no prepared Demo item was found; check --demo-root, "
            "--demo-recursive and --demo-prepared-suffixes"
        )
    rows.extend(demo_selected)
    rows.extend(mir_rows(args, mir_cap, audit))
    rows.extend(m4_rows(args, m4_native_cap, m4_long_cap, audit))
    if not rows:
        raise ValueError("manifest contains no items; check Demo/M4Singer/MIR-1K paths")
    assign_variant_sets(rows, mode=args.mode)
    # Always exercise fail-closed incomplete output on one real Demo and one GT item.
    marked = 0
    for preferred_dataset in ("demo", "mir1k", "m4singer_synthetic_long"):
        candidate = next((row for row in rows if row.get("dataset") == preferred_dataset), None)
        if candidate is not None and not candidate.get("incomplete_exercise"):
            candidate["incomplete_exercise"] = True
            marked += 1
        if marked >= 2:
            break
    for ordinal, row in enumerate(rows):
        row["manifest_order"] = ordinal
        for field in ("lyrics_path", "audio_path"):
            if not Path(row[field]).is_file():
                raise FileNotFoundError(Path(row[field]))
        if row.get("gt_path") and not Path(row["gt_path"]).is_file():
            raise FileNotFoundError(Path(row["gt_path"]))
    output = (args.output or args.out_root / "experiment_manifest.jsonl").expanduser().resolve()
    write_jsonl(output, rows)
    audit["manifest"] = str(output)
    audit["item_count"] = len(rows)
    audit["variant_set_counts"] = {
        variant_set: sum(str(row.get("variant_set")) == variant_set for row in rows)
        for variant_set in sorted({str(row.get("variant_set")) for row in rows})
    }
    audit["dataset_counts"] = {
        dataset: sum(str(row["dataset"]) == dataset for row in rows)
        for dataset in sorted({str(row["dataset"]) for row in rows})
    }
    atomic_json(args.out_root / "input_audit.json", audit)
    print(json.dumps({
        "status": "complete", "manifest": str(output), "item_count": len(rows),
        "dataset_counts": audit["dataset_counts"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
