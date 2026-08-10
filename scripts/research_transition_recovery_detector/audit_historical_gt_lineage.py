#!/usr/bin/env python3
"""Stage 3A - exhaustive historical GT lineage scanner (CPU only).

Implements Doc 20 Section 3 / Stage 3A: scan historical run artifacts and emit
one row per discovered result artifact classifying its GT axis (U/P/G/none),
use kind, upstream identity and the Doc 20 Section 2 required action.

Read-only scanner: it never modifies any scanned artifact.

Outputs (into --out-dir):
  HISTORICAL_GT_LINEAGE.csv
  HISTORICAL_GT_LINEAGE.jsonl
  PRETRANSITION_GT_AUDIT.json
  HISTORICAL_RERUN_MANIFEST.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROW_FIELDS = [
    "artifact_path",
    "artifact_sha256",
    "producing_commit_or_code_entrypoint",
    "prediction_sha",
    "gt_axis",
    "gt_start_source",
    "gt_end_source",
    "use_kind",
    "upstream_threshold_or_model_identity",
    "source_song_split",
    "action",
    "category",
    "scan_error",
    "note",
]

DEFAULT_SCAN_ROOTS = [
    # 1. Research V7 long-slot artifacts (pattern-filtered), repo + big-data root
    "runs/research_v7_align_behavior",
    "/home/hyan/Data/lyricalign/runs/research_v7_align_behavior",
    # 2. Transition / propagation / detector / oracle / closed-loop artifacts
    "runs/research_transition_recovery_detector_20260807",
    "/home/hyan/Data/lyricalign/runs/research_transition_recovery_detector_20260807",
    "runs/research_transition_recovery_detector_20260808_corrected",
    "/home/hyan/Data/lyricalign/runs/research_transition_recovery_detector_20260808_corrected",
    "/root/autodl-tmp/lyricalign_sessions/20260808_corrected",
    "/root/autodl-tmp/lyricalign_sessions/20260809_signal_completion",
    # 3. The two 2026-08-09 supplement run roots
    "runs/research_transition_recovery_detector_20260809_second_supplement",
    "/home/hyan/Data/lyricalign/runs/research_transition_recovery_detector_20260809_second_supplement",
    "runs/research_transition_recovery_detector_20260809_signal_completion",
    "/home/hyan/Data/lyricalign/runs/research_transition_recovery_detector_20260809_signal_completion",
    # 4. 2026-08-10 real-GT binding / rebuild artifacts
    "runs/research_transition_recovery_detector_20260810_realgt_expansion_handoff",
    "/home/hyan/Data/lyricalign/runs/research_transition_recovery_detector_20260810_realgt_expansion_handoff",
]

V7_PREFIXES = ("GT_EVAL", "LABELS", "LABEL_SUMMARY", "ASSESSOR", "BASELINE_QUALITY")
TEXT_EXTENSIONS = {".json", ".jsonl", ".csv", ".txt", ".md", ".yaml", ".yml", ".log"}
CONTENT_LIMIT = 1 << 20  # bytes of content used for classification heuristics
CHUNK = 1 << 16
MAX_FILE_BYTES_DEFAULT = 50 << 20  # non-v7 roots: skip files larger than 50 MB

# Doc 20 Section 2 categories and their required actions.
CATEGORY_ACTIONS = {
    "research_v7_long_slot_timing": "REAGGREGATE",
    "research_v7_structural": "KEEP structural only",
    "detector_v2_pre_42522c3": "RETIRE",
    "detector_v2_post_42522c3": "KEEP only after TRACE",
    "transition_0807_0808": "REAGGREGATE",
    "propagation_episode": "RERUN",
    "oracle_recovery": "RERUN",
    "supplement_0809": "RERUN",
    "pr_recovery_decomposition": "RERUN",
    "realgt_second_supplement_0810": "REAGGREGATE",
}

# Priorities from Doc 19 Stage 3 table / GT_CONTAMINATED_RERUN_MATRIX (Doc 16).
RERUN_PRIORITY = {
    "research_v7_long_slot_timing": "P0",
    "transition_0807_0808": "P0",
    "detector_v2_post_42522c3": "P0",
    "supplement_0809": "P0",
    "oracle_recovery": "P1",
    "propagation_episode": "P1",
    "realgt_second_supplement_0810": "P1",
    "pr_recovery_decomposition": "P2",
}

_STRUCTURAL_RE = re.compile(r"mutation|virtual[_\- ]?gap|ownership|structural", re.I)
_UNIFORM_RE = re.compile(r"synthetic_uniform_timeline_axis|synthetic_uniform|uniform[_ ]?timeline", re.I)
_G_DEFECT_RE = re.compile(r"greedily bind|greedy bind|local.to.global|pre.?42522c3|coordinate/mapping-corrupted|91\.4%", re.I)
_P_PROJECT_RE = re.compile(
    r"segment_offsets|accepted_rule_based_pinyin_validated|accepted_rule_validated_held_vowel|overlay projection|global_start_sec",
    re.I,
)
_TIMING_RE = re.compile(r"\bMAE\b|unsafe|timing", re.I)
_PRED_SHA_RE = re.compile(r'"(?:prediction|pred|cache)[^":]{0,40}sha(?:256)?"?\s*[:=]\s*"?([0-9a-fA-F]{40,64})')
_MODEL_RE = re.compile(
    r'"(?:FROZEN_WORKING_POINTS?|frozen_working_point|working_point|threshold|model_id|model_name|'
    r"model_identity|checkpoint|revision)\"\s*[:=]\s*\"?([^\"\s,}]{1,80})",
    re.I,
)
_SPLIT_RE = re.compile(r'"(?:source_?song_?split|split|split_role)"\s*[:=]\s*"?([A-Za-z_\-]+)"?', re.I)
_ROLE_RE = re.compile(r'"(?:role|source_role)"\s*[:=]\s*"?([a-z_]+)"?', re.I)
_ENTRY_RE = re.compile(r"(?:entrypoint|script|command)[:\s=\"]*([\w_./\\-]+\.py)", re.I)
_COMMIT_RE = re.compile(r"\bcommit[s]?\b[:\s#]*([0-9a-f]{7,40})", re.I)
_ENTRYPOINT_HINT_RE = re.compile(r"SESSION_RECORD|SUMMARY|REPORT|MANIFEST|RUN_", re.I)


def sha256_file(path: str, skip_large: bool, large_bytes: int) -> str:
    if skip_large:
        try:
            if os.path.getsize(path) > large_bytes:
                return "skipped_large"
        except OSError:
            pass
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                block = fh.read(CHUNK)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()
    except Exception:
        return ""


def read_content(path: str) -> str:
    with open(path, "rb") as fh:
        data = fh.read(CONTENT_LIMIT)
    return data.decode("utf-8", errors="replace")


def classify_axis(fname: str, text: str) -> str:
    if _STRUCTURAL_RE.search(fname) or (_STRUCTURAL_RE.search(text) and not _TIMING_RE.search(text)):
        return "none"
    if _UNIFORM_RE.search(text):
        return "U"
    if _G_DEFECT_RE.search(text):
        return "G"
    if _P_PROJECT_RE.search(text):
        return "P"
    return "PROVENANCE_UNKNOWN"


def classify_use(fname: str, text: str, axis: str) -> str:
    name = fname.upper()
    if re.search(r"LABEL", name):
        return "label"
    if axis == "none":
        return "structural"
    if re.search(r"oracle|closed.?loop|recover|retry|writeback", text, re.I):
        return "recovery"
    if re.search(r"\btrigger\b", text, re.I):
        return "trigger"
    if re.search(r"select|candidate|route", text, re.I):
        return "selection"
    if re.search(r"GT_EVAL|BASELINE_QUALITY|ASSESSOR", name) or _TIMING_RE.search(text):
        return "metric"
    return "other"


def classify_category(path_str: str, fname: str, text: str, axis: str) -> str:
    if axis == "none" or _STRUCTURAL_RE.search(fname):
        return "research_v7_structural"
    if re.search(r"GT_EVAL|BASELINE_QUALITY|ASSESSOR", fname, re.I) and axis in ("U", "P"):
        return "research_v7_long_slot_timing"
    if re.search(r"LABEL", fname, re.I):
        if axis == "G":
            return "detector_v2_pre_42522c3"
        return "detector_v2_post_42522c3"
    low = path_str.lower()
    if "signal_completion" in low or "20260809" in low:
        if "second_supplement" in low or "0810" in low:
            return "realgt_second_supplement_0810"
        return "supplement_0809"
    if "20260810" in low or "realgt" in low or "second_supplement" in low:
        return "realgt_second_supplement_0810"
    if "oracle" in low or "closed" in low or re.search(r"oracle|closed.?loop", text, re.I):
        return "oracle_recovery"
    if re.search(r"propagat|episode", low) or re.search(r"propagat|episode", text, re.I):
        return "propagation_episode"
    if re.search(r"\bPR\b|pr_|precision.?recall|pr_target", text) or "pr_" in low:
        return "pr_recovery_decomposition"
    if "20260807" in low or "20260808" in low or "transition" in low:
        return "transition_0807_0808"
    if re.search(r"detector|label", low):
        return "detector_v2_post_42522c3"
    return "PROVENANCE_UNKNOWN"


def gt_sources(axis: str) -> tuple:
    source = {
        "U": "synthetic_uniform_canonical",
        "P": "overlay+offset",
        "G": "pre_42522c3_local_pinyin",
        "none": "none_structural",
    }.get(axis, "unknown")
    return source, source


def find_prediction_sha(text: str) -> str:
    match = _PRED_SHA_RE.search(text)
    if match:
        return match.group(1)
    nearby = re.search(r"prediction[^\n]{0,200}", text, re.I)
    if nearby:
        hexm = re.search(r"[0-9a-fA-F]{40,64}", nearby.group(0))
        if hexm:
            return hexm.group(0)
    return ""


def find_threshold_model(text: str) -> str:
    found = [m.group(1).strip() for m in _MODEL_RE.finditer(text)]
    return ";".join(found[:3])


def _norm_split(value: str) -> str:
    value = value.strip().lower().replace("-", "_")
    if value in ("val", "valid", "validation"):
        return "validation"
    if value in ("train", "training"):
        return "train"
    if value in ("test",):
        return "test"
    return "unknown"


def find_split(text: str) -> str:
    values = [_norm_split(m.group(1)) for m in _SPLIT_RE.finditer(text)]
    values += [_norm_split(m.group(1)) for m in _ROLE_RE.finditer(text)]
    values = [v for v in values if v != "unknown"]
    if not values:
        return "unknown"
    distinct = set(values)
    if len(distinct) > 1:
        return "mixed"
    return next(iter(distinct))


def infer_entrypoint(path: str) -> str:
    commits, entries = [], []
    try:
        candidates = sorted(Path(path).parent.glob("*"))
    except OSError:
        return "unknown"
    for candidate in candidates:
        if not candidate.is_file() or not _ENTRYPOINT_HINT_RE.search(candidate.name):
            continue
        try:
            head = candidate.read_text(errors="replace")[:8192]
        except Exception:
            continue
        commits.extend(m.group(1) for m in _COMMIT_RE.finditer(head))
        entries.extend(m.group(1) for m in _ENTRY_RE.finditer(head))
    parts = []
    if commits:
        parts.append("commit=" + commits[0])
    if entries:
        parts.append("entry=" + entries[0])
    return ";".join(parts) if parts else "unknown"


def scan_file(path: str, skip_hash_large: bool, large_bytes: int) -> dict:
    row = {field: "" for field in ROW_FIELDS}
    row["artifact_path"] = path
    try:
        row["artifact_sha256"] = sha256_file(path, skip_hash_large, large_bytes)
        text = read_content(path)
        fname = os.path.basename(path)
        row["prediction_sha"] = find_prediction_sha(text)
        axis = classify_axis(fname, text)
        row["gt_axis"] = axis
        start_src, end_src = gt_sources(axis)
        row["gt_start_source"] = start_src
        row["gt_end_source"] = end_src
        row["use_kind"] = classify_use(fname, text, axis)
        row["upstream_threshold_or_model_identity"] = find_threshold_model(text)
        row["source_song_split"] = find_split(text)
        row["producing_commit_or_code_entrypoint"] = infer_entrypoint(path)
        category = classify_category(path, fname, text, axis)
        row["category"] = category
        row["action"] = CATEGORY_ACTIONS.get(category, "PROVENANCE_UNKNOWN")
    except Exception as exc:  # robustness: never crash on a bad artifact
        row["scan_error"] = f"{type(exc).__name__}: {exc}"
        row["gt_axis"] = row["category"] = row["action"] = "PROVENANCE_UNKNOWN"
        row["note"] = "scan_error"
    return row


def discover_files(root: Path, is_v7: bool, max_file_bytes: int) -> list:
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            full = Path(dirpath) / fname
            if is_v7:
                if not fname.startswith(V7_PREFIXES):
                    continue
            else:
                if full.suffix.lower() not in TEXT_EXTENSIONS:
                    continue
                try:
                    if full.stat().st_size > max_file_bytes:
                        continue
                except OSError:
                    continue
            found.append(str(full))
    return found


def build_audit(rows: list, active_roots: list) -> dict:
    categories = {
        cat: {"count": 0, "artifact_paths": [], "action": CATEGORY_ACTIONS.get(cat, "PROVENANCE_UNKNOWN")}
        for cat in CATEGORY_ACTIONS
    }
    provenance_unknown_rows = []
    for row in rows:
        cat = row["category"]
        if cat in categories:
            categories[cat]["count"] += 1
            categories[cat]["artifact_paths"].append(row["artifact_path"])
        elif cat == "PROVENANCE_UNKNOWN":
            provenance_unknown_rows.append(row)
    no_artifact_found = [
        {"category": cat, "action": info["action"]}
        for cat, info in categories.items()
        if info["count"] == 0
    ]
    return {
        "scan_roots": active_roots,
        "categories": categories,
        "no_artifact_found": no_artifact_found,
        "provenance_unknown_rows": provenance_unknown_rows,
        "assert": "every Doc20 Section 2 category has >=1 classified artifact OR explicit no_artifact_found record",
        "complete": len(no_artifact_found) == 0,
        "summary": {cat: info["count"] for cat, info in categories.items()},
    }


def build_rerun_manifest(rows: list) -> dict:
    entries = []
    for row in rows:
        action = row["action"]
        if action not in ("REAGGREGATE", "RERUN"):
            continue
        category = row["category"]
        entries.append(
            {
                "artifact_path": row["artifact_path"],
                "action": action,
                "priority": RERUN_PRIORITY.get(category, "P2"),
                "route": "cpu" if action == "REAGGREGATE" else "gpu",
                "gt_axis": row["gt_axis"],
                "category": category,
            }
        )
    entries.sort(key=lambda e: e["artifact_path"])
    return {
        "entries": entries,
        "count": len(entries),
        "note": "REAGGREGATE -> cpu (metric recompute from identity-verified predictions); RERUN -> gpu (needs model inference)",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="metadata/lineage")
    parser.add_argument("--scan-root", action="append", default=None, help="repeatable; when provided it replaces the default roots")
    parser.add_argument("--max-files", type=int, default=None, help="limit number of scanned artifacts")
    parser.add_argument("--skip-hash-large", action="store_true", help="skip hashing files larger than --large-threshold-mb")
    parser.add_argument("--large-threshold-mb", type=int, default=100)
    args = parser.parse_args(argv)

    roots = args.scan_root if args.scan_root else DEFAULT_SCAN_ROOTS
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files, active_roots = [], []
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            print(f"WARNING: scan root does not exist, skipping: {root}", file=sys.stderr)
            continue
        if not root_path.is_dir():
            print(f"WARNING: scan root is not a directory, skipping: {root}", file=sys.stderr)
            continue
        active_roots.append(root)
        is_v7 = "research_v7_align_behavior" in str(root_path)
        files.extend(discover_files(root_path, is_v7, MAX_FILE_BYTES_DEFAULT))

    files = sorted(set(files))  # deterministic ordering
    if args.max_files is not None:
        files = files[: args.max_files]

    large_bytes = args.large_threshold_mb << 20
    rows = [scan_file(path, args.skip_hash_large, large_bytes) for path in files]

    with open(out_dir / "HISTORICAL_GT_LINEAGE.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ROW_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    with open(out_dir / "HISTORICAL_GT_LINEAGE.jsonl", "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    audit = build_audit(rows, active_roots)
    with open(out_dir / "PRETRANSITION_GT_AUDIT.json", "w", encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=2)

    manifest = build_rerun_manifest(rows)
    with open(out_dir / "HISTORICAL_RERUN_MANIFEST.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    counts = Counter(row["action"] for row in rows)
    print(f"Scanned {len(rows)} artifacts across {len(active_roots)} roots.")
    print(f"Output written to {out_dir}")
    for action in sorted(counts):
        print(f"  {action}: {counts[action]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
