#!/usr/bin/env python3
"""Doc 19 Stage 2：real-GT cohort builder（CPU-only，确定性）。

从 split manifest（role 映射）+ overlay manifest（段/时长）+ annotations（真实 GT）
构造三 cohort：
  Cohort A = split 'test'       → COHORT_A_FORMAL
  Cohort B = split 'validation' → COHORT_B_DEVELOPMENT
  Cohort D = split 'train'      → COHORT_D_TRAIN_OVERLAP_DIAGNOSTIC

预注册 exclusion gate（顺序固定，只有这些 reason 才允许移除候选；每个排除都记录原因）：
  1. not_in_split             —— overlay 歌不在 split manifest
  2. duplicate_in_split       —— 同一歌在 split manifest 出现 >1 次
  3. not_in_role              —— role 不在允许集合 {test, validation, train}
  4. missing_audio            —— 段音频（audio_root/audio_relpath）缺失
  5. below_min_natural_duration —— natural_duration（段时长之和，不做 seam）< 阈值
  (materialize 追加)
  6. below_coverage_gate      —— real_gt 投影 coverage < diagnostic_floor（移除）；
                                 [floor, primary_gate) 记为 diagnostic_only 保留

无 --materialize：只产出 inventory + 候选清单 + EXCLUSION_LOG + SPLIT_AUDIT + FREEZE
（不调用 builder，不读 annotations）。
--materialize：额外为 A/B 生成 allowlist，subprocess 调
scripts/research_v7/build_long_timeline_manifest.py 构造 LONG_TIMELINE_MANIFEST，
再对每个 manifest 跑 load_real_gt_with_audit 投影，按 coverage gate 冻结最终 cohort。

用法：
  PYTHONPATH=src python scripts/research_transition_recovery_detector/build_real_gt_cohorts.py \
      --overlay-manifest <m4singer_manifest.jsonl> \
      --annotations <m4singer_character_annotations.jsonl> \
      --split-manifest <m4singer_accepted_split_manifest.jsonl> \
      --audio-root <dir> --out-root <run> [--materialize]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
BUILDER = REPO_ROOT / "scripts" / "research_v7" / "build_long_timeline_manifest.py"

ALLOWED_SPLITS: tuple[str, ...] = ("test", "validation", "train")
COHORT_ROLE = {"A": "test", "B": "validation", "D": "train"}
PRE_REGISTERED_GATES: tuple[str, ...] = (
    "not_in_split",
    "duplicate_in_split",
    "not_in_role",
    "missing_audio",
    "below_min_natural_duration",
    "below_coverage_gate",
)
DIAGNOSTIC_ONLY_NOTE = "coverage in [diagnostic_floor, primary_coverage_gate) kept as diagnostic-only"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_jsonl(path: Path, rows: list[dict]) -> None:
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_json(path: Path, payload: dict) -> None:
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def load_split_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """split manifest（含 split/song_id）→ {song_id: {role, n_split_occurrences, duplicate_in_split}}。

    manifest 是逐段行（每首歌可能多行）。同一歌多行同 role 视为重复行去重；
    仅当同一歌跨行 role 不一致（真正冲突）才记 duplicate_in_split=True。
    role 取首个出现的值，n_split_occurrences 为该歌在 manifest 中的行数。
    """
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        song = r.get("song_id")
        role = r.get("split")
        if not song or not role:
            continue
        entry = out.setdefault(song, {
            "role": None, "n_split_occurrences": 0, "duplicate_in_split": False,
        })
        entry["n_split_occurrences"] += 1
        if entry["role"] is None:
            entry["role"] = role
        elif role != entry["role"]:
            entry["duplicate_in_split"] = True
    return out


def load_overlay_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """overlay manifest（含 duration_sec/item_id/song_id）→ {song_id: {segments, ...}}。

    natural_duration_sec = 段时长之和（不做 seam）；段按 item_id 稳定排序。
    """
    by_song: dict[str, list[dict]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        song = r.get("song_id")
        if not song:
            continue
        by_song.setdefault(song, []).append({
            "item_id": r.get("item_id"),
            "audio_relpath": r.get("audio_relpath", ""),
            "duration_sec": float(r.get("duration_sec", 0.0) or 0.0),
        })
    out: dict[str, dict[str, Any]] = {}
    for song, segs in by_song.items():
        segs_sorted = sorted(segs, key=lambda s: str(s["item_id"]))
        out[song] = {
            "segments": segs_sorted,
            "n_segments": len(segs_sorted),
            "natural_duration_sec": round(sum(s["duration_sec"] for s in segs_sorted), 3),
        }
    return out


def _segment_audio_path(audio_root: Path, relpath: str) -> Path:
    rel = relpath if relpath else ""
    return audio_root / rel if rel else audio_root


def build_inventory(
    overlay: dict[str, dict[str, Any]],
    split_songs: dict[str, dict[str, Any]],
    audio_root: Path,
) -> list[dict]:
    """过滤前完整 inventory（确定性，按 song_id 排序）。"""
    rows: list[dict] = []
    for song in sorted(overlay):
        entry = split_songs.get(song)
        segs = overlay[song]["segments"]
        first_rel = (segs[0].get("audio_relpath") or "") if segs else ""
        audio_paths = [_segment_audio_path(audio_root, s.get("audio_relpath") or "")
                       for s in segs]
        rows.append({
            "song_id": song,
            "role": entry["role"] if entry else None,
            "n_segments": overlay[song]["n_segments"],
            "natural_duration_sec": overlay[song]["natural_duration_sec"],
            "in_split": bool(entry),
            "n_split_occurrences": entry["n_split_occurrences"] if entry else 0,
            "duplicate_in_split": entry["duplicate_in_split"] if entry else False,
            "audio_ok": all(p.is_file() for p in audio_paths) and bool(audio_paths),
            "audio_path": str(audio_root / first_rel) if first_rel else "",
        })
    return rows


def classify_songs(
    inventory: list[dict],
    min_natural_duration_sec: float,
) -> tuple[list[dict], dict[str, int]]:
    """预注册 gate 顺序分类：返回 (candidate_rows, exclusion_stats)。

    candidate 直接按 (natural_duration_sec, song_id) 排序（跨 role 统一排）。
    """
    candidates: list[dict] = []
    stats: dict[str, int] = {reason: 0 for reason in PRE_REGISTERED_GATES}
    for row in sorted(inventory, key=lambda r: (r["natural_duration_sec"], r["song_id"])):
        reason = None
        if not row["in_split"]:
            reason = "not_in_split"
        elif row["duplicate_in_split"]:
            reason = "duplicate_in_split"
        elif row["role"] not in ALLOWED_SPLITS:
            reason = "not_in_role"
        elif not row["audio_ok"]:
            reason = "missing_audio"
        elif row["natural_duration_sec"] < min_natural_duration_sec:
            reason = "below_min_natural_duration"
        if reason is not None:
            stats[reason] += 1
            continue
        candidates.append(row)
    return candidates, stats


def candidate_rows(candidates: list[dict], role: str) -> list[dict]:
    """按 role 过滤候选，schema：{song_id, split, natural_duration_sec, n_segments, audio_path}。"""
    out = []
    for r in candidates:
        if r["role"] != role:
            continue
        out.append({
            "song_id": r["song_id"],
            "split": r["role"],
            "natural_duration_sec": r["natural_duration_sec"],
            "n_segments": r["n_segments"],
            "audio_path": r["audio_path"],
        })
    return out


def build_split_audit(
    inventory: list[dict],
    split_songs: dict[str, dict[str, Any]],
    cand_a: list[dict],
    cand_b: list[dict],
    cand_d: list[dict],
    min_natural_duration_sec: float,
    primary_coverage_gate: float,
    diagnostic_coverage_floor: float,
) -> dict:
    a_ids = {r["song_id"] for r in cand_a}
    b_ids = {r["song_id"] for r in cand_b}
    d_ids = {r["song_id"] for r in cand_d}
    checks = {
        "a_b_disjoint": a_ids.isdisjoint(b_ids),
        "a_b_no_train_overlap": a_ids.isdisjoint(d_ids) and b_ids.isdisjoint(d_ids),
        "a_songs_exactly_once_in_split": all(not split_songs.get(s, {}).get("duplicate_in_split")
                                             for s in a_ids),
        "b_songs_exactly_once_in_split": all(not split_songs.get(s, {}).get("duplicate_in_split")
                                             for s in b_ids),
    }
    n_in_inventory = {s: split_songs.get(s, {}).get("n_split_occurrences", 0) for s in
                      sorted({r["song_id"] for r in inventory})}
    return {
        "schema": "build_real_gt_cohorts_split_audit_v1",
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "counts": {
            "cohort_a": len(cand_a), "cohort_b": len(cand_b), "cohort_d": len(cand_d),
            "inventory_songs": len(inventory),
        },
        "split_occurrences_in_inventory": n_in_inventory,
        "gates": {
            "min_natural_duration_sec": min_natural_duration_sec,
            "primary_coverage_gate": primary_coverage_gate,
            "diagnostic_coverage_floor": diagnostic_coverage_floor,
        },
    }


def _manifest_row_sha(row: dict) -> str:
    return _sha_bytes(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def project_real_gt(annotations: Path, manifest: Path) -> tuple[dict, dict[str, dict]]:
    """load_real_gt_with_audit → (real_gt, per_song_coverage)。"""
    from lyricalign.research_transition_recovery_detector.real_gt import load_real_gt_with_audit

    real_gt, audit = load_real_gt_with_audit(annotations, manifest)
    rows = [json.loads(l) for l in manifest.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_song = {r["song_id"]: r for r in rows}
    coverage: dict[str, dict] = {}
    for song, aud in sorted(audit.items()):
        total = len(real_gt.get(song, {})) + sum(aud.values())
        accepted = len(real_gt.get(song, {}))
        coverage[song] = {
            "song_id": song,
            "total_units": total,
            "accepted_gt_units": accepted,
            "unlabeled_units": total - accepted,
            "coverage": round(accepted / total, 6) if total else 0.0,
            "unlabeled_by_reason": aud,
            "manifest_row_sha": _manifest_row_sha(by_song[song]),
        }
    return real_gt, coverage


def run_builder(
    overlay_manifest: Path,
    out_root: Path,
    audio_root: Path,
    min_duration: float,
    seam_silence_sec: float,
    allowlist: Path,
    n_allowlist: int,
) -> None:
    """subprocess 调 research_v7 builder（PYTHONPATH=src）。"""
    limit = max(20, n_allowlist)
    cmd = [
        sys.executable, str(BUILDER),
        "--m4-manifest", str(overlay_manifest),
        "--out-root", str(out_root),
        "--audio-root", str(audio_root),
        "--min-duration", str(min_duration),
        "--seam-silence-sec", str(seam_silence_sec),
        "--song-allowlist", str(allowlist),
        "--limit", str(limit),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(
            f"builder failed rc={proc.returncode}\ncmd={' '.join(cmd)}\n"
            f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-4000:]}"
        )


def write_allowlist(path: Path, cand: list[dict], role: str) -> None:
    rows = [{"song_id": r["song_id"], "role": role} for r in cand]
    _atomic_jsonl(path, rows)


def materialize_cohort(
    args: argparse.Namespace,
    cand: list[dict],
    cohort_tag: str,
    allowlist: Path,
    manifest_dir: Path,
    real_gt_dir: Path,
    exclusion_rows: list[dict],
    primary_gate: float,
    floor: float,
) -> tuple[list[dict], dict]:
    """为单个 cohort 跑 builder + real_gt 投影 + coverage gate。

    返回 (frozen_rows, builder_freeze_snapshot)。frozen_rows schema：
    {song_id, split, natural_duration_sec, n_segments, audio_path,
     long_manifest_row_sha, coverage, accepted_gt_units, unlabeled_units}
    """
    role = COHORT_ROLE[cohort_tag.upper()]
    if not cand:
        _atomic_jsonl(real_gt_dir / f"REAL_GT_COVERAGE_{cohort_tag}.jsonl", [])
        _atomic_json(real_gt_dir / f"REAL_GT_PROJECTION_AUDIT_{cohort_tag}.json", {
            "cohort": cohort_tag, "schema": "real_gt_projection_audit_v1",
            "summary": {"songs": 0, "accepted_gt_units": 0, "unlabeled_units": 0},
            "per_song": {},
        })
        return [], {"rejected_songs": [], "builder_rejected": [], "diagnostic_songs": [],
                    "diag_rows": [], "builder_rejections_path": None}
    write_allowlist(allowlist, cand, role)
    run_builder(
        args.overlay_manifest, manifest_dir, args.audio_root,
        args.min_natural_duration_sec, args.seam_silence_sec, allowlist, len(cand),
    )
    manifest_path = manifest_dir / "LONG_TIMELINE_MANIFEST.jsonl"
    if not manifest_path.is_file():
        raise RuntimeError(f"builder produced no LONG_TIMELINE_MANIFEST at {manifest_dir}")
    real_gt, coverage = project_real_gt(args.annotations, manifest_path)

    audit_doc = {
        "cohort": cohort_tag,
        "schema": "real_gt_projection_audit_v1",
        "summary": {
            "songs": len(coverage),
            "accepted_gt_units": sum(c["accepted_gt_units"] for c in coverage.values()),
            "unlabeled_units": sum(c["unlabeled_units"] for c in coverage.values()),
        },
        "per_song": {s: {k: v for k, v in c.items() if k not in ("manifest_row_sha",)}
                     for s, c in coverage.items()},
    }
    _atomic_json(real_gt_dir / f"REAL_GT_PROJECTION_AUDIT_{cohort_tag}.json", audit_doc)

    cov_rows = []
    frozen: list[dict] = []
    diag_rows: list[dict] = []
    rejected_songs: list[str] = []
    for c in sorted(coverage.values(), key=lambda x: x["song_id"]):
        if c["coverage"] < floor:
            status = "below_floor"
        elif c["coverage"] < primary_gate:
            status = "diagnostic_only"
        else:
            status = "formal"
        cov_rows.append({
            "song_id": c["song_id"], "split": role,
            "total_units": c["total_units"], "accepted": c["accepted_gt_units"],
            "unlabeled": c["unlabeled_units"], "coverage": c["coverage"],
            "gate_status": status, "diagnostic_only_note": DIAGNOSTIC_ONLY_NOTE
            if status == "diagnostic_only" else None,
        })
        if c["coverage"] < floor:
            rejected_songs.append(c["song_id"])
            exclusion_rows.append({
                "song_id": c["song_id"], "role": role, "reason": "below_coverage_gate",
                "coverage": c["coverage"],
                "note": f"coverage < diagnostic_floor ({floor}); "
                        f"[{floor}, {primary_gate}) would be diagnostic-only, {primary_gate}+ formal",
            })
            continue
        base = next(r for r in cand if r["song_id"] == c["song_id"])
        row = {
            "song_id": c["song_id"], "split": role,
            "natural_duration_sec": base["natural_duration_sec"],
            "n_segments": base["n_segments"], "audio_path": base["audio_path"],
            "long_manifest_row_sha": c["manifest_row_sha"],
            "coverage": c["coverage"],
            "accepted_gt_units": c["accepted_gt_units"],
            "unlabeled_units": c["unlabeled_units"],
        }
        if status == "diagnostic_only":
            row["gate_status"] = "diagnostic_only"
            row["diagnostic_only_note"] = DIAGNOSTIC_ONLY_NOTE
            diag_rows.append(row)
            exclusion_rows.append({
                "song_id": c["song_id"], "role": role, "reason": "diagnostic_only_range",
                "coverage": c["coverage"],
                "note": f"coverage in [{floor}, {primary_gate}) kept as diagnostic-only "
                        f"(not in formal/development cohort)",
            })
            continue
        frozen.append(row)
    # builder 可能拒绝 allowlist 内歌曲（防御性上报，不参与 gate 统计）
    rej_path = manifest_dir / "ALLOWLIST_REJECTIONS.jsonl"
    builder_rejected = []
    if rej_path.is_file():
        for line in rej_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rr = json.loads(line)
            if rr.get("song_id") in {r["song_id"] for r in cand}:
                builder_rejected.append(rr)
                exclusion_rows.append({
                    "song_id": rr.get("song_id"), "role": role,
                    "reason": "builder_rejected",
                    "note": f"rejected by research_v7 builder; detail="
                            f"{json.dumps(rr, ensure_ascii=False, sort_keys=True)}",
                })
    _atomic_jsonl(real_gt_dir / f"REAL_GT_COVERAGE_{cohort_tag}.jsonl", cov_rows)
    return frozen, {
        "rejected_songs": rejected_songs,
        "builder_rejected": builder_rejected,
        "diagnostic_songs": [r["song_id"] for r in diag_rows],
        "diag_rows": diag_rows,
        "builder_rejections_path": str(rej_path) if rej_path.is_file() else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--overlay-manifest", required=True, help="m4singer_manifest.jsonl")
    p.add_argument("--annotations", required=True, help="m4singer_character_annotations.jsonl")
    p.add_argument("--split-manifest", required=True, help="accepted split manifest jsonl")
    p.add_argument("--audio-root", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--min-natural-duration-sec", type=float, default=180.0)
    p.add_argument("--primary-coverage-gate", type=float, default=0.90)
    p.add_argument("--diagnostic-coverage-floor", type=float, default=0.85)
    p.add_argument("--seam-silence-sec", type=float, default=0.0)
    p.add_argument("--materialize", action="store_true",
                   help="调 builder 子进程 + real_gt 投影并冻结最终 cohort")
    args = p.parse_args(argv)

    out_root = Path(args.out_root)
    audio_root = Path(args.audio_root)
    overlay_path = Path(args.overlay_manifest)
    annotations_path = Path(args.annotations)
    split_path = Path(args.split_manifest)
    if args.diagnostic_coverage_floor > args.primary_coverage_gate:
        print(f"ERROR: diagnostic_coverage_floor ({args.diagnostic_coverage_floor}) "
              f"must be <= primary_coverage_gate ({args.primary_coverage_gate})", file=sys.stderr)
        return 2

    overlay = load_overlay_manifest(overlay_path)
    split_songs = load_split_manifest(split_path)
    inventory = build_inventory(overlay, split_songs, audio_root)
    candidates, exclusion_stats = classify_songs(inventory, args.min_natural_duration_sec)

    cand_a = candidate_rows(candidates, "test")
    cand_b = candidate_rows(candidates, "validation")
    cand_d = candidate_rows(candidates, "train")

    inventory_dir = out_root / "inventory"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    inv_path = inventory_dir / "COMPLETE_SONG_INVENTORY.jsonl"
    _atomic_jsonl(inv_path, sorted(inventory, key=lambda r: r["song_id"]))
    cand_paths = {
        "A": out_root / "COHORT_A_FORMAL_candidates.jsonl",
        "B": out_root / "COHORT_B_DEVELOPMENT_candidates.jsonl",
        "D": out_root / "COHORT_D_TRAIN_OVERLAP_DIAGNOSTIC_candidates.jsonl",
    }
    _atomic_jsonl(cand_paths["A"], cand_a)
    _atomic_jsonl(cand_paths["B"], cand_b)
    _atomic_jsonl(cand_paths["D"], cand_d)

    # 从 inventory 重算每个排除原因的具体行（保持 gate 顺序）
    excl_by_song: dict[str, str] = {}
    for row in sorted(inventory, key=lambda r: (r["natural_duration_sec"], r["song_id"])):
        if row["song_id"] in {c["song_id"] for c in candidates}:
            continue
        if not row["in_split"]:
            reason = "not_in_split"
        elif row["duplicate_in_split"]:
            reason = "duplicate_in_split"
        elif row["role"] not in ALLOWED_SPLITS:
            reason = "not_in_role"
        elif not row["audio_ok"]:
            reason = "missing_audio"
        else:
            reason = "below_min_natural_duration"
        excl_by_song[row["song_id"]] = reason
    exclusion_rows = [
        {"song_id": s, "role": next(r["role"] for r in inventory if r["song_id"] == s),
         "reason": reason}
        for s, reason in sorted(excl_by_song.items())
    ]
    excl_path = out_root / "EXCLUSION_LOG.jsonl"
    _atomic_jsonl(excl_path, exclusion_rows)

    audit = build_split_audit(
        inventory, split_songs, cand_a, cand_b, cand_d,
        args.min_natural_duration_sec, args.primary_coverage_gate,
        args.diagnostic_coverage_floor,
    )
    audit_path = out_root / "SPLIT_AUDIT.json"
    _atomic_json(audit_path, audit)

    freeze = {
        "schema": "build_real_gt_cohorts_freeze_v1",
        "git_head_sha": _git_head(),
        "cli_args": {k: str(getattr(args, k)) for k in
                     ("min_natural_duration_sec", "primary_coverage_gate",
                      "diagnostic_coverage_floor", "seam_silence_sec", "materialize")},
        "inputs": {
            "overlay_manifest": {"path": str(overlay_path), "sha256": _sha_file(overlay_path)},
            "annotations": {"path": str(annotations_path), "sha256": _sha_file(annotations_path)},
            "split_manifest": {"path": str(split_path), "sha256": _sha_file(split_path)},
            "audio_root": str(audio_root),
        },
        "gates": {
            "min_natural_duration_sec": args.min_natural_duration_sec,
            "primary_coverage_gate": args.primary_coverage_gate,
            "diagnostic_coverage_floor": args.diagnostic_coverage_floor,
            "seam_silence_sec": args.seam_silence_sec,
        },
        "candidate_counts": {
            "cohort_a": len(cand_a), "cohort_b": len(cand_b), "cohort_d": len(cand_d),
        },
        "exclusion_stats": exclusion_stats,
        "files": {
            "inventory": _sha_file(inv_path),
            "cohort_a_candidates": _sha_file(cand_paths["A"]),
            "cohort_b_candidates": _sha_file(cand_paths["B"]),
            "cohort_d_candidates": _sha_file(cand_paths["D"]),
            "exclusion_log": _sha_file(excl_path),
            "split_audit": _sha_file(audit_path),
        },
    }
    freeze_path = out_root / "FREEZE.json"

    if not args.materialize:
        _atomic_json(freeze_path, freeze)
        print(json.dumps({"ok": True, "materialized": False,
                          "cohort_a": len(cand_a), "cohort_b": len(cand_b),
                          "cohort_d": len(cand_d), "exclusions": sum(exclusion_stats.values())},
                         ensure_ascii=False))
        return 0

    real_gt_dir = out_root / "real_gt"
    real_gt_dir.mkdir(parents=True, exist_ok=True)
    allow_a = out_root / "allowlist_cohort_a.jsonl"
    allow_b = out_root / "allowlist_cohort_b.jsonl"
    manifest_a = out_root / "manifest_cohort_a"
    manifest_b = out_root / "manifest_cohort_b"

    frozen_a, info_a = materialize_cohort(
        args, cand_a, "a", allow_a, manifest_a, real_gt_dir, exclusion_rows,
        args.primary_coverage_gate, args.diagnostic_coverage_floor,
    )
    frozen_b, info_b = materialize_cohort(
        args, cand_b, "b", allow_b, manifest_b, real_gt_dir, exclusion_rows,
        args.primary_coverage_gate, args.diagnostic_coverage_floor,
    )
    _atomic_jsonl(excl_path, exclusion_rows)
    exclusion_stats["below_coverage_gate"] = len(info_a["rejected_songs"]) + len(info_b["rejected_songs"])
    exclusion_stats["diagnostic_only_range"] = (
        len(info_a["diagnostic_songs"]) + len(info_b["diagnostic_songs"]))

    cohort_a_path = out_root / "COHORT_A_FORMAL.jsonl"
    cohort_b_path = out_root / "COHORT_B_DEVELOPMENT.jsonl"
    cohort_d_path = out_root / "COHORT_D_TRAIN_OVERLAP_DIAGNOSTIC.jsonl"
    diag_a_path = out_root / "COHORT_A_DIAGNOSTIC.jsonl"
    diag_b_path = out_root / "COHORT_B_DIAGNOSTIC.jsonl"
    _atomic_jsonl(cohort_a_path, frozen_a)
    _atomic_jsonl(cohort_b_path, frozen_b)
    _atomic_jsonl(cohort_d_path, cand_d)
    _atomic_jsonl(diag_a_path, info_a["diag_rows"])
    _atomic_jsonl(diag_b_path, info_b["diag_rows"])

    freeze["files"].update({
        "real_gt_projection_audit_a": _sha_file(real_gt_dir / "REAL_GT_PROJECTION_AUDIT_a.json"),
        "real_gt_projection_audit_b": _sha_file(real_gt_dir / "REAL_GT_PROJECTION_AUDIT_b.json"),
        "real_gt_coverage_a": _sha_file(real_gt_dir / "REAL_GT_COVERAGE_a.jsonl"),
        "real_gt_coverage_b": _sha_file(real_gt_dir / "REAL_GT_COVERAGE_b.jsonl"),
        "cohort_a_formal": _sha_file(cohort_a_path),
        "cohort_b_development": _sha_file(cohort_b_path),
        "cohort_d_train_overlap_diagnostic": _sha_file(cohort_d_path),
        "cohort_a_diagnostic": _sha_file(diag_a_path),
        "cohort_b_diagnostic": _sha_file(diag_b_path),
    })
    for tag, mdir in (("a", manifest_a), ("b", manifest_b)):
        key = f"manifest_cohort_{tag}"
        tl = mdir / "LONG_TIMELINE_MANIFEST.jsonl"
        if tl.is_file():
            freeze["files"][key] = _sha_file(tl)
    freeze["final_counts"] = {
        "cohort_a": len(frozen_a), "cohort_b": len(frozen_b), "cohort_d": len(cand_d),
        "cohort_a_diagnostic": len(info_a["diagnostic_songs"]),
        "cohort_b_diagnostic": len(info_b["diagnostic_songs"]),
    }
    freeze["coverage_rejected"] = {"cohort_a": info_a["rejected_songs"],
                                   "cohort_b": info_b["rejected_songs"]}
    freeze["builder_rejected"] = {
        "count": len(info_a["builder_rejected"]) + len(info_b["builder_rejected"]),
        "by_cohort": {
            "cohort_a": [r["song_id"] for r in info_a["builder_rejected"]],
            "cohort_b": [r["song_id"] for r in info_b["builder_rejected"]],
        },
        "details_files": {
            "cohort_a": info_a["builder_rejections_path"],
            "cohort_b": info_b["builder_rejections_path"],
        },
    }
    _atomic_json(freeze_path, freeze)
    print(json.dumps({"ok": True, "materialized": True,
                      "cohort_a": len(frozen_a), "cohort_b": len(frozen_b),
                      "cohort_d": len(cand_d),
                      "coverage_rejected": len(info_a["rejected_songs"]) + len(info_b["rejected_songs"]),
                      "diagnostic_only": len(info_a["diagnostic_songs"]) + len(info_b["diagnostic_songs"]),
                      "builder_rejected": len(info_a["builder_rejected"]) + len(info_b["builder_rejected"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
