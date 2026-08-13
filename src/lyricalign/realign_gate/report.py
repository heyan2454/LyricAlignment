"""05_report: aggregate 00-04 stage artifacts into FINAL_REPORT.md + FINAL_SUMMARY.json.

All numbers in the final report are read from the per-stage JSON/JSONL artifacts;
nothing is hard-coded here. Frozen baseline values (historical comparison) are read
from 01_detector_audit/RAW_UNIT_METRICS.json historical_bridge only.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "realign_gate_05_final_summary_v1"

PRODUCTION_POPULATION_KIND = "production_raw_baseline"
REQUIRED_VARIANTS = ("R-A", "R-B")


def _variant_kind(variant: str | None) -> str:
    """Map a concrete variant name to its R-A/R-B kind for pairing checks.

    Candidate index stores full names (``R-A_unsafe_old_range`` /
    ``R-B_safe_anchor_bounded``); pairing completeness only cares about the
    family prefix so report can validate both legacy short names and long ones.
    """
    if not variant:
        return ""
    v = str(variant)
    for kind in ("R-A", "R-B"):
        if v.startswith(kind):
            return kind
    return v
PAIRED_DEFINITION = {
    "gt_pair_schema": "realign_gate_gt_pair_metrics_v1",
    "no_gt_schema": "realign_gate_no_gt_features_v1",
    "neutral_eps_ms": 200.0,
}

BASELINE_FILES = {
    "BASELINE_WINDOW_INDEX": "00_inventory/BASELINE_WINDOW_INDEX.jsonl",
    "BASELINE_UNITS": "00_inventory/BASELINE_UNITS.jsonl",
    "BASELINE_DETECTOR_SHADOW": "00_inventory/BASELINE_DETECTOR_SHADOW.jsonl",
}

STAGE_FILES: dict[str, dict[str, str]] = {
    "00_inventory": {
        "DATA_INVENTORY": "00_inventory/DATA_INVENTORY.json",
        "BASELINE_WINDOW_INDEX": "00_inventory/BASELINE_WINDOW_INDEX.jsonl",
        "BASELINE_UNITS": "00_inventory/BASELINE_UNITS.jsonl",
        "BASELINE_DETECTOR_SHADOW": "00_inventory/BASELINE_DETECTOR_SHADOW.jsonl",
    },
    "01_detector_audit": {
        "RAW_UNIT_METRICS": "01_detector_audit/RAW_UNIT_METRICS.json",
        "RAW_WINDOW_METRICS": "01_detector_audit/RAW_WINDOW_METRICS.json",
    },
    "02_behavior": {
        "CASES": "02_behavior/CASES.jsonl",
        "REQUESTS": "02_behavior/REQUESTS.jsonl",
        "CANDIDATE_INDEX": "02_behavior/CANDIDATE_INDEX.jsonl",
        "SKIPPED_CASES": "02_behavior/SKIPPED_CASES.jsonl",
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
    ("accept_ratio", "tri_unit_metrics.pooled.accept_ratio"),
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
    if conclusion.get("writeback_gate") == "stage_ineligible":
        lines.append("")
        lines.append("**diagnostic-only — staged admission failed. Next-round rebuild inputs:**")
        for item in conclusion.get("rebuild_inputs", []):
            lines.append(
                f"- [{item.get('stage')}::{item.get('artifact')}] "
                f"required: {item.get('required')} — {item.get('action')}"
            )
        lines.append("")
    if smoke:
        lines.append(
            "note: smoke/partial run — conclusion is preliminary only, "
            "NOT a production audit conclusion."
        )
    lines.append(f"actual_writeback={actual_writeback} (shadow, no writeback performed)")
    lines.append("")
    return "\n".join(lines)


def _conclusion(audit: dict, analysis: dict, cfg: dict) -> dict:
    # This research branch is shadow-only.  A report can never graduate an
    # offline GT evaluation into a production writeback decision.
    if analysis.get("suggestion") == "DIAGNOSTIC_ONLY_NO_WRITEBACK":
        return {
            "writeback_gate": "NOT_FROZEN",
            "reason": "candidate gate is diagnostic-only; actual_writeback remains 0",
        }
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
    return {
        "writeback_gate": "NOT_FROZEN",
        "reason": "legacy gate result is not an authorization for writeback",
    }


def _check_stage_eligibility(
    run_root: str | Path, loaded: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict], list[dict]]:
    """B14 staged admission: P0/P2/P3 + paired-definition version checks.

    Returns (stage_checks, rebuild_inputs). Each check dict has
    ``eligible`` / ``blockers``; p2 also carries ``warning``. Any blocker or
    p2-warning degrades the corresponding stage to ineligible (diagnostic-only).
    """
    checks: dict[str, dict] = {
        "p0": {"eligible": True, "blockers": []},
        "p2": {"eligible": True, "blockers": [], "warning": []},
        "p3": {"eligible": True, "blockers": []},
        "paired_definition": {"eligible": True, "blockers": []},
    }
    rebuild: list[dict] = []

    def _add_rebuild(stage: str, artifact: str, required: str, action: str) -> None:
        rebuild.append(
            {
                "stage": stage,
                "artifact": artifact,
                "required": required,
                "action": action,
            }
        )

    data00 = loaded["00_inventory"]["DATA_INVENTORY"]
    raw_unit = loaded["01_detector_audit"]["RAW_UNIT_METRICS"]

    # ---- P0: production raw-baseline population + unique baseline window ----
    pop_kind = _get(raw_unit, "population_kind") if isinstance(raw_unit, dict) else None
    if pop_kind != PRODUCTION_POPULATION_KIND:
        checks["p0"]["blockers"].append(
            f"01 RAW_UNIT_METRICS population_kind={pop_kind!r} != "
            f"{PRODUCTION_POPULATION_KIND!r} (E5 proposal bank / non-baseline 输入被拒)"
        )
        checks["p0"]["eligible"] = False
        _add_rebuild(
            "01_detector_audit",
            "RAW_UNIT_METRICS.json",
            "population_kind == production_raw_baseline",
            "以 BASELINE_WINDOW_INDEX 重建 raw baseline shadow；禁止把 E5 proposal bank 当作 population",
        )
    for key, rel in BASELINE_FILES.items():
        content = loaded["00_inventory"].get(key)
        if content is None:
            checks["p0"]["blockers"].append(f"00_inventory {rel} 缺失/不可解析")
            checks["p0"]["eligible"] = False
            _add_rebuild(
                "00_inventory",
                rel,
                f"{key} 齐全",
                "补跑 P0：按 cohort manifest 的 60s stride/10s overlap 构造唯一 (song_id, window_id) 表并产出 shadow",
            )
        elif key == "BASELINE_WINDOW_INDEX":
            seen = set()
            dups = []
            for row in content:
                if not isinstance(row, dict):
                    continue
                key_pair = (str(row.get("song_id")), str(row.get("window_id")))
                if key_pair in seen:
                    dups.append(key_pair)
                seen.add(key_pair)
            if dups:
                checks["p0"]["blockers"].append(
                    f"BASELINE_WINDOW_INDEX (song_id, window_id) 重复: {dups[:5]}"
                )
                checks["p0"]["eligible"] = False
                _add_rebuild(
                    "00_inventory",
                    "BASELINE_WINDOW_INDEX.jsonl",
                    "(song_id, window_id) 唯一",
                    "去重后重建 BASELINE_WINDOW_INDEX",
                )

    # ---- P2: per-case R-A/R-B pairing + no skipped + unique (case_id, variant) ----
    cand_index = loaded["02_behavior"]["CANDIDATE_INDEX"]
    cases = loaded["02_behavior"]["CASES"]
    if cand_index is None:
        checks["p2"]["blockers"].append("02_behavior/CANDIDATE_INDEX.jsonl 缺失/不可解析")
        checks["p2"]["eligible"] = False
        _add_rebuild(
            "02_behavior",
            "CANDIDATE_INDEX.jsonl",
            "candidate index 齐全",
            "重跑 02 并生成 CANDIDATE_INDEX（含 case_id/variant/content_idn）",
        )
    else:
        pairs: list[tuple[str, str]] = []
        for row in cand_index:
            if not isinstance(row, dict):
                continue
            case_id = row.get("case_id")
            variant = row.get("variant")
            if case_id is None or variant is None:
                continue
            pairs.append((str(case_id), str(variant)))
        dup_pairs = [k for k, c in Counter(pairs).items() if c > 1]
        if dup_pairs:
            checks["p2"]["blockers"].append(f"CANDIDATE_INDEX 重复 (case_id, variant): {dup_pairs[:5]}")
            checks["p2"]["eligible"] = False
            _add_rebuild(
                "02_behavior",
                "CANDIDATE_INDEX.jsonl",
                "(case_id, variant) 唯一",
                "修正 candidate 配对后重建 index",
            )
        case_ids: set[str] = set()
        if isinstance(cases, list):
            case_ids = {str(c.get("case_id")) for c in cases if isinstance(c, dict) and c.get("case_id") is not None}
        if not case_ids:
            case_ids = {c for c, _ in pairs}
        skipped_ids: set[str] = set()
        skipped_rows = loaded["02_behavior"].get("SKIPPED_CASES")
        if isinstance(skipped_rows, list):
            skipped_ids = {
                str(r.get("case_id"))
                for r in skipped_rows
                if isinstance(r, dict) and r.get("case_id") is not None
            }
        if skipped_ids:
            checks["p2"]["warning"].append(
                f"SKIPPED_CASES={len(skipped_ids)}（设计内安全窗/不可构造 case，不要求配对）"
            )
        variants_by_case: dict[str, set[str]] = {}
        for c, v in pairs:
            variants_by_case.setdefault(c, set()).add(_variant_kind(v))
        missing = []
        for cid in sorted(case_ids - skipped_ids):
            for req in REQUIRED_VARIANTS:
                if req not in variants_by_case.get(cid, set()):
                    missing.append((cid, req))
        if missing:
            checks["p2"]["blockers"].append(
                f"每 case 需 R-A/R-B 配对完整，缺失: {missing[:5]}"
            )
            checks["p2"]["eligible"] = False
            _add_rebuild(
                "02_behavior",
                "CASES.jsonl / CANDIDATE_INDEX.jsonl",
                "每 case R-A 与 R-B 均完整",
                "补齐缺失 variant 的 request/evidence；不可构造 R-A 的 case 回 P1 补抽，不得只跑 R-B",
            )

    # ---- P3: feature/GT completeness + duplicates + label gap + real-GT coverage ----
    no_gt = loaded["03_gate"]["NO_GT_FEATURES"]
    gt_pairs = loaded["03_gate"]["GT_PAIR_METRICS"]
    if isinstance(no_gt, list):
        invalid = [
            r for r in no_gt if isinstance(r, dict) and r.get("feature_valid") is False
        ]
        if invalid:
            checks["p3"]["blockers"].append(
                f"NO_GT_FEATURES 有 {len(invalid)} 行 feature_valid=False"
            )
            checks["p3"]["eligible"] = False
            _add_rebuild(
                "03_gate",
                "NO_GT_FEATURES.jsonl",
                "无 feature_valid=False 行",
                "修复特征计算/输入对齐后重跑 03 no-GT features",
            )
    if isinstance(gt_pairs, list):
        seen = set()
        dups = []
        no_label = []
        for r in gt_pairs:
            if not isinstance(r, dict):
                continue
            key = (str(r.get("case_id")), str(r.get("variant")), str(r.get("canonical_unit_id")))
            if key in seen:
                dups.append(key)
            seen.add(key)
            if r.get("label") in (None, "", "missing"):
                # extra_prediction 行是 GT annotations 中不存在的 unit（GT 缺口），
                # 无法配对评价，非"缺标签"；new_missing 行是 design 内"本轮未覆盖"。
                # 两者都不应作为 p3 的 label 缺口。
                if not r.get("new_missing") and not r.get("extra_prediction"):
                    no_label.append(key)
        if dups:
            checks["p3"]["blockers"].append(f"GT_PAIR_METRICS 重复 key (case_id, variant, cid): {dups[:5]}")
            checks["p3"]["eligible"] = False
            _add_rebuild(
                "03_gate",
                "GT_PAIR_METRICS.jsonl",
                "无 duplicate key",
                "去重后重算 GT pair 指标",
            )
        if no_label:
            checks["p3"]["blockers"].append(f"GT_PAIR_METRICS 标签缺口 {len(no_label)} 行: {no_label[:5]}")
            checks["p3"]["eligible"] = False
            _add_rebuild(
                "03_gate",
                "GT_PAIR_METRICS.jsonl",
                "无 missing label",
                "补齐 GT label 或排除无标签样本后重跑 paired",
            )
    if isinstance(data00, dict):
        summary = _summary_of(data00)
        missing_gt_songs = _get(summary, "real_gt_summary.songs_missing_gt")
        if isinstance(missing_gt_songs, list) and missing_gt_songs:
            checks["p3"]["blockers"].append(
                f"real-GT 缺失 song: {missing_gt_songs}"
            )
            checks["p3"]["eligible"] = False
            _add_rebuild(
                "00_inventory",
                "DATA_INVENTORY.json",
                "GT 覆盖完整",
                "补充缺失 song 的 real-GT 或将其明确移出生产评价",
            )

    # ---- paired definition version match ----
    for key, rows, expected in (
        ("GT_PAIR_METRICS", gt_pairs, PAIRED_DEFINITION["gt_pair_schema"]),
        ("NO_GT_FEATURES", no_gt, PAIRED_DEFINITION["no_gt_schema"]),
    ):
        if not isinstance(rows, list):
            continue
        declared = {r.get("schema") for r in rows if isinstance(r, dict) and r.get("schema") is not None}
        if declared and declared != {expected}:
            checks["paired_definition"]["blockers"].append(
                f"{key} schema={sorted(declared)} != 认可版本 {expected!r}"
            )
            checks["paired_definition"]["eligible"] = False
            _add_rebuild(
                "03_gate",
                f"{key}.jsonl",
                "schema 版本与 report 认可一致",
                "用匹配 NEUTRAL_EPS_MS 的 paired 定义版本重跑 03",
            )

    for name, chk in checks.items():
        if chk.get("blockers"):
            chk["eligible"] = False
    return checks, rebuild


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
        finite_pairs = [r for r in gt_pairs if isinstance(r, dict) and r.get("delta_error_ms") is not None]
        outcome_rows = [r for r in gt_pairs if isinstance(r, dict) and r.get("label") in {"improve", "harm", "neutral"}]
        improve_n = sum(1 for r in outcome_rows if r.get("label") == "improve")
        harm_n = sum(1 for r in outcome_rows if r.get("label") == "harm")
        covered_to_missing_n = sum(
            1 for r in outcome_rows
            if r.get("old_missing") is False and r.get("new_missing") is True
        )
        gate["n_finite_paired_units"] = len(finite_pairs)
        gate["n_paired_units"] = len(outcome_rows)
        gate["improve_n"] = improve_n
        gate["harm_n"] = harm_n
        gate["covered_to_missing_n"] = covered_to_missing_n
        gate["net_improved_count"] = improve_n - harm_n
        gate["net_improved_ratio"] = (
            (improve_n - harm_n) / len(outcome_rows) if outcome_rows else None
        )
        gate["neutral_n"] = sum(1 for r in outcome_rows if r.get("label") == "neutral")
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

    stage_checks, rebuild_inputs = _check_stage_eligibility(run_root, loaded)
    sections["stage_eligibility"] = stage_checks
    all_eligible = all(chk["eligible"] for chk in stage_checks.values())
    if not all_eligible:
        blocked = [n for n, c in stage_checks.items() if not c["eligible"]]
        conclusion = {
            "writeback_gate": "stage_ineligible",
            "eligible": False,
            "stage_checks": stage_checks,
            "rebuild_inputs": rebuild_inputs,
            "reason": (
                f"分阶段准入未通过（{', '.join(blocked)}）— 仅诊断结论，"
                "不输出写入回传或产品 review 建议"
            ),
        }
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
    if not all_eligible:
        result_status = "diag_stage_ineligible"
    elif not all_ok:
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
        "paired_definition": {
            "gt_pair_schema": PAIRED_DEFINITION["gt_pair_schema"],
            "no_gt_schema": PAIRED_DEFINITION["no_gt_schema"],
            "neutral_eps_ms": PAIRED_DEFINITION["neutral_eps_ms"],
        },
        "sections": {
            "production_detector_audit": audit,
            "gt_realign_behavior": {
                k: v for k, v in behavior.items() if not k.startswith("_")
            },
            "no_gt_gate_signal": gate,
            "test_demo_stress": {k: v for k, v in demo.items() if not k.startswith("_")},
            "stage_eligibility": stage_checks,
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
