#!/usr/bin/env python3
"""Build a grouped, song-level Evaluation V1 split manifest (draft).

The manifest is *not* a training split; it implements the 2026-08-16 session's
no-training exposure tiers:

    diagnostic_visible : regression_selection : sealed_final = 20 : 50 : 30

Large files stay under /home/hyan/Data/...; this script writes only small JSONL
summaries and cleanup reports to the requested out-root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import tempfile
import wave
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASETS_ROOT = Path("/home/hyan/Data/datasets")
DEFAULT_OUT_ROOT = Path("/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft")

TIERS = ("diagnostic_visible", "regression_selection", "sealed_final")
TIER_COUNTS = {
    "mir_mlpop_cmn": (4, 10, 6),
    "mir_mlpop_yue": (1, 1, 1),
    "jamendolyrics_en": (4, 10, 6),
    "pjs": (20, 50, 30),
    "gtsinger_chinese": (1, 2, 2),
}

AUDIO_CHECK_ENABLED = True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def atomic_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def wave_duration_sec(path: Path) -> float | None:
    if not AUDIO_CHECK_ENABLED:
        return None
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return frames / float(rate) if rate else None
    except Exception:
        return None


def allocate_simple(items: list[dict[str, Any]], counts: tuple[int, int, int], seed: str, key: str = "group_id") -> None:
    """Deterministically assign tier counts to whole groups.

    The input list is expected to contain one representative per group.  It is
    shuffled with a fixed seed, then cut into diagnostic/regression/sealed.
    """
    total = sum(counts)
    if len(items) != total:
        raise ValueError(f"expected {total} groups, got {len(items)}")
    rng = random.Random(f"{seed}:{key}:simple")
    ordered = list(items)
    rng.shuffle(ordered)
    for idx, row in enumerate(ordered):
        if idx < counts[0]:
            row["tier"] = TIERS[0]
        elif idx < counts[0] + counts[1]:
            row["tier"] = TIERS[1]
        else:
            row["tier"] = TIERS[2]


def stratified_allocate(items: list[dict[str, Any]], counts: tuple[int, int, int], seed: str, strata_keys: Sequence[str], key: str = "group_id") -> None:
    """Stratified deterministic allocation for small song pools.

    Items are partitioned by the boolean strata tuple; each stratum is shuffled
    internally, then strata are interleaved round-robin so hard-case tags are
    spread across all tiers.
    """
    total = sum(counts)
    if len(items) != total:
        raise ValueError(f"expected {total} groups, got {len(items)}")
    rng = random.Random(f"{seed}:{key}:stratified")
    groups: dict[tuple[bool, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in items:
        groups[tuple(bool(row.get(k)) for k in strata_keys)].append(row)
    for group_rows in groups.values():
        rng.shuffle(group_rows)
    # Interleave strata in a stable key order.
    ordered: list[dict[str, Any]] = []
    pool = {k: list(v) for k, v in groups.items()}
    while pool:
        for k in sorted(pool.keys()):
            if pool[k]:
                ordered.append(pool[k].pop(0))
        pool = {k: v for k, v in pool.items() if v}
    for idx, row in enumerate(ordered):
        if idx < counts[0]:
            row["tier"] = TIERS[0]
        elif idx < counts[0] + counts[1]:
            row["tier"] = TIERS[1]
        else:
            row["tier"] = TIERS[2]


def collect_mir_mlpop(datasets_root: Path, seed: str) -> list[dict[str, Any]]:
    root = datasets_root / "mir_mlpop"
    rows: list[dict[str, Any]] = []
    official = {
        "cmn": read_json(root / "raw/extracted/official_repository/dataset/cmn_dataset_240223.json"),
        "yue": read_json(root / "raw/extracted/official_repository/dataset/yue_dataset_240223.json"),
    }
    for lang in ("cmn", "yue"):
        available = sorted(
            int(p.stem) for p in (root / "raw/extracted/audio" / lang).glob("*.wav")
        )
        by_id = {str(r["song_id"]): r for r in official[lang]}
        reps: list[dict[str, Any]] = []
        for song_id in available:
            rec = by_id.get(str(song_id))
            if rec is None:
                continue
            audio_rel = Path("raw/extracted/audio") / lang / f"{song_id}.wav"
            audio_abs = root / audio_rel
            reps.append({
                "dataset_id": f"mir_mlpop_{lang}",
                "item_id": f"mir_mlpop_{lang}_{song_id}",
                "group_id": f"mir_mlpop_{lang}_song_{song_id}",
                "song_id": str(song_id),
                "language": "cmn" if lang == "cmn" else "yue",
                "source_split": rec.get("data_split", ""),
                "audio_relpath": str(audio_rel),
                "audio_exists": audio_abs.is_file(),
                "duration_sec": wave_duration_sec(audio_abs),
                "annotation_granularity": "character/syllable",
                "metadata": {
                    "youtube_link": rec.get("youtube_link", ""),
                    "aligned_lyrics_count": len(rec.get("aligned_lyrics", [])),
                    "filler_count": len(rec.get("filler", [])),
                },
            })
        # Add one representative per song for allocation.
        reps_for_alloc = list(reps)
        if lang == "cmn":
            # Official test (21-30) is sealed by policy; official train gets 4/10.
            train_reps = [r for r in reps_for_alloc if r["source_split"] == "Train"]
            test_reps = [r for r in reps_for_alloc if r["source_split"] == "Test"]
            allocate_simple(train_reps, (4, 10, 0), seed, key="mir_mlpop_cmn_train")
            for r in test_reps:
                r["tier"] = "sealed_final"
        else:
            # yue is a tiny probe; 1/1/1 regardless of official split.
            allocate_simple(reps_for_alloc, (1, 1, 1), seed, key="mir_mlpop_yue")
        rows.extend(reps)
    return rows


def collect_jamendolyrics(datasets_root: Path, seed: str) -> list[dict[str, Any]]:
    root = datasets_root / "jamendolyrics_en"
    meta_path = root / "raw/extracted/huggingface_snapshot/subsets/en/metadata.jsonl"
    records = read_jsonl(meta_path)
    rows: list[dict[str, Any]] = []
    for rec in records:
        name = rec["name"]
        audio_rel = Path("raw/extracted/huggingface_snapshot/subsets/en") / rec["file_name"]
        audio_abs = root / audio_rel
        words = rec.get("words", [])
        lines = rec.get("lines", [])
        duration = max((w.get("end", 0.0) for w in words), default=0.0)
        rows.append({
            "dataset_id": "jamendolyrics_en",
            "item_id": f"jamendolyrics_en_{name}",
            "group_id": f"jamendolyrics_en_song_{name}",
            "song_id": name,
            "artist": rec.get("artist", ""),
            "title": rec.get("title", ""),
            "language": rec.get("language", "en"),
            "source_split": "test",
            "audio_relpath": str(audio_rel),
            "audio_exists": audio_abs.is_file(),
            "duration_sec": duration,
            "annotation_granularity": "word+line",
            "metadata": {
                "url": rec.get("url", ""),
                "genre": rec.get("genre", ""),
                "license_type": rec.get("license_type", ""),
                "lyric_overlap": bool(rec.get("lyric_overlap", False)),
                "polyphonic": bool(rec.get("polyphonic", False)),
                "non_lexical": bool(rec.get("non_lexical", False)),
                "word_count": len(words),
                "line_count": len(lines),
            },
        })
    # One representative per song.
    reps = list(rows)
    stratified_allocate(
        reps,
        TIER_COUNTS["jamendolyrics_en"],
        seed,
        strata_keys=("non_lexical", "polyphonic", "lyric_overlap"),
        key="jamendolyrics_en",
    )
    return rows


def collect_pjs(datasets_root: Path, seed: str) -> list[dict[str, Any]]:
    root = datasets_root / "pjs"
    corpus = root / "raw/extracted/PJS_corpus_ver1.1"
    manual_lab = root / "raw/extracted/manual_labels_repository/lab"
    ids = sorted(
        p.name for p in corpus.iterdir()
        if p.is_dir() and p.name.startswith("pjs") and p.name[3:].isdigit()
    )
    reps: list[dict[str, Any]] = []
    for pid in ids:
        song_wav = corpus / pid / f"{pid}_song.wav"
        speech_wav = corpus / pid / f"{pid}_speech.wav"
        reps.append({
            "dataset_id": "pjs",
            "item_id": f"pjs_{pid}",
            "group_id": f"pjs_song_{pid}",
            "song_id": pid,
            "language": "ja",
            "source_split": "official_complete",
            "audio_relpath": str(song_wav.relative_to(root)),
            "audio_exists": song_wav.is_file(),
            "duration_sec": wave_duration_sec(song_wav),
            "annotation_granularity": "phoneme/lab",
            "metadata": {
                "has_speech": speech_wav.is_file(),
                "speech_relpath": str(speech_wav.relative_to(root)) if speech_wav.exists() else None,
                "has_manual_lab": (manual_lab / f"{pid}.lab").is_file(),
                "manual_lab_relpath": str((manual_lab / f"{pid}.lab").relative_to(root)) if (manual_lab / f"{pid}.lab").exists() else None,
                "has_midi": (corpus / pid / f"{pid}.mid").is_file(),
                "has_musicxml": (corpus / pid / f"{pid}.musicxml").is_file(),
            },
        })
    allocate_simple(reps, TIER_COUNTS["pjs"], seed, key="pjs")
    rows: list[dict[str, Any]] = []
    for rep in reps:
        pid = rep["song_id"]
        # Expand to audio/label rows while preserving the group tier.
        song_wav = corpus / pid / f"{pid}_song.wav"
        speech_wav = corpus / pid / f"{pid}_speech.wav"
        rows.append({**rep, "item_id": f"pjs_{pid}_song", "kind": "song_audio", "audio_relpath": str(song_wav.relative_to(root))})
        rows.append({**rep, "item_id": f"pjs_{pid}_speech", "kind": "speech_audio", "audio_relpath": str(speech_wav.relative_to(root)), "duration_sec": wave_duration_sec(speech_wav)})
        lab_rel = manual_lab / f"{pid}.lab"
        rows.append({**rep, "item_id": f"pjs_{pid}_manual_lab", "kind": "manual_lab", "audio_relpath": None, "duration_sec": None, "metadata": rep["metadata"]})
    return rows


def collect_gtsinger(datasets_root: Path, seed: str) -> list[dict[str, Any]]:
    root = datasets_root / "gtsinger_chinese"
    selected = root / "raw/extracted/selected_data/Chinese"
    roots = sorted(
        str(p.relative_to(selected))
        for p in selected.rglob("*.json")
    )
    # Derive song-root from the first three path components: singer/technique/song.
    root_to_paths: dict[str, list[Path]] = defaultdict(list)
    for p in selected.rglob("*.json"):
        rel = p.relative_to(selected)
        parts = rel.parts
        if len(parts) >= 3:
            root_to_paths["/".join(parts[:3])].append(p)
    root_ids = sorted(root_to_paths.keys())
    reps = [{"group_id": f"gtsinger_song_{rid.replace('/', '_')}", "song_root": rid} for rid in root_ids]
    allocate_simple(reps, TIER_COUNTS["gtsinger_chinese"], seed, key="gtsinger_chinese")
    tier_by_root = {r["song_root"]: r["tier"] for r in reps}
    rows: list[dict[str, Any]] = []
    for rid in root_ids:
        tier = tier_by_root[rid]
        for json_path in sorted(root_to_paths[rid]):
            stem = json_path.with_suffix("")
            wav_path = stem.with_suffix(".wav")
            textgrid_path = stem.with_suffix(".TextGrid")
            musicxml_path = stem.with_suffix(".musicxml")
            rel_base = json_path.relative_to(root)
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                duration = max((float(row.get("end_time", 0.0)) for row in data), default=0.0)
                word_count = len(data)
                techs = sorted({str(row.get("tech", "")) for row in data if row.get("tech")})
            except Exception:
                duration = None
                word_count = None
                techs = []
            rel_item = str(json_path.relative_to(selected).with_suffix("")).replace("/", "__")
            selected_prefix = Path("raw/extracted/selected_data/Chinese")
            rows.append({
                "dataset_id": "gtsinger_chinese",
                "item_id": f"gtsinger_{rel_item}",
                "group_id": f"gtsinger_song_{rid.replace('/', '_')}",
                "song_id": rid,
                "language": "zh",
                "source_split": "selected_mini",
                "audio_relpath": str(selected_prefix / wav_path.relative_to(selected)) if wav_path.exists() else None,
                "audio_exists": wav_path.is_file(),
                "duration_sec": duration,
                "annotation_granularity": "word+phoneme",
                "tier": tier,
                "metadata": {
                    "textgrid_relpath": str(selected_prefix / textgrid_path.relative_to(selected)) if textgrid_path.exists() else None,
                    "musicxml_relpath": str(selected_prefix / musicxml_path.relative_to(selected)) if musicxml_path.exists() else None,
                    "word_count": word_count,
                    "techniques": techs,
                },
            })
    return rows


def leakage_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    group_tiers: dict[str, set[str]] = defaultdict(set)
    song_tiers: dict[str, set[str]] = defaultdict(set)
    item_ids: Counter[str] = Counter()
    for row in rows:
        gid = str(row.get("group_id", ""))
        tier = str(row.get("tier", ""))
        group_tiers[gid].add(tier)
        song_key = (str(row.get("dataset_id", "")), str(row.get("song_id", "")))
        song_tiers[song_key].add(tier)
        item_ids[str(row.get("item_id", ""))] += 1
    cross_group = sorted(g for g, tiers in group_tiers.items() if len(tiers) > 1)
    cross_song = sorted(s for s, tiers in song_tiers.items() if len(tiers) > 1)
    duplicates = sorted(i for i, c in item_ids.items() if c > 1)
    return {
        "record_count": len(rows),
        "group_count": len(group_tiers),
        "same_group_cross_tier": cross_group,
        "same_song_cross_tier": cross_song,
        "duplicate_item_ids": duplicates,
        "passed": not cross_group and not cross_song and not duplicates,
    }


def write_cleanup_report(out_root: Path, generated_files: list[Path], note: str) -> None:
    import datetime as _dt
    existing = [
        p for p in out_root.iterdir()
        if p.is_file() and p.name != "cleanup_report.md"
    ] if out_root.exists() else []
    generated_files = sorted(set(generated_files) | set(existing), key=lambda p: p.name)
    lines = [
        "# Cleanup Report — Evaluation V1 Split Manifest Batch",
        "",
        f"Generated at UTC: {_dt.datetime.now(_dt.timezone.utc).isoformat()}",
        "",
        "This batch writes only small JSON/JSONL/Markdown files. No audio, model",
        "checkpoints, videos, or other large derived assets are created.",
        "",
        "## Files in this batch",
        "",
        "| File | Size (bytes) | Recreate command |",
        "|---|---|---|",
    ]
    for path in sorted(generated_files):
        if path.name == "cleanup_report.md":
            continue
        size = path.stat().st_size if path.exists() else 0
        lines.append(f"| `{path.relative_to(out_root)}` | {size} | `python scripts/evaluation/build_evaluation_v1_split_manifest.py --out-root {out_root}` |")
    lines += [
        "",
        "## Cleanup",
        "",
        "To remove this entire batch:",
        "",
        "```bash",
        f"rm -rf {out_root}",
        "```",
        "",
        "All files are reproducible from the external datasets and fixed seed;",
        "deleting them does not destroy any unique research asset.",
        "",
        "## Note",
        "",
        note,
        "",
    ]
    (out_root / "cleanup_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--datasets-root", type=Path, default=DEFAULT_DATASETS_ROOT)
    parser.add_argument("--seed", default="evaluation-v1-20260816")
    parser.add_argument("--no-audio-check", action="store_true", help="Do not attempt WAV duration reads (faster smoke)")
    args = parser.parse_args()

    if args.no_audio_check:
        global AUDIO_CHECK_ENABLED
        AUDIO_CHECK_ENABLED = False

    rows: list[dict[str, Any]] = []
    rows.extend(collect_mir_mlpop(args.datasets_root, args.seed))
    rows.extend(collect_jamendolyrics(args.datasets_root, args.seed))
    rows.extend(collect_pjs(args.datasets_root, args.seed))
    rows.extend(collect_gtsinger(args.datasets_root, args.seed))

    audit = leakage_audit(rows)
    if not audit["passed"]:
        raise SystemExit(json.dumps(audit, ensure_ascii=False, indent=2))

    # Aggregate summary.
    tier_counts: Counter[str] = Counter()
    dataset_tier_counts: dict[str, dict[str, int]] = defaultdict(lambda: {t: 0 for t in TIERS})
    group_ids: dict[str, set[str]] = defaultdict(set)
    durations: dict[str, float] = defaultdict(float)
    for row in rows:
        tier = str(row["tier"])
        tier_counts[tier] += 1
        ds = str(row["dataset_id"])
        dataset_tier_counts[ds][tier] += 1
        group_ids[ds].add(str(row["group_id"]))
        if row.get("duration_sec"):
            durations[ds] += float(row["duration_sec"])
    audio_with_path = sum(1 for row in rows if row.get("audio_relpath"))
    audio_without_path = len(rows) - audio_with_path

    summary = {
        "schema_version": "evaluation_v1_split_draft",
        "seed": args.seed,
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "tier_counts": dict(sorted(tier_counts.items())),
        "dataset_tier_counts": {k: dict(sorted(v.items())) for k, v in sorted(dataset_tier_counts.items())},
        "dataset_group_counts": {k: len(v) for k, v in sorted(group_ids.items())},
        "dataset_duration_sec": {k: round(v, 3) for k, v in sorted(durations.items())},
        "audio_rows_with_path": audio_with_path,
        "audio_rows_without_path": audio_without_path,
        "leakage_audit": audit,
        "status": "draft_not_frozen",
        "notes": [
            "This is a draft manifest, not a frozen evaluation set.",
            "Sealed rows are not run by default; a runner must require --allow-sealed.",
            "MIR-MLPop official Test cmn is fully sealed; yue is a 1/1/1 exploratory probe.",
            "Jamendo/GTSinger still need vocal derivation/provenance before operational use.",
        ],
    }

    out_root = args.out_root
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "evaluation_v1_split_manifest.jsonl"
    summary_path = out_root / "evaluation_v1_split_summary.json"
    audit_path = out_root / "evaluation_v1_leakage_audit.json"
    sha_path = out_root / "evaluation_v1_manifest.sha256"

    atomic_jsonl(manifest_path, rows)
    atomic_json(summary_path, summary)
    atomic_json(audit_path, audit)

    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    sha_path.write_text(f"{manifest_hash}  {manifest_path.name}\n", encoding="utf-8")

    generated = [manifest_path, summary_path, audit_path, sha_path, out_root / "cleanup_report.md"]
    write_cleanup_report(out_root, generated, "Draft split manifest; review before freezing.")

    print(json.dumps({
        "out_root": str(out_root),
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "summary": summary,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
