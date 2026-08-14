#!/usr/bin/env python3
"""WP9 — E6 recovery-basin atlas (summary of already-produced evidence).

Collapses every frozen region's recoverability across the E1-E4 mechanisms
(multi-iteration / fine split / audio recrop / coarse->fine) plus E5 selector
bookkeeping into one ``recovery_atlas_v1`` row, and classifies each region into
the 6-way taxonomy (once-realign / iterative / split-only / recrop /
coarse->fine / still-unrecoverable).

Pure CPU. GT is used ONLY for the evaluator-side baseline-error bucket and only
when supplied (``--gt`` json {canonical_unit_id:{start_sec,end_sec}} or each
region's ``region.gt_units``). No-GT regions keep detector-side fields and are
classified ``still-unrecoverable`` (GT firewall: no fabricated baseline bucket).

Outputs (under <out-root>):
   01_atlas/ATLAS.jsonl          recovery_atlas_v1 rows (one per region)
   02_summary/ATLAS_SUMMARY.json class counts + representative rows
   06_runtime/RUN_STATE.json     resume state
   FINAL_ATLAS.json              summary (alias readable by orchestrators)

Usage:
  PYTHONPATH=src python scripts/unit_realign/run_recovery_atlas.py \
      --regions <REGION_POOL.jsonl> --evidence-root <runs/E1..E4> \
      --outcomes-root <runs/WP outcomes> --out-root <run> \
      [--gt <GT.json>] [--smoke]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.recovery_atlas import (  # noqa: E402
    ATLAS_SCHEMA, CLASSES, build_atlas_rows, CLASS_UNRECOVERABLE,
)

_STATE_SCHEMA = "unit_realign_run_state_v2"
_STATE_PATH = Path("06_runtime") / "RUN_STATE.json"
_ATLAS_PATH = Path("01_atlas") / "ATLAS.jsonl"
_SUMMARY_PATH = Path("02_summary") / "ATLAS_SUMMARY.json"
_FINAL_PATH = Path("FINAL_ATLAS.json")

# Evidence/outcome sub-path markers to glob under evidence-root / outcomes-root.
_EVIDENCE_GLOBS = ("**/*.jsonl", "**/*.json")
_EXCLUDE_PARTS = ("RUN_STATE.json", "ATLAS.jsonl", "FINAL_", "REQUESTS.jsonl")


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not parse {path}: {exc}", file=sys.stderr)
        return []


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _write_jsonl(path: Path, rows) -> None:
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    _atomic_write(path, payload)


def _write_json(path: Path, value) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _collect_rows(root: Path) -> list[dict]:
    """Greedily load / collapse evidence+outcome rows under a run root."""
    rows: list[dict] = []
    if not root.exists():
        return rows
    for pattern in _EVIDENCE_GLOBS:
        for f in sorted(root.glob(pattern)):
            name = f.name
            if name.endswith(("_SUMMARY.json",)) or any(name.endswith(s) for s in ()) is None:
                pass
            if any(x in str(f).replace("\\", "/") for x in _EXCLUDE_PARTS):
                continue
            data = f.read_text(encoding="utf-8")
            if f.suffix == ".jsonl":
                rows.extend(_read_jsonl(f))
            else:
                try:
                    obj = json.loads(data)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(obj, list):
                    rows.extend(obj)
                elif isinstance(obj, dict):
                    # aggregate dicts may carry a nested list of region rows.
                    for lstkey in ("aggregates", "region_outcomes", "rows", "trajectory"):
                        val = obj.get(lstkey)
                        if isinstance(val, list):
                            rows.extend(val)
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--regions", required=True, help="REGION_POOL.jsonl")
    p.add_argument("--evidence-root", action="append", default=[],
                   help="run root(s) holding E1-E4 forward evidence")
    p.add_argument("--outcomes-root", action="append", default=[],
                   help="run root(s) holding per-WP outcome JSONL/JSON")
    p.add_argument("--gt", default=None, help="optional GT table json")
    p.add_argument("--out-root", required=True)
    p.add_argument("--smoke", action="store_true",
                   help="flag (accepted; atlas has no model forward in any mode)")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.out_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "01_atlas").mkdir(parents=True, exist_ok=True)
    (root / "02_summary").mkdir(parents=True, exist_ok=True)

    regions = _read_jsonl(Path(args.regions))
    evidence = [r for base in args.evidence_root for r in _collect_rows(Path(base))]
    outcomes = [r for base in args.outcomes_root for r in _collect_rows(Path(base))]

    gt = None
    if args.gt:
        gt = json.loads(Path(args.gt).read_text(encoding="utf-8"))

    rows = build_atlas_rows(regions, evidence, outcomes, gt=gt)

    # ---- summary ----
    counts = {c: 0 for c in CLASSES}
    for r in rows:
        keys = r.get("atlas_class") or CLASS_UNRECOVERABLE
        if isinstance(keys, str):
            keys = [keys]
        for k in keys:
            counts[k] = counts.get(k, 0) + 1
    n_gt = sum(1 for r in rows if r.get("baseline_present_gt"))
    representative = {
        c: (r.get("region_id") for r in rows if r.get("atlas_class") == c)
        for c in CLASSES
    }
    summary = {
        "schema": "recovery_atlas_summary_v1",
        "n_regions": len(rows),
        "n_gt_present": n_gt,
        "class_counts": counts,
        "representative_region_by_class": {c: next(iter(rep), None)
                                           for c, rep in representative.items()},
        "executor": "smoke" if args.smoke else "cpu_atlas",
    }
    _write_jsonl(root / _ATLAS_PATH, rows)
    _write_json(root / _SUMMARY_PATH, summary)
    _write_json(root / _FINAL_PATH, {
        "schema": "recovery_atlas_final_v1", **{k: summary[k] for k in
                 ("n_regions", "n_gt_present", "class_counts")},
        "atlas": str(root / _ATLAS_PATH)})
    _write_json(root / _STATE_PATH, {
        "schema": _STATE_SCHEMA,
        "completed_identities": [str(r.get("region_id")) for r in rows],
        "queued_identities": [], "planned_identities": [],
        "failed_identities": [], "not_constructible_identities": []})

    print(json.dumps({"schema": ATLAS_SCHEMA, "n_regions": len(rows),
                      "class_counts": counts, "n_gt_present": n_gt,
                      "atlas": str(root / _ATLAS_PATH),
                      "summary": str(root / _SUMMARY_PATH),
                      "final": str(root / _FINAL_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
