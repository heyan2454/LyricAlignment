#!/usr/bin/env python3
"""P2 收尾（CPU）：修正 recovery_class 语义 + natural propagation 提取。

1. recovery_class 的 occurrence_jump 必须基于首错行 error_sec > 10s（时间跳跃），
   而非 wrong 行数 > 10（09 P2 / 02 §7 定义）。
2. natural：从 corrected T2 per-song records 事后提取首个 wrong commit 及其 follow-up。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

TOLERANCE = 0.32


def classify_recovery(followup: list[dict]) -> str:
    """02 §7：occurrence_jump 首错行 error_sec>10；否则按 wrong 行数模式。"""
    wrongs = [w["new_wrong"] for w in followup]
    first_err = followup[0].get("max_error_sec") if followup else None
    if first_err is not None and first_err > 10.0:
        return "occurrence_jump"
    if not wrongs or all(w == 0 for w in wrongs):
        return "self_recover"
    first_new_wrong = next((w for w in wrongs if w > 0), 0)
    if len(wrongs) <= 3 and all(w == 0 for w in wrongs[1:]):
        return "slow_recover"
    if any(w > first_new_wrong for w in wrongs):
        return "amplifying"
    return "persistent"


def recompute_from_records(episodes_path: Path, transition_dir: Path, gt_by_song: dict) -> int:
    """从 records jsonl 重算 followup 的 max_error_sec 与 recovery_class（CPU）。"""
    lines = episodes_path.read_text(encoding="utf-8").splitlines()
    out = []
    n_updated = 0
    for line in lines:
        if not line.strip():
            continue
        ep = json.loads(line)
        if ep.get("natural"):
            out.append(ep)
            continue
        gt = gt_by_song.get(ep["source_song_id"])
        if gt is None:
            out.append(ep)
            continue
        fam = ep["intervention"]["family"]
        rec_path = transition_dir / f"{ep['source_song_id']}::corr::{fam}__T2_core_boundary_serial.jsonl"
        if not rec_path.is_file():
            out.append(ep)
            continue
        records = [json.loads(l) for l in rec_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        # 同 family 多 spec 共用同一 records 文件（09 review P0-2：轨迹按 window 交错）。
        # 按 state_before.committed_end 链式还原本 episode 对应的轨迹：
        # 首窗 = corrupted state 的 committed_end；其后窗 = 上一窗 state_after.committed_end。
        target = int(ep["state_before"]["committed_end_exclusive"])
        by_before = {}
        for rec in records:
            by_before.setdefault(int(rec["state_before"]["committed_end_exclusive"]), []).append(rec)
        chain = []
        cur = target
        while cur in by_before and len(chain) < 8:
            rec = by_before[cur][0]
            chain.append(rec)
            cur = int(rec["state_after"]["committed_end_exclusive"])
        if not chain:
            out.append(ep)
            continue
        followup = []
        for rec in chain:
            before = rec["state_before"]["committed_end_exclusive"]
            after = rec["decision"]["committed_end_exclusive"]
            max_err = 0.0
            wrong = 0
            for r in rec["evidence_summary"]["raw_global_rows"]:
                i = int(r["global_character_index"])
                if not (before <= i < after):
                    continue
                s = float(r.get("original_global_start_sec", r["fixed_global_start_sec"]))
                err = abs(s - gt[i]["start_sec"])
                max_err = max(max_err, err)
                if err > TOLERANCE:
                    wrong += 1
            followup.append({"window_index": rec["window_index"],
                             "new_committed": after - before, "new_wrong": wrong,
                             "max_error_sec": round(max_err, 3)})
        ep["followup_windows"] = followup[:5]
        ep["recovery_class"] = classify_recovery(followup[:5])
        out.append(ep)
        n_updated += 1
    episodes_path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in out), "utf-8")
    return n_updated


def extract_natural(transition_dir: Path, song_ids: list[str], gt_by_song: dict,
                    episodes_path: Path) -> list[dict]:
    """T2 轨迹事后提取 natural episodes（首个 wrong commit 及其 follow-up）。"""
    existing = []
    if episodes_path.is_file():
        existing = [json.loads(l) for l in episodes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    known = {e["episode_id"] for e in existing}
    new_nat = []
    for song_id in song_ids:
        gt = gt_by_song.get(song_id)
        if gt is None:
            continue
        rec_path = transition_dir / f"{song_id}__T2_core_boundary_serial.jsonl"
        if not rec_path.is_file():
            continue
        records = [json.loads(l) for l in rec_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        # 首错窗
        err_win = None
        first_wrong = None
        for rec in records:
            before = rec["state_before"]["committed_end_exclusive"]
            after = rec["decision"]["committed_end_exclusive"]
            for r in rec["evidence_summary"]["raw_global_rows"]:
                i = int(r["global_character_index"])
                if not (before <= i < after):
                    continue
                s = float(r.get("original_global_start_sec", r["fixed_global_start_sec"]))
                err = abs(s - gt[i]["start_sec"])
                if err > TOLERANCE:
                    err_win = rec["window_index"]
                    first_wrong = {"global_character_index": i, "start_sec": s,
                                   "gt_start_sec": gt[i]["start_sec"], "error_sec": round(err, 3)}
                    break
            if err_win is not None:
                break
        if err_win is None:
            continue
        eid = f"nat_{song_id}"
        if eid in known:
            continue
        followup = []
        for rec in records:
            if rec["window_index"] < err_win:
                continue
            before = rec["state_before"]["committed_end_exclusive"]
            after = rec["decision"]["committed_end_exclusive"]
            max_err = 0.0
            wrong = 0
            for r in rec["evidence_summary"]["raw_global_rows"]:
                i = int(r["global_character_index"])
                if not (before <= i < after):
                    continue
                s = float(r.get("original_global_start_sec", r["fixed_global_start_sec"]))
                err = abs(s - gt[i]["start_sec"])
                max_err = max(max_err, err)
                if err > TOLERANCE:
                    wrong += 1
            followup.append({"window_index": rec["window_index"],
                             "new_committed": after - before, "new_wrong": wrong,
                             "max_error_sec": round(max_err, 3)})
        ep = {
            "episode_id": eid, "family": "natural", "source": "natural",
            "source_song_id": song_id, "transition_id": "T2_core_boundary_serial",
            "natural": True, "window_index_before_intervention": err_win,
            "continue_from_window_index": err_win + 1,
            "state_before": records[err_win]["state_before"],
            "first_wrong_commit": first_wrong,
            "followup_windows": followup[:5],
            "recovery_class": classify_recovery(followup[:5]),
            "provenance": {"corrected_formal": True, "query_estimator_version": "units_per_sec_v2"},
            "no_effect_attempt": False,
        }
        new_nat.append(ep)
    with open(episodes_path, "a", encoding="utf-8") as f:
        for ep in new_nat:
            f.write(json.dumps(ep, ensure_ascii=False) + "\n")
    return new_nat


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="model_selection")
    args = p.parse_args()
    session_root = Path(args.session_root)
    episodes_path = session_root / "03_propagation" / "EPISODES.jsonl"
    transition_dir = session_root / "02_transition"
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][args.role]
    gt_by_song = {}
    for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            gt_by_song[r["song_id"]] = {int(u["canonical_unit_id"]): u for u in r["canonical_units"]}

    n_upd = recompute_from_records(episodes_path, transition_dir, gt_by_song) if episodes_path.is_file() else 0
    new_nat = extract_natural(transition_dir, song_ids, gt_by_song, episodes_path)
    from collections import Counter

    eps = [json.loads(l) for l in episodes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(json.dumps({
        "reclassified": n_upd, "natural_new": len(new_nat),
        "total_episodes": len(eps),
        "sources": dict(Counter(e.get("source") for e in eps)),
        "recovery": dict(Counter(e.get("recovery_class") for e in eps)),
        "no_effect": sum(1 for e in eps if e.get("no_effect_attempt")),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
