"""Natural propagation episode 提取器（Phase 3，纯 CPU 事后分析，不运行模型）。

对 T2_core_boundary_serial 每首歌逐窗构造 committed rows，与 GT timeline
（tolerance 0.32s）比对判定 correct/wrong，定位首个 wrong commit 窗，构造
natural episode（每首歌最多 1 个）并按 02 §7 判定 recovery_class。
输出 EPISODES.jsonl（append）与 ATTEMPT_DENOMINATORS.json。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T2_CORE

EPISODE_FAMILY = "natural"
FAMILY_BUDGET = 64
MAX_FOLLOWUP_WINDOWS = 5


def load_timeline(timeline_manifest: str) -> dict[str, dict[int, float]]:
    gt: dict[str, dict[int, float]] = {}
    with open(timeline_manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gt[row["song_id"]] = {
                int(u["canonical_unit_id"]): float(u["start_sec"])
                for u in row["canonical_units"]
            }
    return gt


def list_t2_songs(formal_jsonl: str) -> list[str]:
    songs: list[str] = []
    with open(formal_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("transition") == TRANSITION_T2_CORE:
                songs.append(row["song_id"])
    return songs


def load_song_records(session_root: str, song_id: str) -> list[dict]:
    path = os.path.join(
        session_root, "02_transition", f"{song_id}__{TRANSITION_T2_CORE}.jsonl"
    )
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"missing per-song records for {song_id}: {path}"
        )
    records: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def committed_rows(record: dict, gt: dict[int, float], tolerance: float) -> list[dict]:
    before_end = int(record["state_before"]["committed_end_exclusive"])
    after_end = int(record["decision"]["committed_end_exclusive"])
    evidence = record.get("evidence_summary") or {}
    rows_by_id = {
        int(r["global_character_index"]): r for r in (evidence.get("raw_global_rows") or [])
    }
    out: list[dict] = []
    for cid in range(before_end, after_end):
        row = rows_by_id.get(cid)
        if row is None:
            raise KeyError(
                f"no evidence row for character {cid} in window "
                f"{record['window_index']}"
            )
        start_sec = float(row.get("original_global_start_sec", row["fixed_global_start_sec"]))
        gt_start = gt.get(cid)
        if gt_start is None:
            raise KeyError(f"no GT unit for canonical id {cid}")
        out.append(
            {
                "global_character_index": cid,
                "start_sec": start_sec,
                "gt_start_sec": gt_start,
                "error_sec": abs(start_sec - gt_start),
                "correct": abs(start_sec - gt_start) <= tolerance,
            }
        )
    return out


def classify_recovery(first_error_sec: float, first_window_wrong: int, followup: list[dict]) -> str:
    if first_error_sec > 10.0:
        return "occurrence_jump"
    if all(w["new_wrong"] == 0 for w in followup):
        return "self_recover"
    for i, w in enumerate(followup):
        if 1 <= i <= 3 and w["new_wrong"] == 0 and all(
            x["new_wrong"] == 0 for x in followup[i:]
        ):
            return "slow_recover"
    if any(w["new_wrong"] > first_window_wrong for w in followup):
        return "amplifying"
    return "persistent"


def build_episode(song_id: str, records: list[dict], gt: dict[int, float], tolerance: float) -> dict | None:
    per_window: list[dict] = []
    for rec in records:
        rows = committed_rows(rec, gt, tolerance)
        per_window.append(
            {
                "window_index": int(rec["window_index"]),
                "rows": rows,
                "new_committed": len(rows),
                "new_wrong": sum(1 for r in rows if not r["correct"]),
                "new_correct": sum(1 for r in rows if r["correct"]),
                "state_before": rec["state_before"],
            }
        )
    err_idx = next(
        (i for i, w in enumerate(per_window) if w["new_wrong"] > 0),
        None,
    )
    if err_idx is None:
        return None
    err = per_window[err_idx]
    first_wrong = next(r for r in err["rows"] if not r["correct"])
    followup = [
        {
            "window_index": w["window_index"],
            "new_committed": w["new_committed"],
            "new_wrong": w["new_wrong"],
            "new_correct": w["new_correct"],
        }
        for w in per_window[err_idx + 1 : err_idx + 1 + MAX_FOLLOWUP_WINDOWS]
    ]
    state_before = err["state_before"]
    return {
        "episode_id": f"nat_{song_id}",
        "family": EPISODE_FAMILY,
        "source": TRANSITION_T2_CORE,
        "song_id": song_id,
        "natural": True,
        "error_window": err["window_index"],
        "error_before_state": {
            "committed_end": int(state_before["committed_end_exclusive"]),
            "next_input_cursor": int(state_before["next_input_cursor"]),
        },
        "first_wrong_commit": {
            "global_character_index": first_wrong["global_character_index"],
            "start_sec": first_wrong["start_sec"],
            "gt_start_sec": first_wrong["gt_start_sec"],
            "error_sec": first_wrong["error_sec"],
        },
        "state_delta": {
            "committed_end_before": int(state_before["committed_end_exclusive"]),
            "committed_end_after": int(err["rows"][-1]["global_character_index"]) + 1,
            "new_wrong_committed": err["new_wrong"],
            "new_correct_committed": err["new_correct"],
        },
        "followup_windows": followup,
        "recovery_class": classify_recovery(
            first_wrong["error_sec"], err["new_wrong"], followup
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session-root",
        default="/home/hyan/LyricAlignment/runs/research_transition_recovery_detector_20260807/session_20260807T000000Z",
    )
    parser.add_argument(
        "--formal-jsonl",
        default=(
            "/home/hyan/LyricAlignment/runs/research_transition_recovery_detector_20260807"
            "/session_20260807T000000Z/02_transition/FORMAL_model_selection.jsonl"
        ),
    )
    parser.add_argument(
        "--timeline-manifest",
        default=(
            "/home/hyan/LyricAlignment/runs/research_transition_recovery_detector_20260807"
            "/long_manifest_60/LONG_TIMELINE_MANIFEST.jsonl"
        ),
    )
    parser.add_argument("--tolerance", type=float, default=0.32)
    args = parser.parse_args()

    gt = load_timeline(args.timeline_manifest)
    songs = list_t2_songs(args.formal_jsonl)
    episodes: list[dict] = []
    songs_with_error = 0
    for song_id in songs:
        records = load_song_records(args.session_root, song_id)
        episode = build_episode(song_id, records, gt.get(song_id, {}), args.tolerance)
        if episode is not None:
            episodes.append(episode)
            songs_with_error += 1

    out_dir = os.path.join(args.session_root, "03_propagation")
    os.makedirs(out_dir, exist_ok=True)
    episodes_path = os.path.join(out_dir, "EPISODES.jsonl")
    with open(episodes_path, "a", encoding="utf-8") as f:
        for ep in episodes:
            f.write(json.dumps(ep, ensure_ascii=False) + "\n")
    denominators = {
        "songs_analyzed": len(songs),
        "songs_with_error": songs_with_error,
        "episodes": len(episodes),
        "family_budget": FAMILY_BUDGET,
        "note": "natural 不足时由 forced/corruption 补充",
        "count_rejected_before_commit_as_propagated": False,
    }
    denom_path = os.path.join(out_dir, "ATTEMPT_DENOMINATORS.json")
    with open(denom_path, "w", encoding="utf-8") as f:
        json.dump(denominators, f, ensure_ascii=False, indent=2)
        f.write("\n")

    classes: dict[str, int] = {}
    for ep in episodes:
        classes[ep["recovery_class"]] = classes.get(ep["recovery_class"], 0) + 1
    summary = {"episodes": len(episodes), "recovery_classes": classes, **denominators}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"episodes -> {episodes_path}")
    print(f"denominators -> {denom_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
