"""cross_view 存在率审计（结构性缺失路径）测试：合成证据行验证统计与 JSON 输出。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))

from audit_cross_view_signal import audit_evidence


def _write_evidence(tmp_path: Path) -> Path:
    dir_ = tmp_path / "evidence_v2"
    dir_.mkdir()
    rows = [
        {
            "request_identity": "sha256:aaaa",
            "view_id": "full",
            "canonical_unit_id": 1,
            "cross_view": {"view_group": "g1", "n_views": 2, "view_ids": ["full", "overlap"], "unit_covered_by": ["r1"]},
        },
        {"request_identity": "sha256:aaaa", "view_id": "full", "canonical_unit_id": 2, "cross_view": {}},
        {
            "request_identity": "sha256:bbbb",
            "view_id": "overlap",
            "canonical_unit_id": 3,
            "cross_view": {"view_group": "g1", "n_views": 2},
            "features": {"cv_posterior_distance": None, "cv_n_views": 2},
        },
        {"request_identity": "sha256:bbbb", "view_id": "full", "canonical_unit_id": 4, "cross_view": None},
    ]
    (dir_ / "sha256:aaaa.jsonl").write_text(json.dumps(rows[:2]), encoding="utf-8")
    (dir_ / "sha256:bbbb.jsonl").write_text(json.dumps(rows[2:]), encoding="utf-8")
    return dir_


def _write_labels(tmp_path: Path) -> Path:
    rows = [
        {"request_identity": "sha256:aaaa", "view_id": "full", "canonical_unit_id": 1, "label": "unsafe", "split": "train"},
        {"request_identity": "sha256:aaaa", "view_id": "full", "canonical_unit_id": 2, "label": "safe", "split": "train"},
        {"request_identity": "sha256:bbbb", "view_id": "overlap", "canonical_unit_id": 3, "label": "safe", "split": "validation"},
    ]
    path = tmp_path / "LABELS.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def test_audit_evidence_stats_and_splits(tmp_path):
    evidence_dir = _write_evidence(tmp_path)
    labels_path = _write_labels(tmp_path)
    payload = audit_evidence(evidence_dir, labels_path)

    assert payload["schema"] == "cross_view_audit_v1"
    assert payload["status"] == "structural_missing"
    assert payload["recommendation"].startswith("需请求管线")

    ev = payload["evidence"]
    assert ev["total_rows"] == 4
    assert ev["rows_with_features_key"] == 1
    assert ev["rows_cross_view_nonempty"] == 2
    assert ev["rows_with_posterior_distance"] == 0
    assert ev["rows_with_posterior_vectors"] == 0
    assert ev["rows_with_cv_start_diff_sec"] == 0
    assert ev["rows_with_cv_end_diff_sec"] == 0
    assert ev["truncated_by_max_rows"] is False

    train = payload["splits"]["train"]
    assert train["total"] == 2 and train["labeled"] == 2
    assert train["safe"] == 1 and train["unsafe"] == 1
    assert train["cross_view_nonempty"] == 1
    assert train["cross_view_nonempty_rate"] == 0.5
    val = payload["splits"]["validation"]
    assert val["total"] == 1 and val["cross_view_nonempty"] == 1
    assert payload["splits"]["unlabeled"]["total"] == 1


def test_audit_evidence_max_rows_and_missing_labels(tmp_path):
    evidence_dir = _write_evidence(tmp_path)
    payload = audit_evidence(evidence_dir, labels_path=None, max_rows=2)
    assert payload["evidence"]["total_rows"] == 2
    assert payload["evidence"]["truncated_by_max_rows"] is True
    assert set(payload["splits"].keys()) == {"unlabeled"}


def test_audit_single_json_object_file(tmp_path):
    dir_ = tmp_path / "evidence_v2"
    dir_.mkdir()
    row = {"request_identity": "sha256:cccc", "view_id": "full", "canonical_unit_id": 9, "cross_view": {}}
    (dir_ / "sha256:cccc.jsonl").write_text(json.dumps(row), encoding="utf-8")
    payload = audit_evidence(dir_, labels_path=None)
    assert payload["evidence"]["total_rows"] == 1
    assert payload["evidence"]["rows_cross_view_nonempty"] == 0
