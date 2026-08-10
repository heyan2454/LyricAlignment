#!/usr/bin/env python3
"""Stage 3 - real-GT input provenance audit + historical cache reuse plan (CPU only).

For each cohort song (COHORT_A_FORMAL.jsonl line: {song_id, audio, split, overlay}),
audit input completeness and hashes; walk historical run roots to build a cache
reuse plan; merge the Stage 3A lineage CSV with per-artifact reuse actions.

Reuse rule (Doc 19 Stage 3): reuse only when model/checkpoint, audio SHA, request
schema, text, mapping, code version, environment identity all match.

Cache entry schema recognized by this script (must be produced/consumed
consistently by tests):
  {request_id, song_id, model_id, checkpoint_sha, revision, audio_sha,
   request_schema, text, mapping, code_version, environment_identity,
   prediction_sha}
Cache discovery is tolerant: any *.json / *.jsonl file under a historical cache
root whose payload dict(s) carry a request_id key is treated as an entry list.

Outputs (into --out):
  INPUT_PROVENANCE_AUDIT.json
  CACHE_REUSE_PLAN.json
  HISTORICAL_GT_LINEAGE_SUMMARY.csv
  INPUT_PROVENANCE_FREEZE.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

CHUNK = 1 << 16
SUMMARY_FIELDS = ["artifact_path", "prediction_sha", "request_id", "action", "action_override", "override_reason", "note"]

CORE_IDENTITY_FIELDS = ("model_id", "checkpoint_sha", "revision", "audio_sha", "request_schema", "text", "mapping")
REUSE_REQUIRED_IDENTITY_FIELDS = ("code_version", "environment_identity")


def sha256_file(path: str) -> str:
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_head(repo: str | Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return "unknown"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def build_provenance_audit(cohort_path: Path, long_path: Path, real_gt_audit_path: Path) -> dict:
    try:
        cohort_rows = load_jsonl(cohort_path)
    except Exception as exc:
        return {"error": f"cohort load failed: {type(exc).__name__}: {exc}", "per_song": [], "provenance_ok": False}

    manifest_by_song: dict[str, dict] = {}
    try:
        for row in load_jsonl(long_path):
            sid = row.get("song_id")
            if sid is not None:
                manifest_by_song[sid] = row
    except Exception as exc:
        manifest_by_song = {}
        manifest_load_error = f"{type(exc).__name__}: {exc}"
    else:
        manifest_load_error = ""

    real_gt_doc: dict = {}
    if real_gt_audit_path.exists():
        try:
            real_gt_doc = json.loads(real_gt_audit_path.read_text(encoding="utf-8"))
        except Exception as exc:
            real_gt_doc = {"_load_error": f"{type(exc).__name__}: {exc}"}
    real_gt_per_song = real_gt_doc.get("per_song", {}) if isinstance(real_gt_doc, dict) else {}

    per_song = []
    for idx, cohort_row in enumerate(cohort_rows):
        row: dict = {}
        try:
            sid = cohort_row.get("song_id", f"line_{idx}")
            row["song_id"] = sid
            row["split"] = cohort_row.get("split", "")
            row["source_split"] = cohort_row.get("source_split", cohort_row.get("split", ""))

            audio_path = cohort_row.get("audio", "")
            audio_exists = bool(audio_path) and Path(audio_path).is_file()
            audio_sha = sha256_file(audio_path) if audio_exists else ""
            row["audio"] = {"path": audio_path, "exists": audio_exists, "sha256": audio_sha}

            overlay_path = cohort_row.get("overlay", "")
            overlay_exists = bool(overlay_path) and Path(overlay_path).is_file()
            overlay_rows = 0
            if overlay_exists:
                try:
                    overlay_rows = len(load_jsonl(Path(overlay_path)))
                except Exception as exc:
                    row["scan_error"] = f"overlay parse: {type(exc).__name__}: {exc}"
                    overlay_rows = 0
            row["overlay"] = {"path": overlay_path, "exists": overlay_exists, "row_count": overlay_rows}

            manifest_row = manifest_by_song.get(sid)
            if manifest_row is not None:
                row_sha = sha256_bytes(
                    json.dumps(manifest_row, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            else:
                row_sha = ""
            row["manifest"] = {
                "row_found": manifest_row is not None,
                "row_sha256": row_sha,
                "canonical_units": len(manifest_row.get("canonical_units", [])) if manifest_row else 0,
            }

            rg = real_gt_per_song.get(sid) if isinstance(real_gt_per_song, dict) else None
            if isinstance(rg, dict):
                accepted_val = rg.get("accepted", rg.get("accepted_gt_units"))
                unlabeled_val = rg.get("unlabeled", rg.get("unlabeled_units"))
                if accepted_val is None or unlabeled_val is None:
                    row["real_gt"] = {
                        "song_in_audit": True,
                        "accepted_real_gt": 0,
                        "unlabeled": 0,
                        "field_missing": True,
                    }
                else:
                    row["real_gt"] = {
                        "song_in_audit": True,
                        "accepted_real_gt": int(accepted_val),
                        "unlabeled": int(unlabeled_val),
                    }
            else:
                row["real_gt"] = {"song_in_audit": False, "accepted_real_gt": 0, "unlabeled": 0}

            missing = []
            if not audio_exists:
                missing.append("audio_file")
            if not audio_sha:
                missing.append("audio_sha256")
            if not overlay_exists:
                missing.append("overlay_file")
            if overlay_exists and overlay_rows <= 0:
                missing.append("overlay_rows")
            if manifest_row is None:
                missing.append("manifest_row")
            if not row_sha:
                missing.append("manifest_row_sha256")
            if not row["real_gt"]["song_in_audit"]:
                missing.append("real_gt_audit_song")
            elif row["real_gt"].get("field_missing"):
                missing.append("real_gt_audit_fields")
            row["missing"] = missing
            row["provenance_ok"] = not missing
        except Exception as exc:
            row.setdefault("song_id", f"line_{idx}")
            row["scan_error"] = f"{type(exc).__name__}: {exc}"
            row["missing"] = ["scan_error"]
            row["provenance_ok"] = False
        per_song.append(row)

    if manifest_load_error:
        for row in per_song:
            row.setdefault("scan_error", manifest_load_error)
            row["missing"] = sorted(set(row.get("missing", [])) | {"manifest_load_error"})
            row["provenance_ok"] = False

    ok_count = sum(1 for r in per_song if r.get("provenance_ok"))
    return {
        "songs": len(per_song),
        "provenance_ok_count": ok_count,
        "provenance_ok": ok_count == len(per_song) and len(per_song) > 0,
        "per_song": per_song,
    }


def discover_cache_entries(cache_roots: list[str]) -> list[dict]:
    entries: dict[str, dict] = {}
    source_of: dict[str, str] = {}
    for root in cache_roots:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        candidates = []
        for dirpath, _dirnames, filenames in os.walk(root_path):
            for fname in sorted(filenames):
                low = fname.lower()
                full = Path(dirpath) / fname
                if fname.endswith(".jsonl") and "cache" in low:
                    candidates.append(full)
                elif fname.endswith(".json") and ("cache" in low or "identity" in low):
                    candidates.append(full)
        for full in sorted(candidates):
            payload = None
            try:
                if full.suffix == ".jsonl":
                    payload = [json.loads(l) for l in full.read_text(encoding="utf-8").splitlines() if l.strip()]
                else:
                    payload = json.loads(full.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, list):
                payload = [payload]
            for item in payload:
                if not isinstance(item, dict) or "request_id" not in item:
                    continue
                rid = str(item.get("request_id", ""))
                if not rid:
                    continue
                if rid in entries:
                    continue
                norm = {field: item.get(field, "") for field in
                        ("request_id", "song_id", "model_id", "checkpoint_sha", "revision",
                         "audio_sha", "request_schema", "text", "mapping",
                         "code_version", "environment_identity", "prediction_sha")}
                entries[rid] = norm
                source_of[rid] = str(full)
    ordered = []
    for rid in sorted(entries):
        entry = dict(entries[rid])
        entry["_source"] = source_of[rid]
        ordered.append(entry)
    return ordered


def classify_entry(
    entry: dict,
    current: dict,
    cohort_audio_sha: dict[str, str],
    song_texts: dict[str, str],
) -> tuple[str, list[str]]:
    song = entry.get("song_id", "")
    expected_audio = cohort_audio_sha.get(song, "")
    expected_text = song_texts.get(song, "")
    missing_core = [
        field for field in ("model_id", "checkpoint_sha", "audio_sha", "request_schema", "text", "mapping")
        if not entry.get(field)
    ]
    if missing_core:
        return "not_reusable", [f"missing_core_field:{field}" for field in missing_core]
    mismatches = []
    for field in ("model_id", "checkpoint_sha", "revision", "request_schema", "mapping"):
        if not current.get(field):
            mismatches.append(f"identity_source_missing:{field}")
        elif entry.get(field) != current[field]:
            mismatches.append(f"mismatch:{field}")
    if entry.get("audio_sha") != expected_audio:
        mismatches.append("mismatch:audio_sha" if expected_audio else "mismatch:audio_sha(no_cohort_audio)")
    if entry.get("text") != expected_text:
        mismatches.append("mismatch:text")
    if mismatches:
        return "not_reusable", mismatches
    missing_required = [
        field for field in REUSE_REQUIRED_IDENTITY_FIELDS if not entry.get(field)
    ]
    if missing_required:
        return "reusable_for_diagnostic_only", [f"missing:{field}" for field in missing_required]
    return "reusable", ["all_identities_match"]


def build_cache_reuse_plan(
    cache_roots: list[str],
    current: dict,
    cohort_audio_sha: dict[str, str],
    song_texts: dict[str, str],
) -> dict:
    entries = discover_cache_entries(cache_roots)
    classified = []
    counts = {"reusable": 0, "reusable_for_diagnostic_only": 0, "not_reusable": 0}
    for entry in entries:
        klass, reasons = classify_entry(entry, current, cohort_audio_sha, song_texts)
        counts[klass] += 1
        record = {"request_id": entry["request_id"], "song_id": entry.get("song_id", ""),
                  "prediction_sha": entry.get("prediction_sha", ""),
                  "classification": klass, "reasons": reasons, "source": entry.get("_source", ""),
                  "identity": {field: entry.get(field, "") for field in CORE_IDENTITY_FIELDS},
                  "code_version": entry.get("code_version", ""),
                  "environment_identity": entry.get("environment_identity", "")}
        classified.append(record)
    return {
        "current_identity": current,
        "reuse_rule": "reuse only when model/checkpoint, audio SHA, request schema, text, mapping, "
                      "code version, environment identity match",
        "counts": counts,
        "entries": classified,
        "note": "reusable_for_diagnostic_only: core identities match but code/environment identity not recorded",
    }


def merge_lineage_summary(lineage_csv: Path | None, plan: dict, out: Path) -> None:
    fieldnames = SUMMARY_FIELDS
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        if lineage_csv is None or not lineage_csv.exists():
            writer.writerow({
                "artifact_path": "(no lineage csv provided)",
                "action": "",
                "action_override": "",
                "override_reason": "no --lineage-csv input; HISTORICAL_GT_LINEAGE.csv not merged",
                "note": "empty summary",
            })
            return
        by_request = {e["request_id"]: e["classification"] for e in plan["entries"]}
        by_pred_sha = {e.get("prediction_sha") or e["request_id"]: e["classification"]
                       for e in plan["entries"]}
        with open(lineage_csv, newline="", encoding="utf-8") as lf:
            reader = csv.DictReader(lf)
            rows = list(reader)
        for row in rows:
            rid = (row.get("request_id") or "").strip()
            pred_sha = (row.get("prediction_sha") or "").strip()
            klass = by_request.get(rid)
            if klass is None:
                klass = by_pred_sha.get(pred_sha)
            if klass == "reusable":
                row["action_override"] = "reuse"
                row["override_reason"] = "cache entry reusable with matching identity"
            elif klass == "reusable_for_diagnostic_only":
                row["action_override"] = "reuse_for_diagnostic_only"
                row["override_reason"] = "cache entry usable only for diagnosis (missing code/env identity)"
            elif klass == "not_reusable":
                row["action_override"] = "rerun"
                row["override_reason"] = "cache entry not reusable; must rerun"
            else:
                row["action_override"] = ""
                row["override_reason"] = "no matching cache entry"
                row["note"] = "no cache reuse decision"
            writer.writerow(row)


def build_freeze(args, cohort_path: Path, long_path: Path, real_gt_path: Path) -> dict:
    inputs = {
        "COHORT_A_FORMAL.jsonl": {"path": str(cohort_path), "sha256": sha256_file(str(cohort_path))},
        "LONG_TIMELINE_MANIFEST.jsonl": {"path": str(long_path), "sha256": sha256_file(str(long_path))},
        "REAL_GT_PROJECTION_AUDIT.json": {"path": str(real_gt_path), "sha256": sha256_file(str(real_gt_path))},
    }
    if args.checkpoint_identity:
        inputs["checkpoint_identity"] = {"path": args.checkpoint_identity,
                                         "sha256": sha256_file(args.checkpoint_identity)}
    if args.lineage_csv:
        inputs["lineage_csv"] = {"path": args.lineage_csv, "sha256": sha256_file(args.lineage_csv)}
    for root in args.historical_cache:
        inputs[f"historical_cache:{root}"] = {"dir": root}
    return {
        "schema": "input_provenance_freeze_v1",
        "git_head": git_head("."),
        "inputs": inputs,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-manifest", required=True)
    parser.add_argument("--long-manifest", required=True)
    parser.add_argument("--real-gt-audit", required=True)
    parser.add_argument("--historical-cache", action="append", default=[])
    parser.add_argument("--checkpoint-identity", default=None)
    parser.add_argument("--lineage-csv", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cohort_path = Path(args.cohort_manifest)
    long_path = Path(args.long_manifest)
    real_gt_path = Path(args.real_gt_audit)

    provenance = build_provenance_audit(cohort_path, long_path, real_gt_path)
    with open(out_dir / "INPUT_PROVENANCE_AUDIT.json", "w", encoding="utf-8") as fh:
        json.dump(provenance, fh, ensure_ascii=False, indent=2)

    current: dict = {}
    if args.checkpoint_identity:
        try:
            current = json.loads(Path(args.checkpoint_identity).read_text(encoding="utf-8"))
        except Exception:
            current = {"load_error": "checkpoint_identity unreadable"}
    cohort_audio_sha = {}
    song_texts = {}
    try:
        for row in load_jsonl(long_path):
            sid = row.get("song_id")
            if sid is None:
                continue
            song_texts[sid] = "|".join(
                (u.get("text") or "") for u in row.get("canonical_units", []))
    except Exception:
        pass
    for row in provenance.get("per_song", []):
        sid = row.get("song_id")
        if sid and row.get("audio", {}).get("sha256"):
            cohort_audio_sha[sid] = row["audio"]["sha256"]

    plan = build_cache_reuse_plan(args.historical_cache, current, cohort_audio_sha, song_texts)
    plan["cohort_song_text_fingerprints"] = {sid: sha256_bytes(t.encode("utf-8"))[:12] for sid, t in sorted(song_texts.items())}
    for entry in plan["entries"]:
        sid = entry["song_id"]
        if sid and sid in song_texts:
            text_expected = sha256_bytes(song_texts[sid].encode("utf-8"))[:12]
            entry["text_expected_fingerprint"] = text_expected
    with open(out_dir / "CACHE_REUSE_PLAN.json", "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)

    lineage_csv = Path(args.lineage_csv) if args.lineage_csv else None
    merge_lineage_summary(lineage_csv, plan, out_dir / "HISTORICAL_GT_LINEAGE_SUMMARY.csv")

    freeze = build_freeze(args, cohort_path, long_path, real_gt_path)
    with open(out_dir / "INPUT_PROVENANCE_FREEZE.json", "w", encoding="utf-8") as fh:
        json.dump(freeze, fh, ensure_ascii=False, indent=2)

    print(json.dumps({
        "ok": True,
        "songs": provenance.get("songs"),
        "provenance_ok": provenance.get("provenance_ok"),
        "cache_counts": plan["counts"],
        "out": str(out_dir),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
