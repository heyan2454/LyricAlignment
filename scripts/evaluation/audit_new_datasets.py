#!/usr/bin/env python3
"""Audit newly acquired datasets for productization readiness.

This is a CPU-only, read-only audit. It writes a small JSON report and a
cleanup report under the requested out-root.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASETS_ROOT = Path("/home/hyan/Data/datasets")
DEFAULT_OUT_ROOT = Path("/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_datasets_audit")

DATASET_IDS = [
    "mir_mlpop",
    "jamendolyrics_en",
    "pjs",
    "gtsinger_chinese",
    "amll_ttml_db",
    "ikala",
]

EXPECTED_META = ["README.md", "SOURCE.md", "TERMS.md", "acquisition.json", "checksums.sha256"]


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def count_files(root: Path, patterns: tuple[str, ...]) -> int:
    total = 0
    for pattern in patterns:
        total += len(list(root.rglob(pattern)))
    return total


def audit_one(datasets_root: Path, dataset_id: str) -> dict:
    root = datasets_root / dataset_id
    acq_path = root / "acquisition.json"
    acq = {}
    if acq_path.exists():
        try:
            acq = json.loads(acq_path.read_text(encoding="utf-8"))
        except Exception as exc:
            acq = {"_read_error": str(exc)}
    missing_meta = [name for name in EXPECTED_META if not (root / name).exists()]
    # Count only the operational payload, not provenance snapshots or raw archives.
    if dataset_id == "mir_mlpop":
        search_roots = [root / "raw/extracted/audio"]
    elif dataset_id == "jamendolyrics_en":
        search_roots = [root / "raw/extracted/huggingface_snapshot/subsets/en/mp3"]
    elif dataset_id == "pjs":
        search_roots = [root / "raw/extracted/PJS_corpus_ver1.1"]
    elif dataset_id == "gtsinger_chinese":
        search_roots = [root / "raw/extracted/selected_data"]
    else:
        search_roots = []
    audio_count = 0
    audio_bytes = 0
    for search_root in search_roots:
        for pattern in ("*.wav", "*.mp3", "*.flac"):
            for p in search_root.rglob(pattern):
                audio_count += 1
                try:
                    audio_bytes += p.stat().st_size
                except OSError:
                    pass
    # Lightweight per-dataset readiness rules.
    status = acq.get("status", "unknown")
    if dataset_id == "ikala":
        readiness = "blocked_pending_access"
        notes = ["No main audio; custom license unresolved; do not use."]
    elif dataset_id == "amll_ttml_db":
        readiness = "silver_pool_no_audio"
        notes = ["TTML annotations only; underlying lyric/translation rights not cleared."]
    elif dataset_id == "mir_mlpop":
        readiness = "raw_mixture_partial_audio_vocal_pending"
        notes = ["Partial upstream availability; requires vocal derivation before operational benchmark."]
    elif dataset_id == "jamendolyrics_en":
        readiness = "raw_mixture_complete_vocal_pending"
        notes = ["Raw MP3 complete; requires vocal derivation + per-track license retention."]
    elif dataset_id == "pjs":
        readiness = "vocal_ready_internal"
        notes = ["Complete Japanese singing/speech; CC BY-SA 4.0; use for boundary calibration."]
    elif dataset_id == "gtsinger_chinese":
        readiness = "vocal_ready_internal_pending_terms"
        notes = ["Complete selected subset; additional upstream agreement unresolved."]
    else:
        readiness = "unknown"
        notes = []
    return {
        "dataset_id": dataset_id,
        "root": str(root),
        "acquisition_status": status,
        "missing_meta": missing_meta,
        "meta_complete": not missing_meta,
        "audio_file_count": audio_count,
        "audio_bytes": audio_bytes,
        "readiness": readiness,
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets-root", type=Path, default=DEFAULT_DATASETS_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()

    rows = [audit_one(args.datasets_root, ds) for ds in DATASET_IDS]
    summary = {
        "schema_version": "new_datasets_readiness_audit_v1",
        "dataset_count": len(rows),
        "readiness_counts": dict(Counter(r["readiness"] for r in rows)),
        "meta_complete_count": sum(1 for r in rows if r["meta_complete"]),
        "total_audio_files": sum(r["audio_file_count"] for r in rows),
        "total_audio_bytes": sum(r["audio_bytes"] for r in rows),
        "datasets": rows,
    }
    out_root = args.out_root
    out_root.mkdir(parents=True, exist_ok=True)
    report_path = out_root / "dataset_readiness_audit.json"
    atomic_json(report_path, summary)
    cleanup = [
        "# Cleanup Report — New Datasets Readiness Audit",
        "",
        "This batch writes only one small JSON report.",
        "",
        f"File: `{report_path.relative_to(out_root)}` ({report_path.stat().st_size} bytes)",
        "",
        "Recreate with:",
        "",
        f"```bash\npython scripts/evaluation/audit_new_datasets.py --out-root {out_root}\n```",
        "",
        "Delete with:",
        "",
        f"```bash\nrm -rf {out_root}\n```",
        "",
    ]
    (out_root / "cleanup_report.md").write_text("\n".join(cleanup), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
