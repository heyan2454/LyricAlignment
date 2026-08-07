#!/usr/bin/env python3
"""Phase 0：四角色 source-song-disjoint split（07 §4.1）。

同一源歌及其窗口、mutation、重复构造不得跨 role：
    detector_train / model_selection / threshold_validation / m4_formal
MIR 是 fixed transfer；Test Demo 无 GT。

输入：LONG_TIMELINE_MANIFEST.jsonl（research_v7 build_long_timeline_manifest 输出）
输出：<SESSION_ROOT>/00_meta/DATASET_SPLIT.json + SPLIT_SUMMARY.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROLES = ("detector_train", "model_selection", "threshold_validation", "m4_formal")

DEFAULT_WEIGHTS = {
    "detector_train": 0.45,
    "model_selection": 0.15,
    "threshold_validation": 0.15,
    "m4_formal": 0.25,
}


def split_songs(songs: list[dict], *, seed: int = 20260807) -> dict[str, list[str]]:
    """按 source song 哈希分桶到四角色，尽量平衡 duration/n_units 总量。

    严格保证：每个 song 只出现在一个 role；同歌构造（窗口/mutation）跟随源歌。
    """
    assigned: dict[str, list[str]] = {role: [] for role in ROLES}
    weights = DEFAULT_WEIGHTS
    totals = {role: 0.0 for role in ROLES}
    total_weight = max(sum(
        float(s.get("duration_sec", 0) or 0) + 0.01 * float(s.get("n_units", 0) or 0) for s in songs
    ), 1e-9)
    for song in sorted(songs, key=lambda s: s["song_id"]):
        song_id = song["song_id"]
        weight = float(song.get("duration_sec", 0) or 0) + 0.01 * float(song.get("n_units", 0) or 0)
        score = {
            role: totals[role] / max(weights[role] * total_weight, 1e-12)
            for role in ROLES
        }
        role = min(ROLES, key=lambda r: score[r])
        assigned[role].append(song_id)
        totals[role] += weight
    return assigned


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--min-duration", type=float, default=90.0)
    p.add_argument("--min-n-units", type=int, default=40)
    args = p.parse_args()

    out_root = Path(args.out_root)
    meta_dir = out_root / "00_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    songs = [
        {
            "song_id": r["song_id"],
            "duration_sec": float(r["duration_sec"]),
            "n_units": len(r["canonical_units"]),
            "timeline_id": r.get("timeline_id"),
        }
        for r in rows
        if float(r["duration_sec"]) >= args.min_duration
        and len(r["canonical_units"]) >= args.min_n_units
    ]
    if len(songs) < 4:
        print(f"ERROR: only {len(songs)} long songs, need >=4 for four roles", file=sys.stderr)
        return 2
    assigned = split_songs(songs)
    split = {
        "schema_version": "four_role_source_song_disjoint_v1",
        "seed": 20260807,
        "role_counts": {role: len(v) for role, v in assigned.items()},
        "roles": assigned,
        "all_songs": [s["song_id"] for s in songs],
    }
    out = meta_dir / "DATASET_SPLIT.json"
    out.write_text(json.dumps(split, ensure_ascii=False, indent=2), "utf-8")
    summary = {
        "n_long_songs": len(songs),
        "total_duration_sec": round(sum(s["duration_sec"] for s in songs), 1),
        "roles": {
            role: {
                "n_songs": len(ids),
                "duration_sec": round(sum(next(s["duration_sec"] for s in songs if s["song_id"] == i) for i in ids), 1),
            }
            for role, ids in assigned.items()
        },
        "input_manifest": str(args.timeline_manifest),
    }
    (meta_dir / "SPLIT_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
