#!/usr/bin/env python3
"""19 §6 交付物三件生成（总体 review backlog #5）：PRECHECK_DETECTOR_V2.json /
HIDDEN_EXTRACTION_AUDIT.json / REQUEST_IDENTITY_AUDIT.json。

全部基于真实数据统计（只读，不伪造数字）。输出到 --out-dir（默认 run-root 顶层）。
schema：precheck_detector_v2_v1 / hidden_extraction_audit_v1 / request_identity_audit_v1。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

DELIVERABLES_19_6 = [
    "PRECHECK_DETECTOR_V2.json", "SOURCE_SONG_SPLIT.json", "GT_LABEL_AUDIT.json",
    "HIDDEN_EXTRACTION_AUDIT.json", "REQUEST_IDENTITY_AUDIT.json",
    "ANOMALY_MANIFEST.jsonl", "MULTIVIEW_MANIFEST.jsonl", "SIGNAL_ATLAS.json",
    "FEATURE_SCHEMA.json", "MODEL_SELECTION.json", "FROZEN_OPERATING_POINTS.json",
    "DETECTOR_V2_COVERAGE_MATRIX.json", "M4_SONG_HELDOUT.json", "FAMILY_LOO.json",
    "M4_TO_MIR_BY_FAMILY.json", "SERIAL_CLOSED_LOOP.json", "RUNTIME_BUDGET.json",
    "FAILURES.jsonl", "AUTO_FINDINGS_DRAFT.md",
]

_SEARCH_DIRS = ["", "preflight", "run2", "run1", "manifests", "phaseB_final",
                "phaseC_m4", "phaseC_mir", "stress2_run", "serial_run", "timeline_v4",
                "run2/evidence_v2", "run1/evidence_v2", "run2/manifests"]


def _atomic_write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _find(root: Path, name: str) -> str | None:
    for d in _SEARCH_DIRS:
        p = root / d / name
        if p.is_file():
            return str(p)
    return None


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def build_precheck(root: Path) -> dict:
    items = []
    for name in DELIVERABLES_19_6:
        p = _find(root, name)
        items.append({"item": name, "exists": p is not None,
                      "path": p, "note": "OK" if p else "missing"})
    labels_path = root / "run2" / "LABELS.jsonl"
    split = {"checked": False, "note": ""}
    if labels_path.is_file():
        songs: dict[str, set[str]] = {}
        for row in _load_jsonl(labels_path):
            songs.setdefault(row.get("split"), set()).add(row.get("song_id"))
        tr, va, te = songs.get("train"), songs.get("validation"), songs.get("test")
        ok = (tr and va and len(tr) == 20 and len(va) == 5 and len(te) == 5
              and not (tr & va) and not (tr & te) and not (va & te))
        split = {"checked": True, "train_songs": len(tr or {}),
                 "validation_songs": len(va or {}), "test_songs": len(te or {}),
                 "disjoint": ok, "note": "20/5/5 song-grouped disjoint" if ok else "MISMATCH"}
    budget = {"checked": False, "note": ""}
    rp = root / "RUNTIME_BUDGET.json"
    if rp.is_file():
        b = json.loads(rp.read_text(encoding="utf-8"))
        total = b.get("total_est_hours")
        fb = b.get("formal_budget_hours") or {}
        cap = fb.get("hard_cap") if isinstance(fb, dict) else fb
        ok = bool(b.get("budget_ok")) and (total is None or float(total) <= float(cap or 1e9))
        budget = {"checked": True, "total_est_hours": total,
                  "formal_budget_hours": fb,
                  "budget_ok": ok}
    return {"schema": "precheck_detector_v2_v1",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_root": str(root), "deliverables": items,
            "checks": {"split_song_grouped": split, "runtime_budget": budget},
            "summary": {"deliverables_ok": sum(1 for i in items if i["exists"]),
                        "deliverables_total": len(items),
                        "split_ok": split.get("disjoint"),
                        "budget_ok": budget.get("budget_ok")}}


def build_hidden_audit(root: Path, max_rows: int = 20000) -> dict:
    ev_dir = root / "run2" / "evidence_v2"
    files = sorted(ev_dir.glob("sha256:*.jsonl")) if ev_dir.is_dir() else []
    total = 0
    n_hidden_avail = 0
    n_with_schema = 0
    n_checked = 0
    hidden_starts = 0
    hidden_ends = 0
    rng = random.Random(0)
    sampled = rng.sample(files, min(len(files), 200)) if files else []
    for f in sampled:
        try:
            arr = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(arr, list):
            continue
        for row in arr:
            if not isinstance(row, dict) or "canonical_unit_id" not in row:
                continue  # header dict（无 canonical_unit_id）
            if n_checked >= max_rows:
                break
            n_checked += 1
            total += 1
            h = row.get("hidden") or {}
            if h.get("available"):
                n_hidden_avail += 1
                if h.get("start"):
                    hidden_starts += 1
                if h.get("end"):
                    hidden_ends += 1
            if h.get("schema"):
                n_with_schema += 1
        if n_checked >= max_rows:
            break
    return {"schema": "hidden_extraction_audit_v1",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "evidence_dir": str(ev_dir), "max_rows": max_rows,
            "rows_checked": n_checked,
            "hidden_available": n_hidden_avail,
            "hidden_available_rate": (n_hidden_avail / n_checked) if n_checked else None,
            "hidden_with_schema": n_with_schema,
            "hidden_start_nonempty": hidden_starts,
            "hidden_end_nonempty": hidden_ends,
            "note": ("hidden available=False 为 blocked 状态（SIGNAL_ATLAS counts 口径："
                     "blocked_hidden_rows=134538/134538，全量参照）；本次为抽样统计"
                     "（files_scanned/rows_checked），换 run-root 时以本次抽样为准"),
            "files_scanned": len(sampled)}


def build_identity_audit(root: Path) -> dict:
    labels_path = root / "run2" / "LABELS.jsonl"
    lab_rows = _load_jsonl(labels_path) if labels_path.is_file() else []
    rid_counts: dict[str, int] = {}
    quadruple = set()
    dup_quadruple = 0
    for r in lab_rows:
        rid = r.get("request_identity")
        rid_counts[rid] = rid_counts.get(rid, 0) + 1
        key = (rid, r.get("view_id"), r.get("canonical_unit_id"), r.get("target"))
        if key in quadruple:
            dup_quadruple += 1
        quadruple.add(key)

    run_manifest = root / "run2" / "manifests" / "ANOMALY_MANIFEST.jsonl"
    run_info: dict = {"rows": 0, "unique_request_id": 0,
                      "unique_baseline_request_identity": 0}
    if run_manifest.is_file():
        m_rows = _load_jsonl(run_manifest)
        run_info = {"rows": len(m_rows),
                    "unique_request_id": len({r.get("request_id") for r in m_rows
                                              if r.get("request_id")}),
                    "unique_baseline_request_identity": len(
                        {r.get("baseline_request_identity") for r in m_rows
                         if r.get("baseline_request_identity")})}

    build_manifest = root / "manifests" / "ANOMALY_MANIFEST.jsonl"
    build_logical: list[str] = []
    if build_manifest.is_file():
        build_logical = [str(r.get("request_id")) for r in _load_jsonl(build_manifest)
                         if r.get("request_id")]

    ev_dir = root / "run2" / "evidence_v2"
    ev_files = sorted(ev_dir.glob("sha256:*.jsonl")) if ev_dir.is_dir() else []
    ev_rids = {f.stem for f in ev_files}
    lab_rids = set(rid_counts)
    return {"schema": "request_identity_audit_v1",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "labels": {"rows": len(lab_rows),
                       "unique_request_identity": len(lab_rids),
                       "rows_per_request_identity": {
                           "min": min(rid_counts.values()) if rid_counts else 0,
                           "max": max(rid_counts.values()) if rid_counts else 0},
                       "dup_quadruple_rid_view_unit_target": dup_quadruple},
            "evidence_files": {"count": len(ev_files),
                               "sha256_stems_matched_in_labels":
                                   len(ev_rids & lab_rids),
                               "sha256_stems_unmatched_in_labels":
                                   len(ev_rids - lab_rids)},
            "run_manifest": run_info,
            "build_manifest": {"rows": len(build_logical),
                               "note": ("构建/运行清单的 request_id 为逻辑 id（mutation 展开"
                                        "前），LABELS/evidence 的 request_identity 为请求内容"
                                        "哈希（sha256:...，与 evidence 文件名一致）——两层级"
                                        "不直接比对，仅登记")},
            "consistency": {
                "labels_vs_evidence_files": ("OK" if lab_rids and lab_rids == ev_rids
                                             else "MISMATCH"),
                "dup_quadruple": "OK" if dup_quadruple == 0 else "MISMATCH"}}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True, type=Path)
    p.add_argument("--out-dir", type=Path, default=None)
    p.add_argument("--max-rows", type=int, default=20000)
    a = p.parse_args(argv)
    root = a.run_root
    out_dir = a.out_dir or root
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "PRECHECK_DETECTOR_V2.json": build_precheck(root),
        "HIDDEN_EXTRACTION_AUDIT.json": build_hidden_audit(root, a.max_rows),
        "REQUEST_IDENTITY_AUDIT.json": build_identity_audit(root),
    }
    for name, obj in results.items():
        _atomic_write(out_dir / name, obj)
        print(f"wrote {out_dir / name}")
    print(json.dumps({"ok": True,
                      "summary": {k: v.get("summary", v.get("consistency"))
                                  for k, v in results.items()}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
