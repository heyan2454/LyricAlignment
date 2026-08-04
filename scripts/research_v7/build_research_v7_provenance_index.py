#!/usr/bin/env python3
"""Build a content-addressed index of frozen research-v7 run artifacts.

The index deliberately records only files that exist in each supplied run root.
It is a reporting aid, not an inference result: a missing freeze, manifest, or
verification file remains visible as ``null`` rather than being inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ARTIFACT_NAMES = (
    "manifest.jsonl", "freeze.json", "collection.json", "analysis.json",
    "gt_paired.json", "gt_paired_v2.json", "gt_paired_v3.json",
    "workflow_gt.json", "workflow_gt_v2.json", "review_bundle.json",
    "source_song_coverage.json",
    "c10_multianswer_gt.json",
    "recovery_gt.json",
    "gt_evidence_diagnostics.json",
    "blinded_review_packets.json", "experimenter_blind_key.json",
    "internal_signal_separation.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def indexed_file(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}


def collection_summary(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    return {
        "records": len(records),
        "request_ids_sha256": hashlib.sha256(
            "\n".join(sorted(str(record.get("request_id", "")) for record in records)).encode()
        ).hexdigest(),
    }


def build_entry(root: Path) -> dict[str, object]:
    artifacts = {name: indexed_file(root / name) for name in ARTIFACT_NAMES}
    # Run families predate a single naming convention (for example,
    # ``workflow_manifest.jsonl`` and ``formal_freeze.json``).  Preserve the
    # canonical slots above while also indexing every root-level manifest/freeze
    # so an auditor never mistakes a naming difference for a missing input.
    manifest_files = {
        path.name: indexed_file(path)
        for path in sorted(root.glob("*manifest*.jsonl"))
    }
    freeze_files = {
        path.name: indexed_file(path)
        for path in sorted(root.glob("*freeze*.json"))
    }
    return {
        "run_name": root.name,
        "run_root": str(root),
        "artifacts": artifacts,
        "manifest_files": manifest_files,
        "freeze_files": freeze_files,
        "collection_summary": collection_summary(root / "collection.json"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", action="append", required=True,
                        help="frozen run directory; may be specified repeatedly")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    roots = [Path(value).resolve() for value in args.run_root]
    missing = [str(root) for root in roots if not root.is_dir()]
    if missing:
        parser.error("missing run root: " + ", ".join(missing))
    entries = [build_entry(root) for root in sorted(roots)]
    names = [entry["run_name"] for entry in entries]
    if len(names) != len(set(names)):
        parser.error("run root names must be unique")
    payload = {"schema": "research_v7/provenance_index_v1", "runs": entries}
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") != text:
        parser.error(f"refusing to overwrite a different provenance index: {target}")
    target.write_text(text, encoding="utf-8")
    print(json.dumps({"ok": True, "runs": len(entries), "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
