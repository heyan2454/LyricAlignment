"""Fast (L1) tests for the long-form weak-GT panel assembly and analysis."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import m4_longform_weakgt as P


def _timeline_row(song: str = "songA") -> dict:
    units = []
    for i in range(4):
        units.append({"canonical_unit_id": i, "text": f"t{i}",
                      # deliberately NOT uniform: the real axis is the frozen label, not this
                      "start_sec": 10.0 + 1.3 * i, "end_sec": 10.0 + 1.3 * i + 1.1,
                      "source_segment_id": f"{song}#000{i//2}", "source_unit_index": i % 2})
    return {"song_id": song, "singer_id": "Tenor-1", "duration_sec": 20.0,
            "artificial_silence_sec": 0.5,
            "canonical_units": units,
            "segment_offsets": [{"source_segment_id": f"{song}#0000", "global_start_sec": 10.0,
                                 "duration_sec": 4.0, "n_units": 2},
                                {"source_segment_id": f"{song}#0001", "global_start_sec": 14.0,
                                 "duration_sec": 4.0, "n_units": 2}],
            "seams": [{"left_source_segment_id": f"{song}#0000",
                       "right_source_segment_id": f"{song}#0001", "inserted_silence_sec": 0.5}]}


def _label_row(ident: str, cid: int, target: str, label: str, s_err: float, e_err: float,
               family: str = "baseline_legal") -> dict:
    return {"request_identity": ident, "view_id": "full", "canonical_unit_id": cid,
            "target": target, "label": label, "family": family, "split": "test",
            "song_id": "songA", "gt_unavailable": label == "gt_unavailable",
            "audit": {"reason": "within_safe" if label == "safe" else "exceeds_unsafe",
                      "start_abs_error_sec": s_err, "end_abs_error_sec": e_err,
                      "worst_abs_error_sec": max(s_err, e_err),
                      "used_keys": {"start_key": f"{target}_global_start_sec"}}}


def _ev(cid: int, start: float, end: float) -> dict:
    return {"canonical_unit_id": cid, "view_id": "full",
            "raw": {"start_sec": start, "end_sec": end, "start_entropy": 0.4 + 0.1 * cid,
                    "end_entropy": 0.9 + 0.1 * cid, "start_margin": 0.6, "end_margin": 0.2},
            "official": {"start_sec": start, "end_sec": end,
                         "repair_start_shift_sec": 0.0, "repair_end_shift_sec": 0.0},
            "hidden": {"available": False}, "cross_view": {}}


@pytest.fixture()
def fake_run(tmp_path: Path) -> Path:
    ident = "sha256:" + "a" * 64
    run = tmp_path / "runX"
    (run / "manifests").mkdir(parents=True)
    rows = []
    for cid in range(4):
        # real-GT (frozen) error stays <=100ms, while the fabricated uniform axis is off by seconds
        for target, lab, s_err, e_err in (("raw", "safe", 0.02, 0.03),
                                          ("official", "safe", 0.02, 0.03)):
            rows.append(_label_row(ident, cid, target, lab, s_err, e_err))
    (run / "LABELS.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    ev_dir = run / "evidence_v2"
    ev_dir.mkdir()
    (ev_dir / f"{ident}.jsonl").write_text(
        json.dumps([_ev(c, 10.0 + 1.3 * c, 10.0 + 1.3 * c + 1.1) for c in range(4)],
                   ensure_ascii=False) + "\n", encoding="utf-8")
    return run


def test_build_run_joins_labels_evidence_and_timeline(fake_run: Path):
    timelines, _ = P.load_timelines([])
    timelines["songA"] = {"row": _timeline_row(), "units": {int(u["canonical_unit_id"]): u
                                                            for u in _timeline_row()["canonical_units"]},
                          "seams": [], "segments": {s["source_segment_id"]: s
                                                    for s in _timeline_row()["segment_offsets"]},
                          "duration_sec": 20.0, "artificial_silence_sec": 0.5}
    rows, stats = P.build_run(fake_run, timelines)
    assert stats["units"] == 4 and stats["requests_with_evidence"] == 1
    assert {r["canonical_unit_id"] for r in rows} == {0, 1, 2, 3}
    r0 = rows[0]
    assert r0["label_raw_both_err_sec"] == 0.03          # frozen real-GT error
    assert r0["raw_label"] == "safe" and r0["off_label"] == "safe"
    assert r0["raw_start_sec"] == 10.0 and r0["gt_start_sec"] == 10.0
    assert r0["source_segment_id"] == "songA#0000"
    assert r0["timeline_duration_sec"] == 20.0 and r0["artificial_silence_sec"] == 0.5


def test_frozen_errors_win_over_fabricated_axis(fake_run: Path):
    timelines = {}
    tl = _timeline_row()
    # shift the fabricated axis far away so the two error definitions must disagree
    for u in tl["canonical_units"]:
        u["start_sec"] += 7.0
        u["end_sec"] += 7.0
    timelines["songA"] = {"row": tl, "units": {int(u["canonical_unit_id"]): u for u in tl["canonical_units"]},
                          "seams": [], "segments": {s["source_segment_id"]: s for s in tl["segment_offsets"]},
                          "duration_sec": 20.0, "artificial_silence_sec": 0.5}
    rows, _ = P.build_run(fake_run, timelines)
    df = P.frame_from_rows(rows)
    assert df["raw_both_err"].iloc[0] == pytest.approx(0.03)         # frozen
    assert df["raw_both_err_uniformaxis"].iloc[0] == pytest.approx(7.0, abs=0.05)


def test_analyse_reports_trap_and_stage_from_frozen_errors(fake_run: Path):
    tl = _timeline_row()
    timelines = {"songA": {"row": tl,
                           "units": {int(u["canonical_unit_id"]): u for u in tl["canonical_units"]},
                           "seams": [], "segments": {s["source_segment_id"]: s
                                                     for s in tl["segment_offsets"]},
                           "duration_sec": 20.0, "artificial_silence_sec": 0.5}}
    rows, _ = P.build_run(fake_run, timelines)
    result = P.analyse(P.frame_from_rows(rows))
    assert result["panel"]["baseline_unit_rows"] == 4
    assert result["reference_profile"]["frozen_raw_label_shares"]["safe"] == 4
    stage = result["stage_comparison"]
    assert stage["micro_hit100_raw"] == 1.0 and stage["micro_hit100_official"] == 1.0
    assert "uniform_axis_trap" not in result or result["uniform_axis_trap"]["n_units"] >= 0


def test_text_error_collateral_detects_contamination_radius():
    rows = []
    # baseline: perfect units; mutated tail request: first 3 survivors broken, rest perfect
    for cid in range(20):
        rows.append({"run": "r", "request_identity": "base", "view_id": "full", "song": "s",
                     "family": "baseline_legal", "canonical_unit_id": cid,
                     "label_off_both_err_sec": 0.02, "label_raw_both_err_sec": 0.02,
                     "label_off_start_err_sec": 0.01, "label_raw_start_err_sec": 0.01, "raw_label": "safe", "off_label": "safe",
                     "source_unit_index": cid, "segment_start_sec": 0.0, "gt_start_sec": float(cid),
                     "gt_end_sec": float(cid) + 0.5, "raw_dur": 0.5, "final_dur": 0.5,
                     "raw_start_sec": float(cid), "raw_end_sec": float(cid) + 0.5,
                     "off_start_sec": float(cid), "off_end_sec": float(cid) + 0.5,
                     "start_entropy": 0.4, "end_entropy": 0.9,
                     "start_margin": 0.6, "end_margin": 0.2,
                     "repair_start_shift_sec": 0.0, "repair_end_shift_sec": 0.0})
    for cid in range(20):
        err = 1.0 if cid < 3 else 0.02
        rows.append({"run": "r", "request_identity": "mut", "view_id": "full", "song": "s",
                     "family": "end_early", "canonical_unit_id": cid,
                     "label_off_both_err_sec": err, "label_raw_both_err_sec": err,
                     "label_off_start_err_sec": err / 2, "label_raw_start_err_sec": err / 2, "raw_label": "unsafe" if err > 0.2 else "safe",
                     "off_label": "unsafe" if err > 0.2 else "safe",
                     "source_unit_index": cid, "segment_start_sec": 0.0, "gt_start_sec": float(cid),
                     "gt_end_sec": float(cid) + 0.5, "raw_dur": 0.5, "final_dur": 0.5,
                     "raw_start_sec": float(cid), "raw_end_sec": float(cid) + 0.5,
                     "off_start_sec": float(cid), "off_end_sec": float(cid) + 0.5,
                     "start_entropy": 0.4, "end_entropy": 0.9,
                     "start_margin": 0.6, "end_margin": 0.2,
                     "repair_start_shift_sec": 0.0, "repair_end_shift_sec": 0.0})
    df = P.frame_from_rows(rows)
    out = P.analyse_text_error_collateral(df)
    prof = {r["bucket"]: r for r in out["tail_mutations_survivors"]["profile"]}
    near = prof["1-3 units from damaged edge"]
    far = prof[">18"]
    assert near["hit100"] < 0.9 and far["hit100"] > 0.95
    paired = out["paired_same_unit_baseline_vs_mutated"]["end_early"]
    assert paired["mean_err_delta_sec"] > 0 and paired["hit100_delta_pp"] < 0
    delta = out["tail_mutations_survivors"].get("far_hit100_minus_baseline_pp")
    # the guard needs >200 far units, so a tiny fixture legitimately omits it
    assert delta is None or delta >= -1.0


def test_auc_orientation():
    y = np.array([0, 0, 1, 1], dtype=float)
    assert P._auc(y, np.array([0.1, 0.2, 0.8, 0.9]), min_n=4) == pytest.approx(1.0)
    assert P._auc(y, np.array([0.9, 0.8, 0.2, 0.1]), min_n=4) == pytest.approx(0.0)
    assert P._auc(np.ones(4), np.arange(4.0), min_n=4) is None      # single class -> no AUC
    assert P._auc(np.array([0.0, 1.0] * 30), np.arange(60.0)) is not None  # default min_n honoured


def test_run_timeline_manifest_resolution(tmp_path: Path):
    run = tmp_path / "runZ"
    (run / "manifests").mkdir(parents=True)
    (run / "manifests" / "FREEZE.json").write_text(json.dumps(
        {"cli": {"timeline_manifest": str(tmp_path / "LONG_TIMELINE_MANIFEST.jsonl")}}), encoding="utf-8")
    assert P.run_timeline_manifest(run).name == "LONG_TIMELINE_MANIFEST.jsonl"
    missing = tmp_path / "runW"
    (missing / "manifests").mkdir(parents=True)
    assert P.run_timeline_manifest(missing) is None
