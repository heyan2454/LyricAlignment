import csv
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "scripts" / "research_transition_recovery_detector" / "audit_historical_gt_lineage.py"

EXPECTED_CATEGORIES = {
    "research_v7_long_slot_timing",
    "research_v7_structural",
    "detector_v2_pre_42522c3",
    "detector_v2_post_42522c3",
    "transition_0807_0808",
    "propagation_episode",
    "oracle_recovery",
    "supplement_0809",
    "pr_recovery_decomposition",
    "realgt_second_supplement_0810",
}


def make_tree(tmp_path):
    gt = tmp_path / "runs" / "gt_eval"
    gt.mkdir(parents=True)
    (gt / "GT_EVAL_long_slot.json").write_text(
        json.dumps(
            {
                "synthetic_uniform_timeline_axis": "duration / len(units)",
                "MAE": {"start": 0.12, "end": 0.15},
                "source_song_split": "test",
                "prediction_sha": "a" * 64,
            }
        )
    )
    labels = tmp_path / "runs" / "labels"
    labels.mkdir(parents=True)
    (labels / "LABEL_SUMMARY_m4.json").write_text(
        json.dumps(
            {
                "accepted_rule_based_pinyin_validated": True,
                "segment_offsets": {"global_start_sec": 12.0},
                "role": "validation",
                "model_identity": "frozen-wp-v2",
            }
        )
    )
    structural = tmp_path / "runs" / "structural"
    structural.mkdir(parents=True)
    (structural / "MUTATION_LONG_SLOT.json").write_text(
        json.dumps(
            {
                "mutation": {"replace": 3},
                "virtual_gap": {"missing": [1, 2]},
                "construction": "structural",
            }
        )
    )
    return tmp_path / "runs"


def run_scanner(scan_root, out_dir):
    proc = subprocess.run(
        [sys.executable, str(SCANNER), "--scan-root", str(scan_root), "--out-dir", str(out_dir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def test_audit_historical_gt_lineage(tmp_path):
    scan_root = make_tree(tmp_path)
    out_dir = tmp_path / "out"
    run_scanner(scan_root, out_dir)

    assert (out_dir / "HISTORICAL_GT_LINEAGE.csv").exists()
    assert (out_dir / "HISTORICAL_GT_LINEAGE.jsonl").exists()
    assert (out_dir / "PRETRANSITION_GT_AUDIT.json").exists()
    assert (out_dir / "HISTORICAL_RERUN_MANIFEST.json").exists()

    rows = [
        json.loads(line)
        for line in (out_dir / "HISTORICAL_GT_LINEAGE.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 3
    by_name = {Path(r["artifact_path"]).name: r for r in rows}

    assert by_name["GT_EVAL_long_slot.json"]["gt_axis"] == "U"
    assert by_name["LABEL_SUMMARY_m4.json"]["gt_axis"] == "P"
    assert by_name["MUTATION_LONG_SLOT.json"]["gt_axis"] == "none"

    assert by_name["GT_EVAL_long_slot.json"]["use_kind"] == "metric"
    assert by_name["MUTATION_LONG_SLOT.json"]["use_kind"] == "structural"

    assert by_name["GT_EVAL_long_slot.json"]["action"] == "REAGGREGATE"
    assert by_name["LABEL_SUMMARY_m4.json"]["action"] == "KEEP only after TRACE"
    assert by_name["MUTATION_LONG_SLOT.json"]["action"] == "KEEP structural only"

    assert by_name["GT_EVAL_long_slot.json"]["prediction_sha"] == "a" * 64
    assert by_name["GT_EVAL_long_slot.json"]["source_song_split"] == "test"
    assert by_name["LABEL_SUMMARY_m4.json"]["source_song_split"] == "validation"
    assert by_name["LABEL_SUMMARY_m4.json"]["upstream_threshold_or_model_identity"] == "frozen-wp-v2"
    assert by_name["GT_EVAL_long_slot.json"]["gt_start_source"] == "synthetic_uniform_canonical"

    with open(out_dir / "HISTORICAL_GT_LINEAGE.csv", encoding="utf-8") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert len(csv_rows) == 3
    assert csv_rows[0]["artifact_path"] < csv_rows[1]["artifact_path"] < csv_rows[2]["artifact_path"]

    audit = json.loads((out_dir / "PRETRANSITION_GT_AUDIT.json").read_text(encoding="utf-8"))
    assert set(audit["categories"]) == EXPECTED_CATEGORIES
    assert sum(v["count"] for v in audit["categories"].values()) == 3
    assert audit["provenance_unknown_rows"] == []
    no_artifact = {n["category"] for n in audit["no_artifact_found"]}
    for cat, info in audit["categories"].items():
        assert info["count"] > 0 or cat in no_artifact
    assert len(audit["no_artifact_found"]) == len(EXPECTED_CATEGORIES) - 3

    manifest = json.loads((out_dir / "HISTORICAL_RERUN_MANIFEST.json").read_text(encoding="utf-8"))
    gt_entry = next(
        e for e in manifest["entries"] if e["artifact_path"].endswith("GT_EVAL_long_slot.json")
    )
    assert gt_entry["action"] == "REAGGREGATE"
    assert gt_entry["route"] == "cpu"
    assert gt_entry["priority"] == "P0"
