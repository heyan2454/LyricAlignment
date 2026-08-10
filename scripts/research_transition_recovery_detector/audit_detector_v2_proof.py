#!/usr/bin/env python3
"""Detector V2 post-42522c3 label proof gate (Stage 3C, Doc 20).

Verifies each run's LABEL_SUMMARY points to a post-fix label artifact whose rows
use accepted pinyin statuses, segment offsets / source id-index mapping, and an
explicit query set.  A failed proof retires the model/threshold and flags the
run for minimal relabel -> frozen-evaluation rerun, preventing the separate G
defect (pre-42522c3 local-to-global pinyin projection) from being misreported
as U contamination.

Checks per run (conservative; missing evidence always fails):
  1. LABEL_SUMMARY.json exists and references a label artifact
     (labels_file / labels_sha / provenance / gt_label_audit).  Absent -> FAIL.
  2. Label rows prove post-fix mapping: audit.used_keys.start_key must be on the
     global clock (raw_global_start_sec / official_global_start_sec) AND rows or
     schema must reference source_segment_id/source_unit_index/segment_offsets/
     global_start_sec or a projection mapping schema.  Local keys -> G defect.
  3. Accepted pinyin statuses: no review_required / uniform mentions.
  4. Explicit query set under manifests/ (or RUN_MANIFEST.json manifest path).
  5. Per-run verdict {run, pass, failures, label_sha, labels_file, query_set_file}.

Aggregate mode (--run-root = parent dir) scans every subdir that looks like a
detector run and writes DETECTOR_V2_PROOF_GATE.json (one object per run plus
retained/retired summary) and DETECTOR_V2_RETIRE_LIST.json (failed runs).

Pure CPU / stdlib only.  Expected behavior: most historical runs fail on
missing provenance; that is correct -- the gate is conservative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

LABEL_MIN_COMMIT_DEFAULT = "42522c3"
GLOBAL_START_KEYS = {"raw_global_start_sec", "official_global_start_sec"}
QUERY_MANIFEST_CANDIDATES = (
    "REQUESTS.jsonl",
    "QUERY_MANIFEST.jsonl",
    "MULTIVIEW_MANIFEST.jsonl",
    "ANOMALY_MANIFEST.jsonl",
)
PROVENANCE_KEYS = ("labels_file", "labels_path", "label_artifact")
PROVENANCE_SHA_KEYS = ("labels_sha", "label_sha", "sha256", "sha")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_labels_file(summary: dict, run_root: Path) -> Path | None:
    labels_file = None
    provenance = summary.get("provenance")
    if isinstance(provenance, dict):
        for key in PROVENANCE_KEYS:
            if provenance.get(key):
                labels_file = provenance[key]
                break
    if not labels_file:
        for key in PROVENANCE_KEYS:
            if summary.get(key):
                labels_file = summary[key]
                break
    if not labels_file:
        return None
    cand = Path(labels_file)
    if not cand.is_absolute():
        cand = run_root / cand
    if not cand.is_file():
        cand = run_root / cand.name
    return cand if cand.is_file() else None


def _summary_sha(summary: dict) -> str | None:
    for key in PROVENANCE_SHA_KEYS:
        value = summary.get(key)
        if value:
            return str(value)
    provenance = summary.get("provenance")
    if isinstance(provenance, dict):
        for key in PROVENANCE_SHA_KEYS:
            value = provenance.get(key)
            if value:
                return str(value)
    return None


def _scan_labels(path: Path, max_rows: int = 2000) -> tuple[str, int, set[str], dict[str, bool], bool, dict[str, bool]]:
    """Return (sha256 of raw lines, n_rows, start_keys seen, mapping flags,
    truncated, row_status).  Every row is parsed for start-key / status
    evidence; the max_rows cap is only a fail-closed safeguard flag."""
    digest = hashlib.sha256()
    start_keys: set[str] = set()
    mapping = {
        "source_segment_id": False,
        "source_unit_index": False,
        "segment_offsets": False,
        "global_start_sec": False,
    }
    row_status = {"review_required": False, "uniform_axis": False}
    n_rows = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            digest.update(line.encode("utf-8"))
            n_rows += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            start_key = row.get("audit", {}).get("used_keys", {}).get("start_key")
            if start_key:
                start_keys.add(start_key)
                if "global_start_sec" in start_key:
                    mapping["global_start_sec"] = True
            text = json.dumps(row, ensure_ascii=False)
            if "source_segment_id" in text:
                mapping["source_segment_id"] = True
            if "source_unit_index" in text:
                mapping["source_unit_index"] = True
            if "segment_offsets" in text:
                mapping["segment_offsets"] = True
            if "review_required" in text:
                row_status["review_required"] = True
            if "uniform" in text and "synthetic_uniform" not in text:
                row_status["uniform_axis"] = True
    return digest.hexdigest(), n_rows, start_keys, mapping, n_rows > max_rows, row_status


def audit_run(run_root: Path, label_min_commit: str = LABEL_MIN_COMMIT_DEFAULT) -> dict:
    verdict = {
        "run": run_root.name,
        "run_root": str(run_root),
        "pass": False,
        "failures": [],
        "label_sha": None,
        "labels_file": None,
        "query_set_file": None,
        "label_min_commit": label_min_commit,
        "label_commit": None,
        "n_label_rows": None,
    }
    row_status = {"review_required": False, "uniform_axis": False}
    run_root = Path(run_root)
    summary_path = run_root / "LABEL_SUMMARY.json"
    labels_path = run_root / "LABELS.jsonl"
    manifest_dir = run_root / "manifests"

    # 1. summary + provenance
    if not summary_path.is_file():
        verdict["failures"].append("missing_label_summary")
        return verdict
    try:
        summary = _read_json(summary_path)
    except (json.JSONDecodeError, OSError) as exc:
        verdict["failures"].append(f"label_summary_invalid:{exc}")
        return verdict

    labels_file = _resolve_labels_file(summary, run_root)
    label_sha = _summary_sha(summary)
    gt_label_audit = summary.get("gt_label_audit")

    has_provenance = bool(labels_file or label_sha or gt_label_audit)
    if not has_provenance:
        verdict["failures"].append("missing_provenance")
    elif gt_label_audit is None and not (labels_file and label_sha):
        verdict["failures"].append("gt_label_audit_null_no_provenance")

    if labels_file:
        verdict["labels_file"] = str(labels_file)
        labels_path = labels_file
    elif summary.get("labels_file"):
        verdict["labels_file"] = str(summary["labels_file"])
    if label_sha:
        verdict["label_sha"] = label_sha

    # 2. label rows: post-fix mapping / global clock
    if labels_path.is_file():
        digest, n_rows, start_keys, mapping, truncated, row_status = _scan_labels(labels_path)
        verdict["n_label_rows"] = n_rows
        if not verdict["label_sha"]:
            verdict["label_sha"] = digest
        schema = str(summary.get("schema_version") or "")
        projection_schema = "local_to_global" in schema or "segment_offsets" in schema

        if truncated:
            verdict["failures"].append("labels_scan_truncated")

        if start_keys and any("global" not in key for key in start_keys):
            verdict["failures"].append("g_defect_local_keys")

        mapping_evident = (
            projection_schema
            or mapping["source_segment_id"]
            or mapping["source_unit_index"]
            or mapping["segment_offsets"]
            or mapping["global_start_sec"]
        )
        if not mapping_evident:
            verdict["failures"].append("g_defect_no_projection")
    elif "missing_labels_file" not in [f.split(":")[0] for f in verdict["failures"]]:
        verdict["failures"].append("missing_labels_file")

    # 3. accepted pinyin statuses (summary text + row-level)
    audit_text = json.dumps(summary, ensure_ascii=False)
    if "review_required" in audit_text:
        verdict["failures"].append("pinyin_status_review_required")
    if "uniform" in audit_text and "synthetic_uniform" not in audit_text:
        verdict["failures"].append("pinyin_uniform_axis")
    if row_status["review_required"] or row_status["uniform_axis"]:
        verdict["failures"].append("labels_unaccepted_status")

    # 4. explicit query set + label commit from RUN_MANIFEST
    run_manifest = run_root / "RUN_MANIFEST.json"
    for name in QUERY_MANIFEST_CANDIDATES:
        candidate = manifest_dir / name
        if candidate.is_file():
            verdict["query_set_file"] = str(candidate)
            break
    if run_manifest.is_file():
        try:
            manifest = _read_json(run_manifest)
            if not verdict["query_set_file"]:
                path = manifest.get("manifest", {}).get("path")
                if path and Path(path).is_file():
                    verdict["query_set_file"] = path
            commit = manifest.get("label_commit") or manifest.get("code_identity", {}).get("git_commit")
            if commit:
                verdict["label_commit"] = str(commit)
        except (json.JSONDecodeError, OSError):
            pass
    if not verdict["query_set_file"]:
        verdict["failures"].append("missing_query_set")

    # 5. label commit floor: accepted GT must come from the fixed labeler
    if verdict["label_commit"] is not None and verdict["label_commit"] < label_min_commit:
        verdict["failures"].append("label_pre_min_commit")

    verdict["pass"] = not verdict["failures"]
    return verdict


def _run_candidates(root: Path) -> list[Path]:
    markers = ("LABEL_SUMMARY.json", "LABELS.jsonl", "RUN_MANIFEST.json")
    return [
        sub
        for sub in sorted(root.iterdir())
        if sub.is_dir() and not sub.name.startswith(".") and any((sub / marker).is_file() for marker in markers)
    ]


def audit_run_root(run_root: Path, label_min_commit: str = LABEL_MIN_COMMIT_DEFAULT) -> tuple[list[dict], dict, list[dict]]:
    run_root = Path(run_root)
    if (run_root / "LABEL_SUMMARY.json").is_file():
        verdicts = [audit_run(run_root, label_min_commit)]
    else:
        verdicts = [audit_run(sub, label_min_commit) for sub in _run_candidates(run_root)]
    retired = [v for v in verdicts if not v["pass"]]
    retained = [v for v in verdicts if v["pass"]]
    summary = {
        "total_runs": len(verdicts),
        "retained": len(retained),
        "retired": len(retired),
        "retained_runs": [v["run"] for v in retained],
        "retired_runs": [v["run"] for v in retired],
    }
    return verdicts, summary, retired


def write_outputs(out_dir: Path, verdicts: list[dict], summary: dict, retired: list[dict], label_min_commit: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    gate = {
        "schema_version": "detector_v2_proof_gate_v1",
        "label_min_commit": label_min_commit,
        "runs": verdicts,
        "summary": summary,
    }
    (out_dir / "DETECTOR_V2_PROOF_GATE.json").write_text(
        json.dumps(gate, ensure_ascii=False, indent=2), "utf-8"
    )
    retire = {
        "schema_version": "detector_v2_retire_list_v1",
        "label_min_commit": label_min_commit,
        "note": "A retired run/model/threshold must not be reused as a scientific result; "
                "schedule minimal relabel -> frozen-evaluation rerun.",
        "retired": [
            {
                "run": v["run"],
                "run_root": v["run_root"],
                "failures": v["failures"],
                "labels_file": v["labels_file"],
                "label_sha": v["label_sha"],
                "query_set_file": v["query_set_file"],
            }
            for v in retired
        ],
    }
    (out_dir / "DETECTOR_V2_RETIRE_LIST.json").write_text(
        json.dumps(retire, ensure_ascii=False, indent=2), "utf-8"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True, help="Detector run dir (LABEL_SUMMARY.json) or parent dir for aggregate scan")
    p.add_argument("--label-min-commit", default=LABEL_MIN_COMMIT_DEFAULT, help="minimum labeler commit for accepted GT")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    verdicts, summary, retired = audit_run_root(Path(args.run_root), args.label_min_commit)
    write_outputs(Path(args.out_dir), verdicts, summary, retired, args.label_min_commit)

    for v in verdicts:
        print(f"{v['run']:20s} {'PASS' if v['pass'] else 'FAIL'}  {v['failures'] if v['failures'] else 'ok'}")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"gate      -> {Path(args.out_dir) / 'DETECTOR_V2_PROOF_GATE.json'}")
    print(f"retire    -> {Path(args.out_dir) / 'DETECTOR_V2_RETIRE_LIST.json'}")
    return 0 if not retired else 1


if __name__ == "__main__":
    sys.exit(main())
