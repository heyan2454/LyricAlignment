"""Song-level split and transparent leakage checks for alignment manifests."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any


SPLIT_VERSION = "song_hash_split_v1"


def stable_song_split(song_id: str, seed: str, validation_percent: int = 10) -> str:
    """Assign a whole song deterministically; never assign records independently."""
    if not 1 <= validation_percent < 100:
        raise ValueError("validation_percent must be in [1, 99]")
    digest = hashlib.sha256(f"{seed}:{song_id}".encode("utf-8")).digest()
    return "validation" if int.from_bytes(digest[:4], "big") % 100 < validation_percent else "train"


def freeze_m4singer_split(records: list[dict[str, Any]], seed: str, validation_percent: int = 10) -> list[dict[str, Any]]:
    # Exact normalized lyrics across songs are leakage candidates.  Keep every
    # connected song component on one side of the split rather than merely
    # reporting the conflict.
    parent = {str(row["song_id"]): str(row["song_id"]) for row in records}
    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value
    def union(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left
    lyric_owner: dict[str, str] = {}
    for row in records:
        lyric = str(row.get("lyrics_normalized", ""))
        if lyric:
            digest = hashlib.sha256(lyric.encode("utf-8")).hexdigest()
            if digest in lyric_owner:
                union(str(row["song_id"]), lyric_owner[digest])
            else:
                lyric_owner[digest] = str(row["song_id"])
    result = []
    for record in records:
        item = dict(record)
        item["split"] = stable_song_split(find(str(item["song_id"])), seed, validation_percent)
        item["split_version"] = SPLIT_VERSION
        item["split_seed"] = seed
        result.append(item)
    return result


def leakage_audit(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Find hard split violations and exact normalized-lyrics overlap across splits."""
    song_splits: dict[str, set[str]] = defaultdict(set)
    lyric_splits: dict[str, set[str]] = defaultdict(set)
    item_ids: Counter[str] = Counter()
    for record in records:
        split = str(record.get("split", ""))
        song_splits[str(record.get("song_id", ""))].add(split)
        lyrics = str(record.get("lyrics_normalized", ""))
        if lyrics:
            lyric_splits[hashlib.sha256(lyrics.encode("utf-8")).hexdigest()].add(split)
        item_ids[str(record.get("item_id", ""))] += 1
    cross_song = sorted(song for song, splits in song_splits.items() if len(splits) > 1)
    cross_lyrics = sorted(key for key, splits in lyric_splits.items() if len(splits) > 1)
    duplicates = sorted(item_id for item_id, count in item_ids.items() if count > 1)
    return {
        "schema_version": 1, "record_count": len(records), "song_cross_split": cross_song,
        "exact_lyrics_cross_split_hashes": cross_lyrics, "duplicate_item_ids": duplicates,
        "passed": not cross_song and not duplicates,
    }


def canonical_hash(records: list[dict[str, Any]]) -> str:
    encoded = "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for record in records)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
