# -*- coding: utf-8 -*-
"""round08：baseline 质量与 GT 轴敏感性分析（analyze_long_slot_baseline_quality）单测。

纯内存 fixture：
- GT_EVAL（research_v7_gt_eval_v1）：2 首歌 × 3 窗 × full/sparse × baseline/missing 子集，
  行数已知 → 断言覆盖率分层表数值；
- 已知边界误差值的 rows（start/end 误差分布 + 阈值表，median/p90/p99/max 可手算）；
- 无 timeline → seam_strata 跳过；带 timeline + seams → 近/远分层正确；
- 带 evidence-dir → 特征 AUC 对已知判别特征返回 >0.5 的方向值；
- self_check：n_rows/n_units 与 GT_EVAL metrics 一致时 ok=True。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))

import analyze_long_slot_baseline_quality as m  # noqa: E402

UNSAFE = m.UNSAFE_THRESHOLD_SEC


def _row(rid, gci, cid, gt_s, gt_e, pred_s, pred_e, mut="baseline"):
    return {
        "global_character_index": gci, "canonical_unit_id": cid,
        "character": "x", "gt_start_sec": gt_s, "gt_end_sec": gt_e,
        "pred_start_sec": pred_s, "pred_end_sec": pred_e,
        "request_id": rid, "mutation_type": mut,
    }


def _per_request(rid, mut, n_rows, n_units, song="s1"):
    return {"request_id": rid, "mutation_type": mut, "song_id": song,
            "window_sec": [0.0, 60.0], "n_rows": n_rows,
            "n_units_evaluated": n_units}


def _gt_eval(per_request, rows, metrics=None):
    return {
        "schema": "research_v7_gt_eval_v1",
        "run_root": "/tmp/run",
        "gt_axis_note": "synthetic_uniform_timeline_axis (not human GT)",
        "metrics": metrics or {
            "n_decoder_rows": sum(r["n_rows"] for r in per_request),
            "n_units_evaluated": sum(r["n_units_evaluated"] for r in per_request),
        },
        "per_request": per_request,
        "rows": rows,
    }


def _make_gt_eval() -> dict:
    """覆盖率 fixture：s1 baseline full w0: 8/10；missing sparse w1: 4/5。

    行边界误差（start_err, end_err）固定：
    baseline 行: (0.1, 0.05) (0.2, 0.05) (0.3, 0.05) (0.4, 0.05)
                 (0.5, 0.05) (0.6, 0.05) (0.7, 0.05) (0.8, 0.05)
    missing 行:  (0.05, 0.3) (0.05, 0.5) (0.05, 1.2) (0.05, 5.5)
    """
    rows = []
    for i, se in enumerate((0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)):
        rows.append(_row("s1:w0:full", i, i, gt_s=float(i), gt_e=float(i + 1),
                         pred_s=float(i) + se, pred_e=float(i + 1) + 0.05))
    for i, ee in enumerate((0.3, 0.5, 1.2, 5.5)):
        rows.append(_row("s1:w1:sparse:missing", i, i, gt_s=float(i), gt_e=float(i + 1),
                         pred_s=float(i) + 0.05, pred_e=float(i + 1) + ee,
                         mut="missing"))
    per_request = [
        _per_request("s1:w0:full", "baseline", 8, 10),
        _per_request("s1:w1:sparse:missing", "missing", 4, 5),
    ]
    return _gt_eval(per_request, rows)


def _row_with_geometry(rid, gci, gt_s, gt_e, pred_s, pred_e, mut="baseline"):
    return _row(rid, gci, gci, gt_s, gt_e, pred_s, pred_e, mut)


def _evidence_row(gci, raw_start_sec, raw_end_sec, margin, entropy):
    return {
        "global_character_index": gci,
        "raw_start_sec": raw_start_sec, "raw_end_sec": raw_end_sec,
        "raw_global_start_sec": raw_start_sec, "raw_global_end_sec": raw_end_sec,
        "official_fixed_global_start_sec": raw_start_sec,
        "official_fixed_global_end_sec": raw_end_sec,
        "fixed_global_start_sec": raw_start_sec, "fixed_global_end_sec": raw_end_sec,
        "raw_start_margin": margin, "raw_end_margin": margin,
        "raw_start_entropy": entropy, "raw_end_entropy": entropy,
    }


def _write_evidence(tmp_path, rid, rows):
    d = tmp_path / "evidence"
    d.mkdir(exist_ok=True)
    (d / f"sha256:{rid.replace(':', '_')}.json").write_text(json.dumps({
        "content_identity": f"sha256:{rid}",
        "attempt": {
            "status": "ok",
            "request": {"request_id": rid},
            "decoder_outputs": {"official": {"rows": rows}},
        },
    }, ensure_ascii=False))


def test_coverage_table_values():
    gt = _make_gt_eval()
    res = m.analyze(gt)
    cov = res["coverage"]
    assert cov["overall"] == {"n_rows": 12, "n_units_evaluated": 15, "row_coverage": 0.8}
    assert cov["by_mutation"]["baseline"]["row_coverage"] == 0.8
    assert cov["by_mutation"]["missing"] == {"n_rows": 4, "n_units_evaluated": 5,
                                             "row_coverage": 0.8}
    assert cov["by_slot"]["full"]["row_coverage"] == 0.8
    assert cov["by_slot"]["sparse"]["row_coverage"] == 0.8
    assert cov["by_window"]["w0"]["row_coverage"] == 0.8
    assert cov["by_window"]["w1"] == {"n_rows": 4, "n_units_evaluated": 5,
                                      "row_coverage": 0.8}
    assert cov["by_mutation_slot_window"]["baseline|full|w0"]["n_rows"] == 8
    assert cov["by_mutation_slot_window"]["missing|sparse|w1"]["n_units_evaluated"] == 5
    assert cov["n_requests_unparsed_request_id"] == 0


def test_coverage_unparsed_request_id_isolated():
    rows = [_row("weird_id", 0, 0, 0.0, 1.0, 0.5, 1.5)]
    per_request = [_per_request("weird_id", "baseline", 1, 2)]
    res = m.analyze(_gt_eval(per_request, rows))
    cov = res["coverage"]
    assert cov["n_requests_unparsed_request_id"] == 1
    assert cov["overall"]["n_rows"] == 1
    assert res["self_check"]["ok"] is True


def test_boundary_error_distribution_and_thresholds():
    gt = _make_gt_eval()
    res = m.analyze(gt)
    be = res["boundary_error"]
    assert be["n_rows_with_geometry"] == 12
    assert be["n_rows_geometry_missing"] == 0
    start = sorted([0.05] * 4 + [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    end = sorted([0.05] * 8 + [0.3, 0.5, 1.2, 5.5])
    q = lambda s, x: s[min(len(s) - 1, int(x * len(s)))]  # noqa: E731
    assert be["by_boundary"]["start_abs_error_sec"]["median"] == q(start, 0.5)
    assert be["by_boundary"]["start_abs_error_sec"]["p90"] == q(start, 0.9)
    assert be["by_boundary"]["start_abs_error_sec"]["max"] == 0.8
    assert be["by_boundary"]["end_abs_error_sec"]["p99"] == q(end, 0.99)
    assert be["by_boundary"]["end_abs_error_sec"]["max"] == 5.5
    # either_max = max(start, end) 每行：baseline=start_err，missing=end_err
    either = sorted([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8] + [0.3, 0.5, 1.2, 5.5])
    assert be["by_boundary"]["either_max_abs_error_sec"]["median"] == q(either, 0.5)
    # 阈值表：start>0.25 = 6/12=0.5；end>0.25 = 4/12；either>0.25 = (6+4)/12
    t = be["thresholds"]
    assert t["0.25"]["exceed_rate"]["start"] == round(6 / 12, 4)
    assert t["0.25"]["exceed_rate"]["end"] == round(4 / 12, 4)
    assert t["0.25"]["exceed_rate"]["either"] == round(10 / 12, 4)
    assert t["0.5"]["exceed_rate"]["either"] == round(5 / 12, 4)
    assert t["1.0"]["exceed_rate"]["either"] == round(2 / 12, 4)
    assert t["2.0"]["exceed_rate"]["either"] == round(1 / 12, 4)
    assert t["5.0"]["exceed_rate"]["either"] == round(1 / 12, 4)
    assert t["0.25"]["n_exceed"]["either"] == 10
    # by_mutation：baseline either>0.25 = 6/8；missing = 4/4
    assert be["by_mutation"]["baseline"]["unsafe_rate_gt_0_25"] == round(6 / 8, 4)
    assert be["by_mutation"]["missing"]["unsafe_rate_gt_0_25"] == 1.0


def test_schema_and_self_check():
    gt = _make_gt_eval()
    res = m.analyze(gt)
    assert res["schema"] == "research_v7_baseline_quality_analysis_v1"
    assert list(res) == ["schema", "generated_at_utc", "inputs", "coverage",
                         "boundary_error", "axis_sensitivity", "seam_strata",
                         "feature_auc", "self_check"]
    assert res["seam_strata"] is None
    assert res["feature_auc"] is None
    sc = res["self_check"]
    assert sc["ok"] is True
    assert sc["counts"] == {"n_rows": 12, "n_units_evaluated": 15}
    assert sc["checks"]["n_rows_total_matches_metrics"] is True
    assert sc["checks"]["n_units_evaluated_matches_metrics"] is True


def test_self_check_fails_on_mismatched_metrics():
    gt = _make_gt_eval()
    gt["metrics"]["n_decoder_rows"] = 999
    res = m.analyze(gt)
    assert res["self_check"]["ok"] is False
    assert res["self_check"]["checks"]["n_rows_total_matches_metrics"] is False


def test_rows_with_missing_geometry_excluded():
    rows = [
        _row("s1:w0:full", 0, 0, 0.0, 1.0, 0.5, 1.5),
        _row("s1:w0:full", 1, 1, 0.0, 1.0, None, None),
    ]
    per_request = [_per_request("s1:w0:full", "baseline", 2, 2)]
    res = m.analyze(_gt_eval(per_request, rows))
    be = res["boundary_error"]
    assert be["n_rows_with_geometry"] == 1
    assert be["n_rows_geometry_missing"] == 1
    assert be["by_boundary"]["start_abs_error_sec"]["median"] == 0.5


def test_axis_sensitivity_hardcoded_reference():
    rows = [
        _row("s1:w0:full", 0, 0, 0.0, 1.0, 0.5, 1.5),
        _row("s1:w0:full", 1, 1, 0.0, 1.0, 1.0, 2.0),
    ]
    res = m.analyze(_gt_eval([_per_request("s1:w0:full", "baseline", 2, 2)], rows))
    ax = res["axis_sensitivity"]
    assert ax["m4_synthetic_axis"]["unsafe_rate_gt_0_25"] == 1.0
    assert ax["mir_weak_axis"]["unsafe_rate"] == round(592 / 4592, 4)
    assert ax["ratio_m4_over_mir"] == round(1.0 / (592 / 4592), 2)
    assert "GT 轴选择对 unsafe 率影响巨大" in ax["conclusion"]


def test_axis_sensitivity_from_cross_domain_eval():
    rows = [
        _row("s1:w0:full", 0, 0, 0.0, 1.0, 0.1, 1.1),
        _row("s1:w0:full", 1, 1, 0.0, 1.0, 2.0, 3.0),
    ]
    cross = {"mir1k": {"n_gt_unsafe_units": 10, "n_units_labeled": 100}}
    res = m.analyze(_gt_eval([_per_request("s1:w0:full", "baseline", 2, 2)], rows),
                    cross_domain_eval=cross)
    ax = res["axis_sensitivity"]
    assert ax["mir_weak_axis"]["unsafe_rate"] == 0.1
    assert ax["mir_weak_axis"]["source"].endswith("(provided)")
    assert ax["m4_synthetic_axis"]["unsafe_rate_gt_0_25"] == 0.5


def test_seam_strata_near_far(tmp_path):
    rows = [
        # gt 中心 0.5s：seam 在 0.5 -> near
        _row("s1:w0:full", 0, 0, 0.0, 1.0, 0.8, 1.8),
        # gt 中心 5.5s：距 seam(0.5) 5.0s -> far
        _row("s1:w0:full", 1, 1, 5.0, 6.0, 5.4, 6.4),
        # 无 seam 的 song -> 归入无 seam 计数
        _row("s2:w0:full", 0, 0, 0.0, 1.0, 0.2, 1.2),
    ]
    timeline = tmp_path / "LONG_TIMELINE_MANIFEST.jsonl"
    timeline.write_text(json.dumps({
        "song_id": "s1", "seams": [{"timeline_sec": 0.5}],
        "canonical_units": [{"canonical_unit_id": 0, "start_sec": 0.0, "end_sec": 1.0},
                            {"canonical_unit_id": 1, "start_sec": 5.0, "end_sec": 6.0}],
    }) + "\n" + json.dumps({"song_id": "s2", "seams": [],
                            "canonical_units": [{"canonical_unit_id": 0, "start_sec": 0.0,
                                                 "end_sec": 1.0}]}) + "\n")
    res = m.analyze(_gt_eval([_per_request("s1:w0:full", "baseline", 3, 3)], rows),
                    timeline_manifest=timeline)
    ss = res["seam_strata"]
    assert ss["n_rows_near_seam"] == 1
    assert ss["n_rows_far_from_seam"] == 1
    assert ss["n_rows_song_without_seams"] == 1
    assert ss["near_seam"]["unsafe_rate_gt_0_25"] == 1.0
    assert ss["far_from_seam"]["unsafe_rate_gt_0_25"] == 1.0
    assert ss["near_seam"]["median_seam_distance_sec"] == 0.0
    assert ss["far_from_seam"]["median_seam_distance_sec"] == 5.0


def test_feature_auc_joined(tmp_path):
    """raw_end_margin 高 -> 误差小（安全）：该特征 AUC < 0.5，方向正确且可判别。"""
    gt_rows = []
    ev_rows = []
    for i in range(10):
        margin = 0.9 if i % 2 == 0 else 0.05
        entropy = 0.2 if i % 2 == 0 else 2.5
        err = 0.1 if margin == 0.9 else 1.5  # 安全行误差 0.1，unsafe 行 1.5
        gt_rows.append(_row("s1:w0:full", i, i, gt_s=float(i), gt_e=float(i + 1),
                            pred_s=float(i) + err, pred_e=float(i + 1) + err))
        ev_rows.append(_evidence_row(i, float(i), float(i + 1), margin, entropy))
    _write_evidence(tmp_path, "s1:w0:full", ev_rows)
    res = m.analyze(_gt_eval([_per_request("s1:w0:full", "baseline", 10, 10)], gt_rows),
                    evidence_dir=tmp_path / "evidence")
    fa = res["feature_auc"]
    assert fa["n_rows_joined"] == 10
    assert fa["n_unsafe"] == 5
    assert fa["unsafe_rate_gt_0_25"] == 0.5
    assert fa["per_feature"]["raw_end_margin"]["auc"] < 0.5
    assert fa["per_feature"]["raw_end_entropy"]["auc"] > 0.5
    assert fa["per_feature"]["pred_duration_sec"]["auc"] == 0.5  # 时长无判别力
    assert fa["per_feature"]["either_max_boundary_error_sec"]["auc"] == 1.0
    assert "raw_start_margin" in fa["per_feature"]


def test_feature_auc_unjoined_rows_counted(tmp_path):
    gt_rows = [
        _row("s1:w0:full", 0, 0, 0.0, 1.0, 0.5, 1.5),
        _row("s1:w0:full", 1, 1, 0.0, 1.0, 0.5, 1.5),
    ]
    _write_evidence(tmp_path, "s1:w0:full", [_evidence_row(0, 0.0, 1.0, 0.9, 0.2)])
    res = m.analyze(_gt_eval([_per_request("s1:w0:full", "baseline", 2, 2)], gt_rows),
                    evidence_dir=tmp_path / "evidence")
    fa = res["feature_auc"]
    assert fa["n_rows_joined"] == 1
    assert fa["n_rows_not_joined"] == 1


def test_parse_request_id():
    assert m.parse_request_id("song:w2:sparse:missing") == {
        "song_id": "song", "window_index": 2, "slot_kind": "sparse"}
    assert m.parse_request_id("song:w0:full")["slot_kind"] == "full"
    assert m.parse_request_id("nonsense") is None


def test_main_writes_output(tmp_path):
    gt_path = tmp_path / "GT_EVAL.json"
    gt_path.write_text(json.dumps(_make_gt_eval(), ensure_ascii=False))
    out = tmp_path / "out"
    rc = m.main(["--gt-eval", str(gt_path), "--out", str(out)])
    assert rc == 0
    result = json.loads((out / "BASELINE_QUALITY_ANALYSIS.json").read_text(encoding="utf-8"))
    assert result["schema"] == "research_v7_baseline_quality_analysis_v1"
    assert result["coverage"]["overall"]["row_coverage"] == 0.8
