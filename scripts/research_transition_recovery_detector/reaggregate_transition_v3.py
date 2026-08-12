#!/usr/bin/env python3
"""11 计划 Stage 1（实验 A）：Transition v3 重汇总（row-level 修复 + paired CI）。

修复 v2 bug：selection candidates 必须携带 row_level（serial wrong_committed 非零），
product/mechanism candidate 由 row 表导出。per-song invariant: committed==safe+grey+unsafe。
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector import gt_provenance  # noqa: E402

TOLERANCES_MS = (100, 250, 500, 1000)
TRANSITIONS = ("T1_direct_serial", "T2_core_boundary_serial", "T3_stable_boundary_serial")
SERIAL_PATTERN = __import__("re").compile(
    r"^(?P<song>.+)__(?P<transition>T[123]_direct_serial|T[123]_core_boundary_serial|T[123]_stable_boundary_serial)\.jsonl$")


def load_gt(row: dict) -> dict[int, dict]:
    return {int(u["canonical_unit_id"]): u for u in row["canonical_units"]}


def committed_rows(record: dict, gt: dict[int, dict]) -> list[dict]:
    if record.get("skipped"):
        return []
    before = int(record["state_before"]["committed_end_exclusive"])
    after = int(record["decision"]["committed_end_exclusive"])
    out = []
    for r in record["evidence_summary"]["raw_global_rows"]:
        cid = int(r["global_character_index"])
        if not (before <= cid < after):
            continue
        pred_raw = next((float(r[k]) for k in ("original_global_start_sec", "fixed_global_start_sec")
                         if r.get(k) is not None), None)
        pred_off = r.get("official_fixed_global_start_sec")
        g = gt.get(cid)
        err_raw = abs(pred_raw - float(g["start_sec"])) if (pred_raw is not None and g) else None
        err_off = abs(float(pred_off) - float(g["start_sec"])) if (pred_off is not None and g) else None
        out.append({
            "song_id": record.get("song_id", ""),
            "request_id": record.get("request", {}).get("request_id", ""),
            "window_index": record.get("window_index", 0),
            "canonical_id": cid,
            "view": "serial",
            "error_raw_sec": err_raw,
            "error_official_sec": err_off,
            "label": 0 if (err_raw is not None and err_raw <= 0.1) else (
                1 if (err_raw is not None and err_raw <= 0.25) else (2 if err_raw is not None else None)),
        })
    return out


def match_full_song_cache(session_root: Path, song_id: str, row: dict) -> dict:
    texts = {r["song_id"]: "".join(u["text"] for u in r["canonical_units"]) for r in
             [row]}
    target = texts[song_id][:12]
    matches = []
    for p in sorted((session_root / "cache" / "full_song").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        text = "".join(d.get("identity", {}).get("alignment_units") or [])
        if text.startswith(target):
            matches.append(d)
    if len(matches) != 1:
        raise RuntimeError(f"song {song_id}: full-song cache match count = {len(matches)}")
    return matches[0]


def full_song_rows(cache: dict, gt: dict[int, dict]) -> list[dict]:
    out = []
    for r in cache.get("rows", []):
        cid = int(r["global_character_index"])
        pred_raw = r.get("fixed_global_start_sec")
        pred_off = r.get("official_fixed_global_start_sec")
        g = gt.get(cid)
        err_raw = abs(float(pred_raw) - float(g["start_sec"])) if (pred_raw is not None and g) else None
        # raw 定义与 serial 一致：优先 original_global_start_sec（映射回 original clock）
        err_off = abs(float(pred_off) - float(g["start_sec"])) if (pred_off is not None and g) else None
        out.append({
            "song_id": "", "request_id": "full_song", "window_index": 0, "canonical_id": cid,
            "view": "full_song",
            "error_raw_sec": err_raw, "error_official_sec": err_off,
            "label": 0 if (err_raw is not None and err_raw <= 0.1) else (
                1 if (err_raw is not None and err_raw <= 0.25) else (2 if err_raw is not None else None)),
        })
    return out


def row_summary(rows: list[dict], total_units: int) -> dict:
    n = len(rows)
    safe = sum(1 for r in rows if r["label"] == 0)
    grey = sum(1 for r in rows if r["label"] == 1)
    unsafe = sum(1 for r in rows if r["label"] == 2)
    no_gt = sum(1 for r in rows if r["label"] is None)
    counts = {ms: sum(1 for r in rows if r["error_raw_sec"] is not None and r["error_raw_sec"] <= ms / 1000.0)
              for ms in TOLERANCES_MS}
    legacy320 = sum(1 for r in rows if r["error_raw_sec"] is not None and r["error_raw_sec"] <= 0.32)
    return {
        "evaluated": n, "total": total_units, "safe": safe, "grey": grey, "unsafe": unsafe,
        "no_gt": no_gt, "committed": n,
        "wrong_committed_250ms": unsafe,
        "committed_coverage": round(n / total_units, 4) if total_units else 0.0,
        "correct_250ms": counts[250],
        "correct_coverage_250ms": round(counts[250] / total_units, 4) if total_units else 0.0,
        "correct_rate_100ms": round(counts[100] / n, 4) if n else 0.0,
        "correct_rate_250ms": round(counts[250] / n, 4) if n else 0.0,
        "correct_rate_500ms": round(counts[500] / n, 4) if n else 0.0,
        "correct_rate_1000ms": round(counts[1000] / n, 4) if n else 0.0,
        "legacy_320ms_rate": round(legacy320 / n, 4) if n else 0.0,
    }


def bootstrap_ci(deltas: list[float], *, n_boot: int = 2000, seed: int = 7) -> dict:
    if len(deltas) < 2:
        return {"mean": None, "median": None, "ci95_low": None, "ci95_high": None}
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sample = [rng.choice(deltas) for _ in range(len(deltas))]
        means.append(statistics.mean(sample))
    means.sort()
    return {"mean": round(statistics.mean(deltas), 4), "median": round(statistics.median(deltas), 4),
            "ci95_low": round(means[int(0.025 * n_boot)], 4), "ci95_high": round(means[int(0.975 * n_boot)], 4)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    session_root = Path(args.session_root)
    corrected = Path("/home/hyan/Data/lyricalign/runs/research_transition_recovery_detector_20260808_corrected")
    manifest = {json.loads(l)["song_id"]: json.loads(l)
                for l in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines() if l.strip()}
    split = json.loads((corrected / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    role_songs = split["roles"][args.role]

    # row table: {(song, transition): [rows]}
    row_table: dict[tuple[str, str], list[dict]] = {}
    for pth in sorted((corrected / "02_transition").glob("*.jsonl")):
        m = SERIAL_PATTERN.match(pth.name)
        if not m:
            continue
        song, transition = m.group("song"), m.group("transition")
        if song not in role_songs:
            continue
        gt = load_gt(manifest[song])
        rows = []
        for line in pth.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.extend(committed_rows(json.loads(line), gt))
        row_table[(song, transition)] = rows
    full_rows: dict[str, list[dict]] = {}
    for song in role_songs:
        cache = match_full_song_cache(corrected, song, manifest[song])
        full_rows[song] = full_song_rows(cache, load_gt(manifest[song]))

    per_song: dict[str, dict] = {}
    for (song, t), rows in row_table.items():
        per_song[f"{song}::{t}"] = {"song_id": song, "transition": t,
                                    **row_summary(rows, len(load_gt(manifest[song])))}
    for song, rows in full_rows.items():
        per_song[f"{song}::full_song"] = {"song_id": song, "transition": "full_song",
                                          **row_summary(rows, len(load_gt(manifest[song])))}

    # pooled per transition
    pooled = []
    for t in TRANSITIONS:
        rows = [r for (s2, t2), rs in row_table.items() if t2 == t for r in rs]
        total = sum(len(load_gt(manifest[s])) for s in role_songs)
        entry = {"transition": t, "kind": "serial", "n_songs": len(role_songs),
                 **row_summary(rows, total), "row_level": rows}
        pooled.append(entry)
    all_full = [r for rs in full_rows.values() for r in rs]
    pooled.append({"transition": "full_song", "kind": "full_song", "n_songs": len(full_rows),
                   **row_summary(all_full, sum(len(load_gt(manifest[s])) for s in role_songs)),
                   "row_level": all_full})

    # invariant check
    for e in pooled:
        s = e
        assert s["committed"] == s["safe"] + s["grey"] + s["unsafe"] + s["no_gt"], e["transition"]
        if s["unsafe"] > 0:
            assert s["wrong_committed_250ms"] > 0, e["transition"]

    # selection v3（row-level 导出）
    candidates = [{
        "candidate": e["transition"], "kind": e["kind"],
        "primary_250ms_correct_coverage": e["correct_coverage_250ms"],
        "correct_250ms": e["correct_250ms"], "evaluated": e["evaluated"], "total": e["total"],
        "wrong_committed_250ms": e["wrong_committed_250ms"],
    } for e in pooled]
    product = max(candidates, key=lambda c: (c["primary_250ms_correct_coverage"], c["correct_250ms"]))
    mechanism = max(candidates, key=lambda c: c["wrong_committed_250ms"])
    selection = {
        "schema_version": "authoritative_transition_selection_v3",
        "role": args.role, "scope": "development_selection", "derived_from_data": True,
        "primary_metric": "250ms correct coverage over ALL target units",
        "candidates": candidates,
        "product_candidate": product["candidate"],
        "mechanism_candidate": mechanism["candidate"],
        "rationale": {
            "product": f"highest 250ms correct coverage: {product['primary_250ms_correct_coverage']:.4f}",
            "mechanism": f"largest wrong-committed at 250ms: {mechanism['wrong_committed_250ms']}",
        },
        "provenance": gt_provenance.synthetic_uniform_timeline_provenance(),
    }

    # paired comparison（T2−T1、serial−full_song）250ms correct coverage per-song bootstrap CI
    paired = {}
    for label, (a_t, b_t) in {"T2_minus_T1": ("T2_core_boundary_serial", "T1_direct_serial"),
                              "serial_minus_full": ("T2_core_boundary_serial", "full_song")}.items():
        deltas = []
        win = tie = loss = 0
        for song in role_songs:
            ca = per_song[f"{song}::{a_t}"]["correct_coverage_250ms"]
            cb = per_song[f"{song}::{b_t}"]["correct_coverage_250ms"]
            d = ca - cb
            deltas.append(d)
            if d > 1e-6:
                win += 1
            elif d < -1e-6:
                loss += 1
            else:
                tie += 1
        paired[label] = {"a": a_t, "b": b_t, "win": win, "tie": tie, "loss": loss,
                         **bootstrap_ci(deltas)}

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    gt_provenance.warn_synthetic_gt()
    paired_with_pv = dict(paired)
    paired_with_pv["provenance"] = gt_provenance.synthetic_uniform_timeline_provenance()
    (out_dir / "REAGGREGATE_v3_model_selection.json").write_text(json.dumps({
        "schema_version": "reaggregate_v3", "per_song": per_song, "pooled": [
            {k: v for k, v in e.items() if k != "row_level"} for e in pooled],
        "paired_by_song": paired,
        "provenance": gt_provenance.synthetic_uniform_timeline_provenance(),
    }, ensure_ascii=False, indent=2))
    (out_dir / "AUTHORITATIVE_TRANSITION_SELECTION_v3.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2))
    (out_dir / "TRANSITION_PAIRED_BY_SONG.json").write_text(
        json.dumps(paired_with_pv, ensure_ascii=False, indent=2))
    print(json.dumps({
        "selection_v3": {"product": selection["product_candidate"],
                         "mechanism": selection["mechanism_candidate"]},
        "wrong_committed": {c["candidate"]: c["wrong_committed_250ms"] for c in candidates},
        "paired": paired,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
