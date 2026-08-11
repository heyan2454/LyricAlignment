"""Tests for audit_wp4_light_merge_before_after.py (WP4 reporter).

Uses tmp_path fixtures only; never reads real/large files.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts"
           / "research_transition_recovery_detector"
           / "audit_wp4_light_merge_before_after.py")
_SPEC = importlib.util.spec_from_file_location("audit_wp4_lmb", _SCRIPT)
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)

T_ACCEPT = 0.16546343952822562
T_REJECT = 0.16837782471409926


def _make_eval(t_accept=T_ACCEPT, t_reject=T_REJECT, n_train=100, n_test=50,
               combo="R", schema="research_v7_eval_v1",
               model_kind="standardized_logistic",
               protected_recall=0.8, safe_accept_rate=0.9,
               reject_recall=0.7):
    tm = {
        "n_unsafe_units": 10, "n_safe_units": 100, "n_grey_units": 0,
        "unsafe_false_accept_rate": 0.2, "reject_recall": reject_recall,
        "protected_recall": protected_recall, "safe_accept_rate": safe_accept_rate,
        "safe_reject_rate": 0.05, "safe_uncertain_rate": 0.05,
        "counts": {"unsafe_accept": 2, "unsafe_reject": 8, "unsafe_uncertain": 0,
                   "safe_accept": 90, "safe_reject": 5, "safe_uncertain": 5},
    }
    im = {
        "n_unsafe_intervals": 3, "reject_interval_recall_at_75": 0.6,
        "protected_interval_recall_at_75": 0.7,
        "reject_interval_recall_at_100": 0.6,
        "protected_interval_recall_at_100": 0.7,
        "n_long_unsafe_intervals": 2,
        "long_unsafe_interval_fully_accepted_rate": 0.0,
        "longest_consecutive_unsafe_accept_run": 1,
    }
    split = {
        "n_train": n_train, "n_test": n_test, "combo": combo,
        "model_kind": model_kind, "T_accept": t_accept, "T_reject": t_reject,
        "tri_unit_metrics": dict(tm), "interval_metrics": dict(im),
        "by_family": {
            "baseline": {"n_units": 50, "tri_unit_metrics": dict(tm),
                         "interval_metrics": dict(im)},
            "missing": {"n_units": 60, "tri_unit_metrics": dict(tm),
                        "interval_metrics": dict(im)},
        },
    }
    return {"schema": schema, "model_kind": model_kind,
            "targets": {"raw": split, "official": split}}


def _make_frozen():
    return {"raw": {"standardized_logistic": {"operating_points": {
                "T_accept": T_ACCEPT, "T_reject": T_REJECT}}},
            "official": {"standardized_logistic": {"operating_points": {
                "T_accept": T_ACCEPT, "T_reject": T_REJECT}}}}


def test_gate_passes_only_postprocess_changed():
    before = _make_eval(protected_recall=0.7, safe_accept_rate=0.8)
    after = _make_eval(protected_recall=0.9, safe_accept_rate=0.95)
    status, checks, mismatches = MOD.gate_checks(before, after, _make_frozen())
    assert status == MOD.STATUS_FIX
    assert mismatches == []
    assert len(checks) >= 10


def test_mismatched_threshold_fails_closed():
    before = _make_eval()
    after = _make_eval(t_accept=T_ACCEPT + 0.01)
    status, checks, mismatches = MOD.gate_checks(before, after, _make_frozen())
    assert status == MOD.STATUS_FAIL
    assert any("T_accept" in m[0] for m in mismatches)


def test_mismatched_frozen_threshold_fails_closed():
    before = _make_eval()
    after = _make_eval()
    frozen = _make_frozen()
    frozen["raw"]["standardized_logistic"]["operating_points"]["T_accept"] = 0.2
    status, _, mismatches = MOD.gate_checks(before, after, frozen)
    assert status == MOD.STATUS_FAIL
    assert any("frozen.raw.T_accept" in m[0] for m in mismatches)


def test_mismatched_cohort_fails_closed():
    before = _make_eval(n_train=100)
    after = _make_eval(n_train=999)
    status, _, mismatches = MOD.gate_checks(before, after, _make_frozen())
    assert status == MOD.STATUS_FAIL
    assert any("raw.n_train" in m[0] for m in mismatches)


def test_known_threshold_counts_and_rejected_island(tmp_path):
    before = _make_eval()
    after = _make_eval()
    labels = tmp_path / "LABELS.jsonl"
    labels.write_text(json.dumps({
        "request_identity": "sha256:x", "target": "raw", "label": "unsafe",
        "family": "missing", "split": "test", "song_id": "songA"}) + "\n" +
        json.dumps({
            "request_identity": "sha256:y", "target": "raw", "label": "safe",
            "family": "baseline", "split": "test", "song_id": "songB"}) + "\n")
    summary = MOD.build_detector_summary(
        {"M4_SONG_HELDOUT": before, "FAMILY_LOO": _make_eval()},
        {"M4_SONG_HELDOUT": after, "FAMILY_LOO": _make_eval()},
        _make_frozen(), str(labels))
    s = summary["summaries"]["M4_SONG_HELDOUT"]
    raw = s["after"]["raw"]["unit_metrics"]
    assert raw["protected_recall"] == 0.8          # 8/10 unsafe rejected
    assert raw["safe_accept_rate"] == 0.9          # 90/100 safe accepted
    assert raw["n_unsafe_intervals"] == 3          # rejected island passes through
    assert raw["protected_interval_recall_at_100"] == 0.7
    assert summary["per_song_units"]["n_rows"] == 2
    assert {r["song_id"] for r in summary["per_song_units"]["per_song"]} == \
        {"songA", "songB"}


def test_fail_closed_writer(tmp_path):
    args = _Args(before=tmp_path / "before.json",
                 after=tmp_path / "after.json",
                 frozen=tmp_path / "frozen.json",
                 labels=tmp_path / "labels.jsonl",
                 window_report=tmp_path / "nope.json",
                 rerun_90=tmp_path / "nope.jsonl",
                 scores_dir=tmp_path / "no_evidence",
                 scores_jsonl=tmp_path / "nope.jsonl",
                 out=tmp_path / "out")
    args.before.write_text(json.dumps(_make_eval()))
    args.after.write_text(json.dumps(_make_eval(t_accept=0.2)))
    args.frozen.write_text(json.dumps(_make_frozen()))
    args.labels.write_text("")
    MOD.run(args)
    doc = json.loads((args.out / "corrected_detector_summary.json").read_text())
    assert doc["result_status"] == MOD.STATUS_FAIL
    assert "gate fail_closed" in doc["error"]


def test_song_failure_concentration_from_labels_fixture(tmp_path):
    rows = []
    # songA -> cohort A, raw/baseline: 4 unsafe, 1 safe, 1 grey
    for label in (["unsafe"] * 4 + ["safe", "grey"]):
        rows.append({"song_id": "songA", "target": "raw", "family": "baseline",
                     "label": label})
    # songA -> raw/missing: 2 unsafe
    rows.append({"song_id": "songA", "target": "raw", "family": "missing",
                 "label": "unsafe"})
    rows.append({"song_id": "songA", "target": "raw", "family": "missing",
                 "label": "unsafe"})
    # songB -> cohort B, raw/baseline: 2 unsafe
    rows.append({"song_id": "songB", "target": "raw", "family": "baseline",
                 "label": "unsafe"})
    rows.append({"song_id": "songB", "target": "raw", "family": "baseline",
                 "label": "unsafe"})
    # songB -> raw/missing: 1 safe, no unsafe
    rows.append({"song_id": "songB", "target": "raw", "family": "missing",
                 "label": "safe"})
    # gt_unavailable must be excluded from n_labeled
    rows.append({"song_id": "songA", "target": "raw", "family": "baseline",
                 "label": "gt_unavailable"})
    # official target: songA 1 unsafe, songB 3 unsafe
    rows.append({"song_id": "songA", "target": "official", "family": "baseline",
                 "label": "unsafe"})
    rows.append({"song_id": "songB", "target": "official", "family": "baseline",
                 "label": "unsafe"})
    rows.append({"song_id": "songB", "target": "official", "family": "baseline",
                 "label": "unsafe"})
    rows.append({"song_id": "songB", "target": "official", "family": "baseline",
                 "label": "unsafe"})
    # songC joins neither cohort -> not_available_cohort_identity
    rows.append({"song_id": "songC", "target": "official", "family": "baseline",
                 "label": "unsafe"})

    by_id = {}
    out, meta = MOD.song_failure_concentration_from_labels(
        rows, {"songA"}, {"songB"})
    for r in out:
        by_id[(r["cohort"], r["target"], r["song_id"], r["family"])] = r

    raw_a_base = by_id[("A", "raw", "songA", "baseline")]
    assert raw_a_base["n_labeled"] == 6          # 4 unsafe + 1 safe + 1 grey
    assert raw_a_base["n_safe"] == 1
    assert raw_a_base["n_grey"] == 1
    assert raw_a_base["n_unsafe"] == 4
    assert raw_a_base["n_gt_unavailable"] == 1   # excluded from n_labeled
    assert raw_a_base["unsafe_fraction"] == 4 / 6
    assert raw_a_base["share_of_target_all_unsafe"] == 4 / 8

    raw_b_miss = by_id[("B", "raw", "songB", "missing")]
    assert raw_b_miss["n_labeled"] == 1
    assert raw_b_miss["n_unsafe"] == 0
    assert raw_b_miss["share_of_target_all_unsafe"] == 0.0

    # per-target sort: share DESC, song_id, family; cumulative accumulates
    raw_order = [(r["song_id"], r["family"]) for r in out
                 if r["target"] == "raw"]
    assert raw_order == [("songA", "baseline"), ("songA", "missing"),
                         ("songB", "baseline"), ("songB", "missing")]
    cums = [r["cumulative_unsafe_share"] for r in out
            if r["target"] == "raw"]
    assert abs(cums[0] - 0.5) < 1e-9
    assert abs(cums[1] - 0.75) < 1e-9
    assert abs(cums[2] - 1.0) < 1e-9
    assert abs(cums[3] - 1.0) < 1e-9

    off_order = [(r["song_id"], r["family"]) for r in out
                 if r["target"] == "official"]
    assert off_order == [("songB", "baseline"), ("songA", "baseline"),
                         ("songC", "baseline")]
    assert abs(out[len(out) - 1]["cumulative_unsafe_share"] - 1.0) < 1e-9
    assert by_id[("not_available_cohort_identity", "official", "songC",
                  "baseline")]["cohort"] == \
        MOD.COHORT_NA
    assert meta["detector_decision_status"] == "not_available"
    assert meta["n_rows"] == len(rows)


def test_song_failure_concentration_csv_columns(tmp_path):
    rows = [{"song_id": "songA", "target": "raw", "family": "baseline",
             "label": "unsafe"},
            {"song_id": "songB", "target": "official", "family": "missing",
             "label": "safe"}]
    out, _ = MOD.song_failure_concentration_from_labels(rows, {"songA"}, {})
    csv_path = tmp_path / "song_failure_concentration.csv"
    MOD.write_csv(csv_path, MOD.SFC_CSV_COLUMNS, out)
    header = csv_path.read_text().splitlines()[0]
    for col in ("cohort", "target", "song_id", "family", "n_labeled", "n_safe",
                "n_grey", "n_unsafe", "unsafe_fraction",
                "share_of_target_all_unsafe", "cumulative_unsafe_share"):
        assert col in header


class _Args:
    _DEFAULTS = {
        "cohort_a_formal": "/tmp/opencode/COHORT_A_FORMAL.jsonl",
        "cohort_a_diag": "/tmp/opencode/COHORT_A_DIAGNOSTIC.jsonl",
        "cohort_b_dev": "/tmp/opencode/COHORT_B_DEVELOPMENT.jsonl",
    }

    def __init__(self, **kw):
        merged = dict(self._DEFAULTS)
        merged.update(kw)
        self.__dict__.update(merged)
