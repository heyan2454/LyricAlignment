from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

_SPEC = importlib.util.spec_from_file_location(
    "audit_detector_v2_proof",
    ROOT / "scripts/research_transition_recovery_detector/audit_detector_v2_proof.py",
)
audit = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(audit)


def _row(start_key: str, **over: object) -> dict:
    row = {
        "request_identity": "sha256:req",
        "view_id": "full",
        "canonical_unit_id": 0,
        "target": "raw",
        "label": "safe",
        "audit": {
            "reason": "ok",
            "start_abs_error_sec": 0.01,
            "end_abs_error_sec": 0.02,
            "missing_geometry": False,
            "used_keys": {
                "start_key": start_key,
                "end_key": start_key.replace("start", "end"),
                "start_present": True,
                "end_present": True,
            },
        },
        "gt_unavailable": False,
        "family": "legal",
        "split": "train",
        "song_id": "s",
    }
    row.update(over)
    return row


def _write_query_set(root: Path) -> Path:
    manifests = root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "REQUESTS.jsonl").write_text(json.dumps({"canonical_ids": [0]}) + "\n", "utf-8")
    return root


def _write_summary(root: Path, **over: object) -> Path:
    summary = {
        "schema_version": "research_v7_detector_v2_labels_v1",
        "labels_file": "LABELS.jsonl",
        "labels_sha": "sha256:fake",
        "gt_label_audit": {"rows": 2, "status": "accepted_pinyin_global"},
        "source_song_split_used": True,
    }
    summary.update(over)
    (root / "LABEL_SUMMARY.json").write_text(json.dumps(summary), "utf-8")
    return root


def _write_good_run(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        _row("raw_global_start_sec", source_segment_id=3, source_unit_index=5,
             segment_offsets={"global_start_sec": 12.0}),
        _row("official_global_start_sec"),
    ]
    (root / "LABELS.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    _write_query_set(root)
    _write_summary(root)
    return root


def _write_local_run(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        _row("raw_local_start_sec", source_segment_id=3, source_unit_index=5,
             segment_offsets={"global_start_sec": 12.0}),
    ]
    (root / "LABELS.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    _write_query_set(root)
    _write_summary(root)
    return root


def _write_nolabels_run(root: Path) -> Path:
    _write_query_set(root)
    _write_summary(root)
    return root


def test_good_run_passes(tmp_path: Path) -> None:
    root = _write_good_run(tmp_path / "good")
    verdict = audit.audit_run(root)
    assert verdict["pass"] is True
    assert verdict["failures"] == []
    assert verdict["query_set_file"] is not None and verdict["query_set_file"].endswith("REQUESTS.jsonl")
    assert verdict["labels_file"] is not None
    assert verdict["label_sha"] is not None
    assert verdict["n_label_rows"] == 2


def test_local_keys_fail_with_g_defect(tmp_path: Path) -> None:
    root = _write_local_run(tmp_path / "local")
    verdict = audit.audit_run(root)
    assert verdict["pass"] is False
    assert "g_defect_local_keys" in verdict["failures"]


def test_missing_labels_file_fails(tmp_path: Path) -> None:
    root = _write_nolabels_run(tmp_path / "nolabels")
    verdict = audit.audit_run(root)
    assert verdict["pass"] is False
    assert "missing_labels_file" in verdict["failures"]


def test_aggregate_run_root_and_outputs(tmp_path: Path) -> None:
    _write_good_run(tmp_path / "good")
    _write_local_run(tmp_path / "local")
    _write_nolabels_run(tmp_path / "nolabels")

    verdicts, summary, retired = audit.audit_run_root(tmp_path)
    assert summary["total_runs"] == 3
    assert summary["retained"] == 1
    assert summary["retired"] == 2
    assert summary["retained_runs"] == ["good"]
    assert summary["retired_runs"] == ["local", "nolabels"]
    assert [v["run"] for v in retired] == ["local", "nolabels"]

    out = tmp_path / "out"
    audit.write_outputs(out, verdicts, summary, retired, audit.LABEL_MIN_COMMIT_DEFAULT)
    assert (out / "DETECTOR_V2_PROOF_GATE.json").is_file()
    assert (out / "DETECTOR_V2_RETIRE_LIST.json").is_file()
    retire = json.loads((out / "DETECTOR_V2_RETIRE_LIST.json").read_text("utf-8"))
    assert [item["run"] for item in retire["retired"]] == ["local", "nolabels"]


def _write_run_manifest(root: Path, git_commit: str) -> Path:
    manifest = {
        "schema": "run_manifest_v1",
        "run_id": "run",
        "code_identity": {"git_commit": git_commit},
        "manifest": {"path": "manifests/REQUESTS.jsonl"},
    }
    (root / "RUN_MANIFEST.json").write_text(json.dumps(manifest), "utf-8")
    return root


def test_local_key_after_max_rows_fails_truncated(tmp_path: Path) -> None:
    root = _write_good_run(tmp_path / "late_local")
    rows = [_row("raw_global_start_sec", source_segment_id=3, source_unit_index=5,
                 segment_offsets={"global_start_sec": 12.0}) for _ in range(2000)]
    rows.append(_row("raw_local_start_sec"))
    (root / "LABELS.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    verdict = audit.audit_run(root)
    assert verdict["pass"] is False
    assert "labels_scan_truncated" in verdict["failures"]
    assert "g_defect_local_keys" in verdict["failures"]


def test_pre_min_label_commit_fails(tmp_path: Path) -> None:
    root = _write_good_run(tmp_path / "old_commit")
    _write_run_manifest(root, "352def4528308ca7906af25b575f7f724e0ee97e")
    verdict = audit.audit_run(root)
    assert verdict["pass"] is False
    assert verdict["label_commit"] == "352def4528308ca7906af25b575f7f724e0ee97e"
    assert "label_pre_min_commit" in verdict["failures"]


def test_label_commit_at_floor_passes(tmp_path: Path) -> None:
    root = _write_good_run(tmp_path / "floor_commit")
    _write_run_manifest(root, "42522c39b51f015d7e16b1f62b3b3973e021676a")
    verdict = audit.audit_run(root)
    assert verdict["pass"] is True
    assert "label_pre_min_commit" not in verdict["failures"]


def test_review_required_rows_fail(tmp_path: Path) -> None:
    root = _write_good_run(tmp_path / "review_rows")
    rows = [
        _row("raw_global_start_sec", label="review_required_manual", source_segment_id=3,
             source_unit_index=5, segment_offsets={"global_start_sec": 12.0}),
        _row("official_global_start_sec"),
    ]
    (root / "LABELS.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    verdict = audit.audit_run(root)
    assert verdict["pass"] is False
    assert "labels_unaccepted_status" in verdict["failures"]
