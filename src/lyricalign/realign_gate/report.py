"""05_report: aggregate 00-04 stage artifacts into FINAL_REPORT.md + FINAL_SUMMARY.json.

All numbers in the final report are read from the per-stage JSON/JSONL artifacts;
nothing is hard-coded here. Frozen baseline values (historical comparison) are read
from 01_detector_audit/RAW_UNIT_METRICS.json historical_bridge only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "realign_gate_05_final_summary_v1"

STAGE_FILES: dict[str, dict[str, str]] = {
    "00_inventory": {
        "DATA_INVENTORY": "00_inventory/DATA_INVENTORY.json",
    },
    "01_detector_audit": {
        "RAW_UNIT_METRICS": "01_detector_audit/RAW_UNIT_METRICS.json",
        "RAW_WINDOW_METRICS": "01_detector_audit/RAW_WINDOW_METRICS.json",
    },
    "02_behavior": {
        "CASES": "02_behavior/CASES.jsonl",
        "REQUESTS": "02_behavior/REQUESTS.jsonl",
        "CANDIDATE_INDEX": "02_behavior/CANDIDATE_INDEX.jsonl",
    },
    "03_gate": {
        "ANALYSIS": "03_gate/ANALYSIS.json",
        "GT_PAIR_METRICS": "03_gate/GT_PAIR_METRICS.jsonl",
        "NO_GT_FEATURES": "03_gate/NO_GT_FEATURES.jsonl",
    },
    "04_test_demo": {
        "TEST_DEMO_DETECTOR_SUMMARY": "04_test_demo/TEST_DEMO_DETECTOR_SUMMARY.json",
        "TEST_DEMO_REALIGN_BEHAVIOR": "04_test_demo/TEST_DEMO_REALIGN_BEHAVIOR.jsonl",
    },
}

_SECTION_HEADINGS = {
    "production_detector_audit": "## 1. Production Detector Audit",
    "gt_realign_behavior": "## 2. GT Realign Behavior",
    "no_gt_gate_signal": "## 3. No-GT Gate Signals",
    "test_demo_stress": "## 4. Test Demo Stress",
}

_ANALYSIS_FIELDS = [
    ("suggestion", "suggestion"),
    ("result_status", "result_status"),
    ("n_dev_rows", "splits.n_dev_rows"),
    ("n_holdout_rows", "splits.n_holdout_rows"),
    ("n_dev_songs", "splits.n_dev_songs"),
    ("n_holdout_songs", "splits.n_holdout_songs"),
    ("dev_auroc_delta", "metrics.dev.auroc_delta"),
    ("dev_auroc_nbig", "metrics.dev.auroc_nbig"),
    ("holdout_auroc_delta", "metrics.holdout.auroc_delta"),
    ("holdout_auroc_nbig", "metrics.holdout.auroc_nbig"),
    ("holdout_auprc_delta", "metrics.holdout.auprc_delta"),
    ("holdout_harm_rate", "metrics.holdout.harm_rate"),
    ("harmful_risk_writeback_holdout", "harmful_risk_writeback_holdout"),
    ("n_counterexamples", "n_counterexamples"),
    ("n_ambiguous", "n_ambiguous"),
    ("duplicate_keys", "duplicate_keys"),
]

_RAW_UNIT_FIELDS = [
    ("n_requests", "n_requests"),
    ("n_hits", "n_hits"),
    ("n_missing", "n_missing"),
    ("n_units", "tri_unit_metrics.pooled.n_units"),
    ("safe_accept_rate", "tri_unit_metrics.pooled.accept_ratio"),
    ("uncertain_ratio", "tri_unit_metrics.pooled.uncertain_ratio"),
    ("reject_ratio", "tri_unit_metrics.pooled.reject_ratio"),
    ("hist_safe_accept", "historical_bridge.frozen_val.safe_accept_rate"),
    ("hist_protected_recall", "historical_bridge.frozen_val.protected_recall_95"),
    ("hist_n", "historical_bridge.frozen_val.n_val_units"),
    ("retro_status", "historical_bridge.retrospective.status"),
    ("requested_limit", "requested_limit"),
    ("full_population_size", "full_population_size"),
    ("evaluated_count", "evaluated_count"),
    ("is_smoke", "is_smoke"),
    ("production_audit_complete", "production_audit_complete"),
]

_WINDOW_FIELDS = [
    ("n_windows", "interval_metrics.pooled.n_windows"),
    ("n_unsafe_windows", "interval_metrics.pooled.n_unsafe_windows"),
    ("unsafe_trigger_rate", "interval_metrics.pooled.unsafe_trigger_rate"),
    ("n_unsafe_intervals_total", "interval_metrics.pooled.n_unsafe_intervals_total"),
    ("requested_limit", "requested_limit"),
    ("full_population_size", "full_population_size"),
    ("evaluated_count", "evaluated_count"),
    ("is_smoke", "is_smoke"),
    ("production_audit_complete", "production_audit_complete"),
]

_INVENTORY_FIELDS = [
    ("n_songs", "real_gt_summary.n_songs"),
    ("n_accepted_units", "real_gt_summary.accepted_units"),
    ("n_unlabeled_total", "real_gt_summary.n_unlabeled_total"),
    ("n_constructible_windows", "constructible_windows.constructible_windows"),
    ("n_demo_items", "demo_summary.n_items"),
]

_DEMO_FIELDS = [
    ("n_items", "n_items"),
    ("n_failed", "n_failed"),
    ("no_gt", "no_gt"),
]


def _resolve_path(run_root: str | Path, rel_path: str) -> Path:
    p = Path(rel_path)
    if not p.is_absolute():
        p = Path(run_root) / p
    return p


def load_stage_json(run_root: str | Path, stage_file: str) -> Any:
    """Tolerant read of a stage artifact; returns None on missing/unparsable."""
    p = _resolve_path(run_root, stage_file)
    if not p.exists():
        return None
    try:
        with open(p) as f:
            if p.suffix == ".jsonl":
                rows = []
                for line in f:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
                return rows
            return json.load(f)
    except Exception:
        return None


def _get(d: Any, path: str, default: Any = None) -> Any:
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _summary_of(data: Any) -> dict:
    """Return the dict to read fields from.

    Real stage JSON files are flat (schema/inputs/generated_at/... at top level).
    Some early fixtures wrapped numbers under a "summary" key; prefer that when
    present, otherwise fall back to the whole dict.
    """
    if isinstance(data, dict):
        summary = data.get("summary")
        if isinstance(summary, dict):
            return summary
        return data
    return {}


def _fmt(v: Any, ndigits: int = 4) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float):
            return f"{v:.{ndigits}f}"
        return str(v)
    return str(v) if v is not None else "missing"


def _collect_field(data: Any, path: str) -> Any:
    return _get(_summary_of(data), path)


def _load_config(run_root: str | Path, cfg_path: str | None) -> dict:
    if cfg_path:
        cfg = load_stage_json(run_root, cfg_path)
    else:
        cfg = load_stage_json(run_root, "00_meta/CONFIG.json")
    return cfg if isinstance(cfg, dict) else {}


def _section_missing(stage_files: dict[str, str], data: dict[str, Any], run_root: str | Path) -> str:
    missing = [rel for rel, content in data.items() if content is None]
    if missing:
        return f" [incomplete: missing {', '.join(missing)}]"
    return ""


def _render_markdown(run_root: str | Path, sections: dict[str, dict], cfg: dict) -> str:
    constraints = _get(cfg, "constraints", {})
    actual_writeback = _get(constraints, "actual_writeback", 0)
    ident = _get(cfg, "frozen_identity", {})
    audit = sections["production_detector_audit"]
    smoke = bool(audit.get("smoke") or audit.get("is_smoke") or (audit.get("requested_limit") or 0) > 0)
    badge = "  **[SMOKE / PARTIAL — limited subset, NOT production conclusion]**" if smoke else ""
    lines: list[str] = []
    lines.append("# Detector Production Audit + Realign Gate — Final Report" + badge)
    lines.append("")
    lines.append(f"- run_root: `{run_root}`")
    lines.append(f"- generated_at_utc: {datetime.now(timezone.utc).isoformat()}")
    if smoke:
        requested_limit = audit.get("requested_limit")
        full_pop = audit.get("full_population_size")
        evaluated = audit.get("evaluated_count")
        lines.append(
            f"- **SMOKE/PARTIAL**: requested_limit={requested_limit}, "
            f"full_population_size={full_pop}, evaluated_count={evaluated}. "
            "This run must NOT be used to explain historical safe-accept "
            "or recovery-subset differences."
        )
    lines.append(
        f"- model: {_get(ident, 'model_id', 'missing')} @ {_get(ident, 'model_revision', 'missing')} "
        f"(checkpoint {_get(ident, 'checkpoint_id', 'missing')})"
    )
    lines.append(
        f"- detector: {_get(ident, 'detector_kind', 'missing')} "
        f"T_accept={_get(ident, 'T_accept', 'missing')} T_reject={_get(ident, 'T_reject', 'missing')}"
    )
    lines.append(
        f"- shadow-only run: actual_writeback={actual_writeback} "
        "(offline read-only; outputs are NOT stateful recovery / NOT written back)"
    )
    lines.append("")

    for section, heading in _SECTION_HEADINGS.items():
        lines.append(heading)
        lines.append("")
        s = sections[section]
        lines.append(f"status: {s.get('status', 'incomplete')}")
        for key, value in s.items():
            if key == "status" or value is None:
                continue
            lines.append(f"- {key}: {_fmt(value)}")
        lines.append("")

    lines.append("## Conclusion")
    lines.append("")
    conclusion = sections["conclusion"]
    lines.append(f"writeback gate: {conclusion.get('writeback_gate', 'incomplete')}")
    if conclusion.get("reason"):
        lines.append(f"reason: {conclusion['reason']}")
    if smoke:
        lines.append(
            "note: smoke/partial run — conclusion is preliminary only, "
            "NOT a production audit conclusion."
        )
    lines.append(f"actual_writeback={actual_writeback} (shadow, no writeback performed)")
    lines.append("")
    return "\n".join(lines)


def _conclusion(audit: dict, analysis: dict, cfg: dict) -> dict:
    holdout_weak = analysis.get("holdout_weak")
    harmful_risk = analysis.get("harmful_risk")
    decision = analysis.get("decision")
    if decision is None:
        return {"writeback_gate": "incomplete", "reason": "03_gate/ANALYSIS.json missing"}
    if analysis.get("status") not in (None, "ok"):
        return {
            "writeback_gate": "partial_incomplete",
            "reason": f"03_gate stage status={analysis.get('status')} — not a production conclusion",
        }
    reasons = []
    if holdout_weak is True:
        reasons.append("holdout signal weak (holdout_weak=true)")
    if harmful_risk is True:
        reasons.append("harmful risk present (harmful_risk=true)")
    if reasons:
        return {
            "writeback_gate": "NOT_FROZEN",
            "reason": "holdout 弱或 harmful risk 不可接受: " + "; ".join(reasons),
        }
    if decision and decision != "ACCEPT_WRITEBACK":
        return {
            "writeback_gate": "NOT_FROZEN",
            "reason": f"three-state decision is {decision}, not ACCEPT_WRITEBACK",
        }
    return {
        "writeback_gate": "eligible_for_review",
        "reason": "holdout 不弱且无 harmful risk；仍需人工确认后再冻结",
    }


def build_final_report(run_root: str | Path, *, cfg_path: str | None = None) -> dict:
    """Read 00-04 artifacts and build FINAL_REPORT.md + FINAL_SUMMARY.json content."""
    run_root = Path(run_root)
    cfg = _load_config(run_root, cfg_path)
    constraints = _get(cfg, "constraints", {})

    loaded: dict[str, dict[str, Any]] = {}
    for stage, files in STAGE_FILES.items():
        loaded[stage] = {}
        for key, rel in files.items():
            loaded[stage][key] = load_stage_json(run_root, rel)

    sections: dict[str, dict] = {}

    data00 = loaded["00_inventory"]["DATA_INVENTORY"]
    audit = {"status": "ok"}
    if data00 is not None:
        for key, path in _INVENTORY_FIELDS:
            audit[key] = _collect_field(data00, path)
    if data00 is None:
        audit["status"] = "incomplete"
    sections["production_detector_audit"] = audit

    raw_unit = loaded["01_detector_audit"]["RAW_UNIT_METRICS"]
    window = loaded["01_detector_audit"]["RAW_WINDOW_METRICS"]
    audit = dict(audit)
    if raw_unit is not None:
        for key, path in _RAW_UNIT_FIELDS:
            audit[key] = _collect_field(raw_unit, path)
    if window is not None:
        for key, path in _WINDOW_FIELDS:
            audit[key] = _collect_field(window, path)
    missing_audit = [
        rel
        for rel, content in {
            "RAW_UNIT_METRICS.json": raw_unit,
            "RAW_WINDOW_METRICS.json": window,
        }.items()
        if content is None
    ]
    if raw_unit is not None and isinstance(raw_unit, dict):
        audit_status = raw_unit.get("result_status")
    else:
        audit_status = None
    if audit_status in ("blocked", "incomplete"):
        audit["status"] = audit_status
    elif missing_audit or data00 is None:
        audit["status"] = "incomplete"
    audit["audit_result_status"] = audit_status
    audit["smoke"] = bool(audit.get("is_smoke") or (audit.get("requested_limit") or 0) > 0)
    audit["historical_bridge"] = (
        f"frozen_val safe_accept={audit.get('hist_safe_accept')} "
        f"protected_recall={audit.get('hist_protected_recall')} n={audit.get('hist_n')}; "
        f"retrospective={audit.get('retro_status')}"
        if audit.get("retro_status")
        else "missing"
    )
    sections["production_detector_audit"] = audit

    cases = loaded["02_behavior"]["CASES"]
    requests = loaded["02_behavior"]["REQUESTS"]
    cand_index = loaded["02_behavior"]["CANDIDATE_INDEX"]
    behavior = {"status": "ok"}
    if cases is not None:
        behavior["n_cases"] = len(cases)
    if requests is not None:
        behavior["n_requests"] = len(requests)
    if cand_index is not None:
        behavior["n_candidates"] = len(cand_index)
    missing_behavior = [
        rel
        for rel, content in {
            "CASES.jsonl": cases,
            "REQUESTS.jsonl": requests,
            "CANDIDATE_INDEX.jsonl": cand_index,
        }.items()
        if content is None
    ]
    if missing_behavior:
        behavior["status"] = "incomplete"
    behavior["_missing"] = missing_behavior
    sections["gt_realign_behavior"] = behavior

    analysis = loaded["03_gate"]["ANALYSIS"]
    gt_pairs = loaded["03_gate"]["GT_PAIR_METRICS"]
    no_gt = loaded["03_gate"]["NO_GT_FEATURES"]
    gate = {"status": "ok"}
    if analysis is not None:
        for key, path in _ANALYSIS_FIELDS:
            gate[key] = _collect_field(analysis, path)
    if analysis is not None:
        gate["decision"] = gate.get("suggestion")
        gate["holdout_weak"] = (
            gate.get("holdout_auroc_delta") is None or gate.get("holdout_auroc_delta") <= 0.5
        )
        gate["harmful_risk"] = (
            gate.get("harmful_risk_writeback_holdout") is not None
            and gate.get("harmful_risk_writeback_holdout") > 0.5
        )
    if gt_pairs is not None:
        gate["n_gt_pair_rows"] = len(gt_pairs)
        paired = [r for r in gt_pairs if isinstance(r, dict) and r.get("delta_error_ms") is not None]
        improve_n = sum(1 for r in paired if r.get("label") == "improve")
        harm_n = sum(1 for r in paired if r.get("label") == "harm")
        gate["n_paired_units"] = len(paired)
        gate["improve_n"] = improve_n
        gate["harm_n"] = harm_n
        gate["net_improved_count"] = improve_n - harm_n
        gate["net_improved_ratio"] = (
            (improve_n - harm_n) / len(paired) if paired else None
        )
        gate["neutral_n"] = sum(1 for r in paired if r.get("label") == "neutral")
    if no_gt is not None:
        gate["n_no_gt_rows"] = len(no_gt)
    missing_gate = [
        rel
        for rel, content in {
            "ANALYSIS.json": analysis,
            "GT_PAIR_METRICS.jsonl": gt_pairs,
            "NO_GT_FEATURES.jsonl": no_gt,
        }.items()
        if content is None
    ]
    if missing_gate:
        gate["status"] = "incomplete"
    elif analysis is not None and isinstance(analysis, dict):
        stage_status = analysis.get("stage_result_status")
        if stage_status not in (None, "ok"):
            gate["status"] = stage_status
        elif stage_status == "ok" and analysis.get("result_status") not in (None, "ok"):
            gate["status"] = analysis.get("result_status")
    if analysis is not None:
        gate["decision"] = gate.get("suggestion")
        gate["holdout_weak"] = (
            gate.get("holdout_auroc_delta") is None or gate.get("holdout_auroc_delta") <= 0.5
        )
        gate["harmful_risk"] = (
            gate.get("harmful_risk_writeback_holdout") is not None
            and gate.get("harmful_risk_writeback_holdout") > 0.5
        )
    sections["no_gt_gate_signal"] = gate

    demo_sum = loaded["04_test_demo"]["TEST_DEMO_DETECTOR_SUMMARY"]
    demo_behavior = loaded["04_test_demo"]["TEST_DEMO_REALIGN_BEHAVIOR"]
    demo = {"status": "ok"}
    if demo_sum is not None:
        for key, path in _DEMO_FIELDS:
            demo[key] = _collect_field(demo_sum, path)
    if demo_behavior is not None:
        demo["n_demo_requests"] = len(demo_behavior)
    missing_demo = [
        rel
        for rel, content in {
            "TEST_DEMO_DETECTOR_SUMMARY.json": demo_sum,
            "TEST_DEMO_REALIGN_BEHAVIOR.jsonl": demo_behavior,
        }.items()
        if content is None
    ]
    if missing_demo:
        demo["status"] = "incomplete"
    demo["_missing"] = missing_demo
    sections["test_demo_stress"] = demo

    conclusion = _conclusion(audit, gate, cfg)
    sections["conclusion"] = conclusion

    report_markdown = _render_markdown(run_root, sections, cfg)

    smoke = bool(audit.get("smoke") or audit.get("is_smoke") or (audit.get("requested_limit") or 0) > 0)
    all_ok = all(
        sections[name].get("status") == "ok"
        for name in (
            "production_detector_audit",
            "gt_realign_behavior",
            "no_gt_gate_signal",
            "test_demo_stress",
        )
    )
    if not all_ok:
        result_status = "incomplete"
    elif smoke:
        result_status = "ok_smoke_partial"
    else:
        result_status = "ok"
    summary: dict = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_root": str(run_root),
        "smoke": smoke,
        "requested_limit": audit.get("requested_limit"),
        "production_audit_complete": audit.get("production_audit_complete"),
        "constraints": {
            "actual_writeback": _get(constraints, "actual_writeback", 0),
            "no_gt_control": _get(constraints, "no_gt_control", True),
        },
        "sections": {
            "production_detector_audit": audit,
            "gt_realign_behavior": {
                k: v for k, v in behavior.items() if not k.startswith("_")
            },
            "no_gt_gate_signal": gate,
            "test_demo_stress": {k: v for k, v in demo.items() if not k.startswith("_")},
        },
        "conclusion": conclusion,
        "result_status": result_status,
    }
    return {"report_markdown": report_markdown, "final_summary": summary}


def run_stage(run_root: str | Path, cfg_path: str | None = None) -> dict:
    """Write 05_report/FINAL_REPORT.md + 05_report/FINAL_SUMMARY.json; return summary."""
    run_root = Path(run_root)
    result = build_final_report(run_root, cfg_path=cfg_path)
    out_dir = run_root / "05_report"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "FINAL_REPORT.md").write_text(result["report_markdown"], encoding="utf-8")
    (out_dir / "FINAL_SUMMARY.json").write_text(
        json.dumps(result["final_summary"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result["final_summary"]
