#!/usr/bin/env python3
"""Task A: Transition 离线重汇总（纯 CPU，不重跑模型）。

利用已完成 corrected forward 的产物生成统一、可比较的 transition summary：

- serial（T1/T2/T3）：只评价每个 record 当窗新 committed ids
  （state_before.committed_end_exclusive .. decision.committed_end_exclusive），
  行时间取自 evidence_summary.raw_global_rows（original_global_start_sec 优先，
  缺省回退 fixed_global_start_sec）；
- full-song：评价全部 canonical ids，行时间取自 cache/full_song/<hash>.json 的
  fixed_global_start_sec；cache 与 manifest 按 identity.alignment_units 文本前缀
  唯一匹配，任一 song 匹配不到/匹配多个/行数不符则命令失败，不静默 fallback；
- 输出：REAGGREGATE_<role>.json + AUTHORITATIVE_TRANSITION_SELECTION_v2.json。

指标口径（10 §1 冻结）：
- Safe: err<=100ms；Grey: 100<err<=250ms；Unsafe: err>250ms；
- primary product comparison = 250ms correct coverage（分母=全部 target units）；
- committed-only rate 只作辅助；legacy_320ms 仅兼容列，不参与 selection。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOLERANCES_MS = (100, 250, 500, 1000)
SERIAL_PATTERN = re.compile(r"^(?P<song>.+)__(?P<transition>T[123]_direct_serial|T[123]_core_boundary_serial|T[123]_stable_boundary_serial)\.jsonl$")
OUTPUT_DIR_NAME = "10_followup"
OUTPUT_SUBDIR = "transition_v2"
SELECTION_FILENAME = "AUTHORITATIVE_TRANSITION_SELECTION_v2.json"


def load_gt(row: dict) -> dict[int, dict]:
    return {
        int(u["canonical_unit_id"]): {
            "start_sec": u["start_sec"],
            "end_sec": u["end_sec"],
            "text": u["text"],
        }
        for u in row["canonical_units"]
    }


def manifest_texts(row: dict) -> list[str]:
    return [u["text"] for u in row["canonical_units"]]


def committed_rows_for(record: dict, gt: dict[int, dict]) -> list[dict]:
    """本窗新 committed rows：state_before/decision 区间 + evidence raw_global_rows。"""
    if record.get("skipped"):
        return []
    raw = list(record["evidence_summary"]["raw_global_rows"])
    before = int(record["state_before"]["committed_end_exclusive"])
    after = int(record["decision"]["committed_end_exclusive"])
    new_ids = set(range(before, after))
    out = []
    for r in raw:
        cid = int(r["global_character_index"])
        if cid not in new_ids:
            continue
        pred = None
        for k in ("original_global_start_sec", "fixed_global_start_sec"):
            if r.get(k) is not None:
                pred = float(r[k])
                break
        g = gt.get(cid)
        err = abs(pred - g["start_sec"]) if (pred is not None and g) else None
        out.append({"canonical_id": cid, "pred_start_sec": pred, "abs_error_sec": err,
                    "gt_start_sec": g["start_sec"] if g else None})
    return out


def bucket_stats(rows: list[dict], total_units: int) -> dict:
    """由行级 abs error 汇总多容差计数/率 + Safe/Grey/Unsafe + legacy_320ms。"""
    counts = {ms: 0 for ms in TOLERANCES_MS}
    safe = grey = unsafe = no_gt = 0
    for r in rows:
        err = r["abs_error_sec"]
        if err is None:
            no_gt += 1
            unsafe += 1
            continue
        if err <= 0.1:
            safe += 1
        elif err <= 0.25:
            grey += 1
        else:
            unsafe += 1
        for ms in TOLERANCES_MS:
            if err <= ms / 1000.0:
                counts[ms] += 1
    legacy_320 = sum(1 for r in rows if r["abs_error_sec"] is not None and r["abs_error_sec"] <= 0.32)
    evaluated = len(rows)
    out = {
        "evaluated": evaluated,
        "total": total_units,
        "committed_coverage": evaluated / total_units if total_units else 0.0,
        "safe": safe,
        "grey": grey,
        "unsafe": unsafe,
        "no_gt": no_gt,
        "legacy_320ms_count": legacy_320,
        "legacy_320ms_committed_rate": legacy_320 / evaluated if evaluated else 0.0,
    }
    for ms in TOLERANCES_MS:
        out[f"correct_{ms}ms"] = counts[ms]
        out[f"correct_rate_{ms}ms_committed"] = counts[ms] / evaluated if evaluated else 0.0
        out[f"correct_coverage_{ms}ms"] = counts[ms] / total_units if total_units else 0.0
    return out


def wrong_committed(rows: list[dict]) -> int:
    return sum(1 for r in rows if r["abs_error_sec"] is None or r["abs_error_sec"] > 0.25)


def load_serial_files(session_root: Path, song_ids: set[str]) -> list[tuple[str, str, Path]]:
    files = []
    for p in sorted((session_root / "02_transition").glob("*.jsonl")):
        m = SERIAL_PATTERN.match(p.name)
        if not m:
            continue
        song, transition = m.group("song"), m.group("transition")
        if song not in song_ids:
            continue
        files.append((song, transition, p))
    return files


def match_full_song_cache(session_root: Path, song_id: str, row: dict) -> dict:
    """按 identity.alignment_units 文本前缀匹配唯一 cache；不唯一或行数不符即失败。"""
    texts = manifest_texts(row)
    hits = []
    for p in sorted((session_root / "cache" / "full_song").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        units = [str(u) for u in d["identity"]["alignment_units"]]
        n = min(len(units), len(texts))
        if n and units[:n] == texts[:n]:
            hits.append((p, d))
    if len(hits) != 1:
        raise RuntimeError(f"full-song cache match failed for '{song_id}': {len(hits)} hits (need exactly 1)")
    path, d = hits[0]
    if len(d["rows"]) != len(texts):
        raise RuntimeError(
            f"full-song '{song_id}' rows={len(d['rows'])} != manifest units={len(texts)} ({path.name})"
        )
    return d


def evaluate_full_song(cache: dict, gt: dict[int, dict]) -> list[dict]:
    rows = []
    for r in sorted(cache["rows"], key=lambda x: int(x["global_character_index"])):
        cid = int(r["global_character_index"])
        g = gt.get(cid)
        pred = r.get("fixed_global_start_sec")
        err = abs(pred - g["start_sec"]) if (pred is not None and g) else None
        rows.append({"canonical_id": cid, "pred_start_sec": pred, "abs_error_sec": err,
                     "gt_start_sec": g["start_sec"] if g else None})
    return rows


def format_rate(x: float) -> str:
    return f"{x:.3f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session-root", required=True)
    ap.add_argument("--timeline-manifest", required=True)
    ap.add_argument("--role", default="model_selection")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    session_root = Path(args.session_root)
    out_path = Path(args.out)
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    role_songs = split["roles"][args.role]
    manifest_rows = {}
    for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            manifest_rows[r["song_id"]] = r

    # ---- serial T1/T2/T3 ----
    serial_rows: dict[tuple[str, str], list[dict]] = {}
    for song, transition, p in load_serial_files(session_root, set(role_songs)):
        gt = load_gt(manifest_rows[song])
        rows: list[dict] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.extend(committed_rows_for(json.loads(line), gt))
        serial_rows[(song, transition)] = rows

    songs_out, transitions_out = {}, {}
    serial_files_used = []
    for (song, transition), rows in sorted(serial_rows.items()):
        gt = load_gt(manifest_rows[song])
        songs_out[f"{song}::{transition}"] = {
            "song_id": song, "transition": transition, "kind": "serial",
            **bucket_stats(rows, len(gt)),
        }
        t = transitions_out.setdefault(transition, {"transition": transition, "kind": "serial",
                                                    "row_level": []})
        t["row_level"].extend(rows)
        serial_files_used.append(f"{song}__{transition}_serial.jsonl")

    # ---- full-song ----
    full_rows: dict[str, list[dict]] = {}
    for song in role_songs:
        if song not in manifest_rows:
            raise RuntimeError(f"song '{song}' not in timeline manifest")
        gt = load_gt(manifest_rows[song])
        cache = match_full_song_cache(session_root, song, manifest_rows[song])
        rows = evaluate_full_song(cache, gt)
        full_rows[song] = rows
        songs_out[f"{song}::full_song"] = {
            "song_id": song, "transition": "full_song", "kind": "full_song",
            **bucket_stats(rows, len(gt)),
        }

    # ---- pooled per transition ----
    pooled = []
    for transition in ("T1_direct_serial", "T2_core_boundary_serial", "T3_stable_boundary_serial"):
        if transition in transitions_out:
            rows = transitions_out[transition]["row_level"]
            total = sum(len(load_gt(manifest_rows[s])) for s, _ in serial_rows if s ==
                        next(s for (s2, t2) in serial_rows if t2 == transition) for s in [s])
        else:
            total = 0
            rows = []
        if transition in transitions_out:
            total = sum(len(load_gt(manifest_rows[song])) for (song, t2) in serial_rows if t2 == transition)
            rows = transitions_out[transition]["row_level"]
            pooled.append({"transition": transition, "kind": "serial", "n_songs": len({s for (s, t2) in serial_rows if t2 == transition}),
                           **bucket_stats(rows, total)})
    full_total = sum(len(load_gt(manifest_rows[s])) for s in full_rows)
    all_full = [r for rs in full_rows.values() for r in rs]
    pooled.append({"transition": "full_song", "kind": "full_song", "n_songs": len(full_rows),
                   **bucket_stats(all_full, full_total)})

    # ---- cross-check vs FORMAL ----
    formal_path = session_root / "02_transition" / f"FORMAL_{args.role}.json"
    crosscheck = []
    if formal_path.is_file():
        formal = json.loads(formal_path.read_text(encoding="utf-8"))
        for e in formal:
            key = f"{e['song_id']}::{e['transition']}"
            mine = songs_out.get(key)
            if mine is None:
                continue
            diffs = {}
            for ms in TOLERANCES_MS:
                diff = abs(mine[f"correct_rate_{ms}ms_committed"] - e["multi_tolerance"][f"correct_rate_{ms}ms"])
                if diff > 1e-9:
                    diffs[f"correct_rate_{ms}ms"] = diff
            if abs(mine["legacy_320ms_committed_rate"] - e["multi_tolerance"]["legacy_320ms"]) > 1e-9:
                diffs["legacy_320ms"] = mine["legacy_320ms_committed_rate"] - e["multi_tolerance"]["legacy_320ms"]
            if mine["evaluated"] != e["committed"]:
                diffs["committed"] = (mine["evaluated"], e["committed"])
            crosscheck.append({"song_id": e["song_id"], "transition": e["transition"],
                               "consistent": not diffs, "diffs": diffs})
    else:
        crosscheck.append({"note": f"FORMAL_{args.role}.json not found; cross-check skipped"})

    # ---- authoritative selection（由数据导出，不硬编码）----
    candidates = []
    for entry in pooled:
        candidates.append({
            "candidate": entry["transition"], "kind": entry["kind"],
            "primary_250ms_correct_coverage": entry["correct_coverage_250ms"],
            "correct_250ms": entry["correct_250ms"],
            "evaluated": entry["evaluated"],
            "total": entry["total"],
            "wrong_committed_250ms": wrong_committed(entry["row_level"] if "row_level" in entry else
                                                     ([r for r in all_full] if entry["transition"] == "full_song" else [])),
        })
    product_candidate = max(candidates, key=lambda c: (c["primary_250ms_correct_coverage"], c["correct_250ms"]))
    mechanism_candidate = max(candidates, key=lambda c: c["wrong_committed_250ms"])
    selection = {
        "schema_version": "authoritative_transition_selection_v2",
        "role": args.role,
        "scope": "development_selection",
        "derived_from_data": True,
        "primary_metric": "250ms correct coverage over ALL target units",
        "candidates": candidates,
        "product_candidate": product_candidate["candidate"],
        "mechanism_candidate": mechanism_candidate["candidate"],
        "rationale": {
            "product": f"highest 250ms correct coverage (denominator=total target units): "
                       f"{format_rate(product_candidate['primary_250ms_correct_coverage'])}",
            "mechanism": f"largest wrong-committed count at 250ms: "
                         f"{mechanism_candidate['wrong_committed_250ms']}",
        },
    }

    # ---- write outputs ----
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "transition_reaggregate_v2",
        "role": args.role,
        "scope": "development_selection",
        "session_root": str(session_root),
        "timeline_manifest": str(Path(args.timeline_manifest)),
        "serial_files_used": serial_files_used,
        "songs": songs_out,
        "transitions_pooled": pooled,
        "crosscheck_vs_formal": crosscheck,
        "full_song_matches": {s: f"{len(load_gt(manifest_rows[s]))} units" for s in full_rows},
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    selection_path = out_dir / SELECTION_FILENAME
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2), "utf-8")

    print(f"wrote {out_path}")
    print(f"wrote {selection_path}")
    print(f"full-song matched songs: {len(full_rows)} (unique each)")
    print("\n250ms primary table (correct coverage, denominator=all target units):")
    print(f"{'candidate':<26} {'evaluated':>9} {'total':>6} {'correct250':>10} {'cov250':>7} {'rate250c':>8} {'safe':>5} {'grey':>5} {'unsafe':>6}")
    for entry in pooled:
        s = entry
        print(f"{entry['transition']:<26} {s['evaluated']:>9} {s['total']:>6} {s['correct_250ms']:>10} "
              f"{format_rate(s['correct_coverage_250ms']):>7} {format_rate(s['correct_rate_250ms_committed']):>8} "
              f"{s['safe']:>5} {s['grey']:>5} {s['unsafe']:>6}")
    bad = [c for c in crosscheck if c.get("consistent") is False]
    print(f"\ncrosscheck vs FORMAL: {len(crosscheck)} entries, {len(bad)} inconsistent")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
