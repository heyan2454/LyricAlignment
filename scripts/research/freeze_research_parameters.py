#!/usr/bin/env python3
"""Freeze pilot-selected parameters before the all-data formal run.

The freeze is deliberately best-effort: incomplete or very small pilots produce
an explicit degraded/default parameter bundle instead of blocking the formal
run.  This preserves a final result while keeping its weaker evidential status
visible in provenance and reports.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.demo.run_state import atomic_json
from lyricalign.research_v6.detector import (
    DecisionStump, LogisticRiskModel, StumpBoostRiskModel, safe_boundary_score,
)


def best_threshold(curve: list[dict[str, Any]], *, max_fpr: float) -> dict[str, Any] | None:
    eligible = [
        row for row in curve
        if row.get("f1") is not None
        and (row.get("false_positive_rate") is None or float(row["false_positive_rate"]) <= max_fpr)
    ]
    if not eligible:
        eligible = [row for row in curve if row.get("f1") is not None]
    return max(
        eligible,
        key=lambda row: (
            float(row["f1"]),
            float(row.get("recall") or 0.0),
            -float(row.get("threshold") or 0.0),
        ),
    ) if eligible else None



def _threshold_grid(values: list[float], *, maximum_points: int = 65) -> list[float]:
    finite = sorted({float(value) for value in values if math.isfinite(float(value))})
    if not finite:
        return []
    if len(finite) <= maximum_points:
        return finite
    return sorted({
        finite[int(round(i * (len(finite) - 1) / (maximum_points - 1)))]
        for i in range(maximum_points)
    })


def _load_calibration_safe_features(
    root: Path, summary: dict[str, Any], split: dict[str, Any],
) -> list[dict[str, Any]]:
    calibration_groups = {str(value) for value in split.get("calibration_group_ids") or []}
    item_groups = {
        str(item.get("item_id")): str(item.get("source_song_id") or item.get("item_id"))
        for item in summary.get("items") or []
    }
    rows: list[dict[str, Any]] = []
    for item_id, source_song_id in item_groups.items():
        if calibration_groups and source_song_id not in calibration_groups:
            continue
        path = root / "items" / item_id / "E1_detector.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for source in payload.get("features") or []:
            if source.get("gt_safe_boundary") is None:
                continue
            rows.append(dict(source))
    return rows


def _risk_scorer(selected_name: str, model_payload: dict[str, Any] | None):
    if selected_name == "rule":
        return lambda row: float(row.get("rule_risk_score", row.get("risk_score", 0.0)))
    if selected_name == "logistic" and model_payload:
        model = LogisticRiskModel.from_dict(model_payload)
        return model.predict_score
    if selected_name == "stump_boost" and model_payload:
        model = StumpBoostRiskModel(
            float(model_payload["base_score"]),
            float(model_payload["learning_rate"]),
            [DecisionStump(**row) for row in model_payload["stumps"]],
        )
        return model.predict_score
    return None


def select_safe_boundary_joint_thresholds(
    rows: list[dict[str, Any]], *, selected_name: str,
    model_payload: dict[str, Any] | None, max_fpr: float,
) -> dict[str, Any] | None:
    scorer = _risk_scorer(selected_name, model_payload)
    if scorer is None:
        return None
    prepared = []
    for row in rows:
        risk = float(scorer(row))
        # Recompute evidence with the selected active risk score. Pilot item
        # files were initially scored by the rule detector, while formal may
        # freeze a learned detector; reusing the stored evidence would mix scales.
        evidence = float(safe_boundary_score(row, risk_score=risk))
        if not (math.isfinite(risk) and math.isfinite(evidence)):
            continue
        prepared.append((risk, evidence, bool(row["gt_safe_boundary"])))
    if not prepared:
        return None
    risk_grid = _threshold_grid([row[0] for row in prepared])
    evidence_grid = [value for value in _threshold_grid([row[1] for row in prepared]) if value > 0.0]
    if not evidence_grid:
        return None
    candidates = []
    for risk_ceiling in risk_grid:
        for evidence_threshold in evidence_grid:
            tp = fp = fn = tn = 0
            for risk, evidence, label in prepared:
                predicted = risk <= risk_ceiling and evidence >= evidence_threshold
                if predicted and label:
                    tp += 1
                elif predicted:
                    fp += 1
                elif label:
                    fn += 1
                else:
                    tn += 1
            precision = tp / (tp + fp) if tp + fp else None
            recall = tp / (tp + fn) if tp + fn else None
            f1 = (
                2.0 * precision * recall / (precision + recall)
                if precision is not None and recall is not None and precision + recall > 0.0
                else 0.0
            )
            fpr = fp / (fp + tn) if fp + tn else None
            candidates.append({
                "risk_ceiling": risk_ceiling,
                "evidence_threshold": evidence_threshold,
                "threshold": evidence_threshold,
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "precision": precision, "recall": recall, "f1": f1,
                "false_positive_rate": fpr,
                "calibration_unit_count": len(prepared),
            })
    eligible = [
        row for row in candidates
        if row["false_positive_rate"] is None or float(row["false_positive_rate"]) <= max_fpr
    ]
    pool = eligible or candidates
    return max(
        pool,
        key=lambda row: (
            float(row["f1"]),
            float(row.get("recall") or 0.0),
            -float(row.get("false_positive_rate") or 0.0),
            -float(row["risk_ceiling"]),
            float(row["evidence_threshold"]),
        ),
    ) if pool else None

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pilot-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-detector-fpr", type=float, default=0.10)
    p.add_argument("--prefer-model", choices=("logistic", "stump_boost", "rule"), default="logistic")
    return p


def _finite(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _curve(detector: dict[str, Any], model_name: str, kind: str) -> list[dict[str, Any]]:
    prefix = "stump" if model_name == "stump_boost" else model_name
    if kind == "risk":
        return list(detector.get(f"{prefix}_threshold_curve") or [])
    if kind == "repairable":
        return list(detector.get(f"{prefix}_repairable_threshold_curve") or [])
    if kind == "safe_boundary":
        return list(detector.get("safe_boundary_threshold_curve") or [])
    raise ValueError(kind)


def main() -> int:
    args = parser().parse_args()
    root = args.pilot_root.expanduser().resolve()
    summary_path = root / "research_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    complete = (
        json.loads((root / "complete.json").read_text(encoding="utf-8"))
        if (root / "complete.json").is_file() else {}
    )
    models = (
        json.loads((root / "detector_models.json").read_text(encoding="utf-8"))
        if (root / "detector_models.json").is_file() else {}
    )
    detector = summary.get("detector_summary", {}) or {}

    warnings: list[str] = []
    selected_name = args.prefer_model
    model = None
    if selected_name == "logistic":
        model = models.get("logistic")
    elif selected_name == "stump_boost":
        model = models.get("stump_boost")
    if selected_name != "rule" and model is None:
        warnings.append(f"preferred detector {selected_name} unavailable; fell back to rule")
        selected_name = "rule"

    selected_threshold = best_threshold(
        _curve(detector, selected_name, "risk"), max_fpr=args.max_detector_fpr,
    )
    if selected_threshold is None:
        warnings.append("no usable detector calibration curve; used conservative default threshold")
    selected_repairable_threshold = best_threshold(
        _curve(detector, selected_name, "repairable"), max_fpr=1.0,
    )
    if selected_repairable_threshold is None:
        warnings.append("no usable repairability curve; reused detector risk threshold")
    split = detector.get("data_split") or {}
    safe_calibration_rows = _load_calibration_safe_features(root, summary, split)
    selected_safe_boundary_threshold = select_safe_boundary_joint_thresholds(
        safe_calibration_rows,
        selected_name=selected_name,
        model_payload=model,
        max_fpr=args.max_detector_fpr,
    )
    if selected_safe_boundary_threshold is None:
        warnings.append(
            "no usable joint safe-boundary calibration; used default risk ceiling/evidence threshold 0.25"
        )

    risk_default = 0.5 if selected_name != "rule" else 1.0
    risk_threshold = _finite(
        None if selected_threshold is None else selected_threshold.get("threshold"), risk_default,
    )
    repairable_threshold = _finite(
        None if selected_repairable_threshold is None else selected_repairable_threshold.get("threshold"),
        risk_threshold,
    )
    safe_boundary_score_threshold = _finite(
        None if selected_safe_boundary_threshold is None else selected_safe_boundary_threshold.get("evidence_threshold"),
        0.25,
    )
    safe_risk_ceiling = _finite(
        None if selected_safe_boundary_threshold is None else selected_safe_boundary_threshold.get("risk_ceiling"),
        0.25,
    )

    decoder_summary = summary.get("decoder_summary", {}) or {}
    decoder_scores: list[dict[str, Any]] = []
    for name, data in decoder_summary.items():
        macro = (data.get("all") or {}).get("macro") or {}
        mae = macro.get("all_penalized_boundary_mae_sec")
        if mae is None:
            continue
        structural = data.get("structural_macro") or {}
        structural_total = sum(
            _finite(structural.get(key), 0.0)
            for key in (
                "negative_duration_count", "zero_duration_count",
                "inter_unit_overlap_count", "start_regression_count", "invalid_interval_count",
            )
        )
        decoder_scores.append({
            "decoder": name,
            "all_penalized_boundary_mae_sec": float(mae),
            "structural_anomaly_macro_sum": structural_total,
            "coverage": _finite(macro.get("coverage"), 0.0),
        })
    selected_decoder = min(
        decoder_scores,
        key=lambda row: (
            row["all_penalized_boundary_mae_sec"],
            row["structural_anomaly_macro_sum"],
            -row["coverage"],
            row["decoder"],
        ),
    )["decoder"] if decoder_scores else "official"
    if not decoder_scores:
        warnings.append("no usable decoder pilot metrics; defaulted to official")

    if split.get("degraded"):
        warnings.append(str(split.get("degraded_reason") or "detector split degraded"))
    if complete.get("status") == "partial_failure" or int(summary.get("failed_item_count", 0) or 0) > 0:
        warnings.append("pilot had item/phase failures; freeze used all available successful evidence")
    if int(detector.get("labelled_unit_count", 0) or 0) == 0:
        warnings.append("pilot had no labelled detector units")

    if not warnings:
        effectiveness = "normal_pilot_freeze"
    elif selected_threshold is not None or decoder_scores:
        effectiveness = "degraded_best_effort_freeze"
    else:
        effectiveness = "default_fallback_freeze"

    payload = {
        "schema_version": "alignment_research_frozen_parameters_v3_best_effort_joint_safe_boundary",
        "source_pilot_root": str(root),
        "selection_effectiveness": {
            "level": effectiveness,
            "warnings": warnings,
            "pilot_status": complete.get("status"),
            "selected_item_count": summary.get("selected_item_count"),
            "completed_item_count": summary.get("completed_item_count"),
            "failed_item_count": summary.get("failed_item_count"),
            "labelled_detector_unit_count": detector.get("labelled_unit_count", 0),
            "safe_boundary_calibration_unit_count": len(safe_calibration_rows),
            "detector_data_split": split,
            "formal_run_is_allowed": True,
        },
        "selection_policy": {
            "detector": f"max F1 under FPR<={args.max_detector_fpr}; fallback allowed",
            "repairability": "max F1 on pilot calibration; fallback to risk threshold",
            "safe_boundary": (
                f"joint calibration of active-risk ceiling and boundary-evidence threshold "
                f"under FPR<={args.max_detector_fpr}; fallback 0.25/0.25"
            ),
            "decoder": (
                "minimum pilot macro all-reference penalized MAE; then structural "
                "anomaly macro sum, coverage, deterministic name"
            ),
            "E8_candidate": (
                "fixed lexicographic detector policy: risk-span count, maximum risk, mean risk"
            ),
        },
        "selected_detector": selected_name,
        "selected_detector_threshold": selected_threshold,
        "selected_repairable_threshold": selected_repairable_threshold,
        "selected_safe_boundary_threshold": selected_safe_boundary_threshold,
        "detector_model": model if selected_name != "rule" else None,
        "selected_decoder": selected_decoder,
        "recommended_parameters": {
            "detector_model_threshold": risk_threshold if selected_name != "rule" else 0.5,
            "detector_risk_threshold": risk_threshold if selected_name == "rule" else 1.0,
            # Safe-boundary risk ceiling is calibrated separately from the
            # ordinary error-detection threshold.
            "detector_safe_threshold": safe_risk_ceiling,
            # This is the separate boundary-evidence threshold consumed by E5.
            "dynamic_safe_score": safe_boundary_score_threshold,
            "repairable_score_threshold": repairable_threshold,
        },
        "pilot_decoder_scores": decoder_scores,
    }
    atomic_json(args.output.expanduser().resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
