#!/usr/bin/env python3
"""Collect compact canonical metrics from the GTSinger GT deep-analysis artifacts.

Writes a small JSON into ``results/by_run/<name>/metrics.json`` (the git-tracked
metric source) rather than copying numbers by hand.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN_NAME = "20260912_gtsinger_gt_deep"


def pick(d: dict, *keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", type=Path,
                    default=Path(f"/home/hyan/Data/lyricalign/runs/{RUN_NAME}"))
    ap.add_argument("--results-root", type=Path, default=Path(__file__).resolve().parents[2] / "results")
    args = ap.parse_args()

    ad = args.analysis_dir
    j = {name: json.loads((ad / f"{name}.json").read_text(encoding="utf-8"))
         for name in ("SUMMARY", "ANALYSIS_SUMMARY", "EFFECTS", "SIGNALS", "STRUCTURE",
                      "MATRIX_AUDIT", "POSTPROCESS")}
    eff, sig, st, mx, pp = j["EFFECTS"], j["SIGNALS"], j["STRUCTURE"], j["MATRIX_AUDIT"], j["POSTPROCESS"]
    an, summ = j["ANALYSIS_SUMMARY"], j["SUMMARY"]

    levels = {f: {r[f]: r for r in eff["levels"][f]} for f in eff["levels"]}
    contrasts = eff["contrasts_hit100"]
    tab = sig["signals"]["all_configs"]
    gate = sig["gate_model"]
    diag = mx["per_run"].get("20260816_evaluation_v1_gtsinger_diag_all", {})
    cl = st.get("clustering_nulls", {})

    metrics = {
        "schema_version": "gtsinger_gt_deep_metrics_v1",
        "run": RUN_NAME,
        "source_evidence": summ.get("evidence"),
        "evidence_sha256": summ.get("evidence_sha256"),
        "metric_source_of_truth": str(ad),
        "panel": {
            "segments": an.get("panel_segments"), "items": an.get("panel_items"),
            "unit_rows": an.get("panel_rows"), "tolerances_sec": eff["tolerances_sec"],
            "singers": summ.get("singers"), "groups": summ.get("groups"),
        },
        "headline": {
            "config_matrix_is_degenerate": True,
            "labelled_configs_per_item": diag.get("configs_labelled_per_item_mean"),
            "distinct_prediction_vectors_per_item": diag.get("distinct_prediction_vectors_per_item_mean"),
            "mix_equals_vocal_audio_item_share": diag.get("share_items_mix_equals_vocal_audio"),
            "full_vs_windowed_start_identical_share": mx["mode_vs_full_start_identity"]["share_start_identical"],
            "official_minus_raw_hit100_pp": None if not contrasts["official_vs_raw"].get("available") else
            round(contrasts["official_vs_raw"]["mean_diff"] * 100, 3),
            "postprocess_damage_rate": pick(pp, "all_official", "touched", "damage_rate_both"),
            "postprocess_repair_rate": pick(pp, "all_official", "touched", "repair_rate_both"),
            "postprocess_mechanism_start_pinned_to_prev_end": pick(
                pp, "all_official", "mechanism", "start_moved", "share_pinned_to_prev_end"),
            "best_no_gt_single_signal_auc": max(
                (v["bad100"].get("flat_auc_oriented") or 0) for k, v in tab.items()
                if not k.startswith("oracle_")),
            "best_no_gt_gate_auc": pick(gate, "all_no_gt", "oof_auc"),
            "oracle_gate_auc_uses_gt": pick(gate, "oracle_reference_uses_gt", "oof_auc"),
            "bad_units_in_runs_ge2_observed": cl.get("share_bad_in_runs_ge2_observed"),
            "bad_units_in_runs_ge2_covariate_null": cl.get("share_bad_in_runs_ge2_nullB_mean"),
        },
        "hit100_macro_by_level": {f: {k: v.get("hit100_macro") for k, v in rows.items()}
                                  for f, rows in levels.items()},
        "detail_by_level": levels,
        "paired_contrasts_hit100": contrasts,
        "single_signal_auc_bad100": {k: {"oriented": v["bad100"].get("flat_auc_oriented"),
                                        "within_segment": v["bad100"].get(
                                            "within_segment_auc_mean_oriented"),
                                        "uses_gt": bool(v["bad100"].get("uses_gt"))}
                                    for k, v in tab.items()},
        "gate_models": {k: {kk: vv for kk, vv in v.items() if kk != "operating_points"}
                        for k, v in gate.items()},
        "calibration_top1": {k: {kk: vv for kk, vv in v.items() if kk != "reliability_deciles"}
                             for k, v in sig["calibration_top1"].items()},
        "error_structure": {
            "signed_bias": st["signed_bias"],
            "by_gt_duration": st["by_gt_duration"],
            "by_position_in_segment": st["by_position_in_segment"],
            "first_unit_analysis": st.get("first_unit_analysis"),
            "contagion": st.get("contagion"),
            "melisma_x_position_crosstab": st.get("melisma_x_position_crosstab"),
            "by_group": st["by_group"],
            "by_multi_phoneme": st["by_multi_phoneme"],
            "clustering": st["clustering"],
            "clustering_nulls": {k: v for k, v in cl.items() if k != "run_length_table"},
            "clustering_run_length_null_b": pick(cl, "run_length_table"),
        },
        "matrix_audit": {"per_run": mx["per_run"],
                         "mode_vs_full_start_identity": mx["mode_vs_full_start_identity"],
                         "mix_vs_vocal_start_identity": mx["mix_vs_vocal_start_identity"]},
        "postprocess": pp,
        "extraction_stats": summ["stats"],
    }
    out_dir = args.results_root / "by_run" / RUN_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "metrics.json"
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "bytes": out.stat().st_size,
                      "headline": metrics["headline"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
