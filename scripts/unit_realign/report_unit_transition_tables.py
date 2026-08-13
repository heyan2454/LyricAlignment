"""P12 final output tables for the unit-level realign run.

Reads structured artifacts only (UNIT_OUTCOMES / REGION_OUTCOMES /
REQUEST_STATUS / FORWARDS) and emits:
  05_analysis/UNIT_TRANSITION_TABLES.json
  reports/UNIT_TRANSITION_TABLES.md

Strata semantics (region_sampling.assign_gt_stratum):
  S1 = safe (GT<=200ms) + detector ACCEPT
  S2 = safe (GT<=200ms) + detector REJECT
  S3 = bad  (GT>1000ms) + detector REJECT
  S4 = bad  (GT>1000ms) + detector ACCEPT
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

THRESHOLDS_MS = (100, 200, 500, 1000)
SAFE_MS = 200.0


def _load_lines(path: Path) -> list[dict]:
    out = []
    for line in path.open():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 2) if d else None


def _tables_12_1(unit_rows, region_map, region_rows):
    families = sorted({r["family"] for r in unit_rows})
    strata = sorted({r.get("stratum") for r in region_rows})
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in unit_rows:
        reg = region_map.get((r["region_id"], r.get("family")))
        if reg is None:
            continue
        by_key[(r["family"], reg.get("stratum"))].append(r)
    n_regions_by_key = defaultdict(int)
    for r in region_rows:
        n_regions_by_key[(r["family"], r.get("stratum"))] += 1
    rows_out = []
    for fam in families:
        for st in strata:
            rows = by_key.get((fam, st), [])
            if not rows:
                continue
            per_role = {"target": [r for r in rows if r.get("role") == "target"],
                        "context": [r for r in rows if r.get("role") == "context"]}
            entry = {"family": fam, "stratum": st, "n_regions": 0, "roles": {}}
            for role, sel in per_role.items():
                n = len(sel)
                old_safe = sum(1 for r in sel if isinstance(r.get("old_max_boundary_error_ms"), (int, float)) and r["old_max_boundary_error_ms"] <= SAFE_MS)
                old_bad = sum(1 for r in sel if isinstance(r.get("old_max_boundary_error_ms"), (int, float)) and r["old_max_boundary_error_ms"] > SAFE_MS)
                old_missing = sum(1 for r in sel if r.get("old_missing"))
                new_missing = sum(1 for r in sel if r.get("new_missing"))
                missing_to_covered = sum(1 for r in sel if r.get("old_missing") and not r.get("new_missing"))
                covered_to_missing = sum(1 for r in sel if not r.get("old_missing") and r.get("new_missing"))
                t = {"n": n,
                     "old_safe": old_safe, "old_bad": old_bad,
                     "old_missing": old_missing, "new_missing": new_missing,
                     "missing_to_covered": missing_to_covered,
                     "covered_to_missing": covered_to_missing,
                     "thresholds": {}}
                for thr in THRESHOLDS_MS:
                    safe_old = sum(1 for r in sel if isinstance(r.get("old_max_boundary_error_ms"), (int, float)) and r["old_max_boundary_error_ms"] <= thr)
                    preserved = sum(1 for r in sel
                                    if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                                    and r["old_max_boundary_error_ms"] <= thr
                                    and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                                    and r["new_max_boundary_error_ms"] <= thr
                                    and isinstance(r.get("delta_max_boundary_error_ms"), (int, float))
                                    and r["delta_max_boundary_error_ms"] <= 0.0)
                    t["thresholds"][str(thr)] = {
                        "safe_old": safe_old,
                        "safe_preserved": preserved,
                        "preservation_rate_pct": _pct(preserved, safe_old),
                    }
                mild = sum(1 for r in sel if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                           and r["old_max_boundary_error_ms"] <= SAFE_MS
                           and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                           and r["new_max_boundary_error_ms"] > SAFE_MS)
                severe = sum(1 for r in sel if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                             and r["old_max_boundary_error_ms"] <= SAFE_MS
                             and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                             and r["new_max_boundary_error_ms"] > 500.0)
                catastrophic = sum(1 for r in sel if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                                   and r["old_max_boundary_error_ms"] <= SAFE_MS
                                   and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                                   and r["new_max_boundary_error_ms"] > 1000.0)
                recovered = sum(1 for r in sel if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                                and r["old_max_boundary_error_ms"] > SAFE_MS
                                and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                                and r["new_max_boundary_error_ms"] <= SAFE_MS)
                t.update({
                    "harm_mild_n": mild, "harm_severe_n": severe, "harm_catastrophic_n": catastrophic,
                    "strong_recovery_n": recovered,
                    "harm_mild_rate_pct": _pct(mild, old_safe),
                    "harm_severe_rate_pct": _pct(severe, old_safe),
                    "harm_catastrophic_rate_pct": _pct(catastrophic, old_safe),
                    "strong_recovery_rate_pct": _pct(recovered, old_bad),
                })
                entry["roles"][role] = t
                entry["n_regions"] = n_regions_by_key.get((fam, st), 0)
            rows_out.append(entry)
    return rows_out


def _tables_12_2(unit_rows, region_map, region_rows):
    strata = ("S1", "S2", "S3", "S4")
    out = {}
    for st in strata:
        n_regions = sum(1 for r in region_rows if r.get("stratum") == st)
        rows = [r for r in unit_rows if region_map.get((r["region_id"], r.get("family"))) is not None
                and region_map[(r["region_id"], r.get("family"))].get("stratum") == st]
        targets = [r for r in rows if r.get("role") == "target"]
        contexts = [r for r in rows if r.get("role") == "context"]
        n_t = len(targets)
        remain_ok = sum(1 for r in targets
                        if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                        and r["old_max_boundary_error_ms"] <= SAFE_MS
                        and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                        and r["new_max_boundary_error_ms"] <= SAFE_MS)
        to_500 = sum(1 for r in targets
                     if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                     and r["old_max_boundary_error_ms"] <= SAFE_MS
                     and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                     and r["new_max_boundary_error_ms"] > 500.0)
        to_1s = sum(1 for r in targets
                    if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                    and r["old_max_boundary_error_ms"] <= SAFE_MS
                    and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                    and r["new_max_boundary_error_ms"] > 1000.0)
        ctx_safe = sum(1 for r in contexts
                       if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                       and r["old_max_boundary_error_ms"] <= SAFE_MS)
        collateral = sum(1 for r in contexts
                         if isinstance(r.get("old_max_boundary_error_ms"), (int, float))
                         and r["old_max_boundary_error_ms"] <= SAFE_MS
                         and isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                         and r["new_max_boundary_error_ms"] > SAFE_MS)
        out[st] = {
            "n_regions": n_regions, "n_targets": n_t, "n_contexts": len(contexts),
            "target_remain_le_200ms_n": remain_ok,
            "target_remain_le_200ms_rate_pct": _pct(remain_ok, n_t),
            "target_to_gt_500ms_n": to_500,
            "target_to_gt_500ms_rate_pct": _pct(to_500, n_t),
            "target_to_gt_1s_n": to_1s,
            "target_to_gt_1s_rate_pct": _pct(to_1s, n_t),
            "context_safe_n": ctx_safe,
            "collateral_safe_neighbor_harm_n": collateral,
            "collateral_safe_neighbor_harm_rate_pct": _pct(collateral, ctx_safe),
        }
    return out


def _tables_12_3(req_status, forwards, region_map):
    families = sorted({r["family"] for r in req_status})
    out = {}
    for fam in families:
        reqs = [r for r in req_status if r["family"] == fam]
        planned = len(reqs)
        ready = sum(1 for r in reqs if r.get("status") == "ready")
        null_n = sum(1 for r in reqs if r.get("status") == "null")
        not_cons = sum(1 for r in reqs if r.get("status") == "not_constructible")
        fw = [r for r in forwards if r.get("family") == fam]
        n_forwards = len(fw)
        regs = [r for r in region_map.values() if r.get("family") == fam]
        n_regions = len(regs)
        outcome_counts = defaultdict(int)
        for r in regs:
            outcome_counts[r.get("outcome")] += 1
        n_active = n_regions - outcome_counts.get("neutral", 0)
        n_total_regions = sum(1 for r in region_map.values())
        entry = {
            "n_planned": planned, "n_ready_constructible": ready,
            "constructibility_rate_pct": _pct(ready, planned),
            "n_null": null_n, "n_not_constructible": not_cons,
            "n_forwards": n_forwards,
            "n_regions_evaluated": n_regions,
            "outcome_counts": dict(outcome_counts),
            "region_share_pct": _pct(n_regions, n_total_regions),
            "active_ratio_pct": _pct(n_active, n_regions),
            "catastrophic_harm_rate_pct": _pct(outcome_counts.get("catastrophic_harmful", 0), n_regions),
        }
        out[fam] = entry
    return out


def _dispersion(values):
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean_ms": round(statistics.mean(values), 2),
            "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(sorted(values)[int(len(values) * 0.95) - 1], 2),
            "max_ms": round(max(values), 2),
            "frac_gt_200ms_pct": _pct(sum(1 for v in values if v > 200.0), len(values))}


def _tables_12_4(unit_rows, region_map, region_rows):
    out = {}
    for fam in ("R-S", "R-U"):
        rows = [r for r in unit_rows if r["family"] == fam]
        n_regions_by_st = defaultdict(int)
        for r in region_rows:
            if r.get("family") == fam:
                n_regions_by_st[r.get("stratum")] += 1
        by_stratum = defaultdict(list)
        for r in rows:
            reg = region_map.get((r["region_id"], r.get("family")))
            if reg is None:
                continue
            by_stratum[reg.get("stratum")].append(r)
        fam_entry = {}
        for st in sorted(by_stratum):
            sel = by_stratum[st]
            targets = [r for r in sel if r.get("role") == "target"]
            contexts = [r for r in sel if r.get("role") == "context"]
            active_slots = sum(1 for r in targets if isinstance(r.get("old_max_boundary_error_ms"), (int, float)) and r["old_max_boundary_error_ms"] > SAFE_MS)
            disp = [abs(float(r["delta_max_boundary_error_ms"]))
                    for r in contexts if isinstance(r.get("delta_max_boundary_error_ms"), (int, float))]
            old_bad = [r for r in targets if isinstance(r.get("old_max_boundary_error_ms"), (int, float)) and r["old_max_boundary_error_ms"] > SAFE_MS]
            recovered = sum(1 for r in old_bad if isinstance(r.get("new_max_boundary_error_ms"), (int, float)) and r["new_max_boundary_error_ms"] <= SAFE_MS)
            ctx_safe = [r for r in contexts if isinstance(r.get("old_max_boundary_error_ms"), (int, float)) and r["old_max_boundary_error_ms"] <= SAFE_MS]
            preserved = sum(1 for r in ctx_safe
                            if isinstance(r.get("new_max_boundary_error_ms"), (int, float))
                            and r["new_max_boundary_error_ms"] <= SAFE_MS
                            and isinstance(r.get("delta_max_boundary_error_ms"), (int, float))
                            and r["delta_max_boundary_error_ms"] <= 0.0)
            fam_entry[st] = {
                "n_regions": len({r["region_id"] for r in sel}),
                "n_active_slots": active_slots,
                "n_targets": len(targets),
                "fixed_context_displacement": _dispersion(disp),
                "active_target_recovery_n": recovered,
                "active_target_recovery_rate_pct": _pct(recovered, len(old_bad)),
                "context_safe_n": len(ctx_safe),
                "context_safe_preserved_n": preserved,
                "context_safe_preservation_rate_pct": _pct(preserved, len(ctx_safe)),
            }
        out[fam] = fam_entry
    return out


def _md_12_1(t1):
    lines = ["## 12.1 Unit transition tables (family x stratum)", ""]
    lines.append("| family | stratum | role | n | safe_pres@200 | mild_harm | severe_harm | catast_harm | strong_recovery | cov->miss | miss->cov |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for e in t1:
        for role, t in e["roles"].items():
            th200 = t["thresholds"]["200"]
            lines.append("| {} | {} | {} | {} | {} ({}) | {} | {} | {} | {} ({}) | {} | {} |".format(
                e["family"], e["stratum"], role, t["n"],
                th200["safe_preserved"], _fmt(th200["preservation_rate_pct"]),
                t["harm_mild_n"], t["harm_severe_n"], t["harm_catastrophic_n"],
                t["strong_recovery_n"], _fmt(t["strong_recovery_rate_pct"]),
                t["covered_to_missing"], t["missing_to_covered"]))
    return lines


def _md_12_2(t2):
    lines = ["", "## 12.2 Reject-Safe table (target units + context collateral)", ""]
    lines.append("| stratum | n_regions | n_targets | remain<=200ms | -> >500ms | -> >1s | ctx_safe | collateral harm |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for st, t in t2.items():
        lines.append("| {} | {} | {} | {} ({}) | {} ({}) | {} ({}) | {} | {} ({}) |".format(
            st, t["n_regions"], t["n_targets"],
            t["target_remain_le_200ms_n"], _fmt(t["target_remain_le_200ms_rate_pct"]),
            t["target_to_gt_500ms_n"], _fmt(t["target_to_gt_500ms_rate_pct"]),
            t["target_to_gt_1s_n"], _fmt(t["target_to_gt_1s_rate_pct"]),
            t["context_safe_n"], t["collateral_safe_neighbor_harm_n"],
            _fmt(t["collateral_safe_neighbor_harm_rate_pct"])))
    return lines


def _md_12_3(t3):
    lines = ["", "## 12.3 Request family behavior", ""]
    lines.append("| family | planned | ready | constructible% | null | not_cons | n_forwards | n_regions | active% | catastrophic% | outcome counts |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for fam, t in t3.items():
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            fam, t["n_planned"], t["n_ready_constructible"], _fmt(t["constructibility_rate_pct"]),
            t["n_null"], t["n_not_constructible"], t["n_forwards"], t["n_regions_evaluated"],
            _fmt(t["active_ratio_pct"]), _fmt(t["catastrophic_harm_rate_pct"]), t["outcome_counts"]))
    return lines


def _md_12_4(t4):
    lines = ["", "## 12.4 Sparse (R-S) vs contiguous local (R-U), by stratum", ""]
    lines.append("| family | stratum | n_regions | n_targets | active_slots | recovery n | recovery% | ctx_safe | ctx_safe_pres% | ctx_disp_mean | ctx_disp_p95 | ctx_frac>200ms |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for fam, by_st in t4.items():
        for st, t in by_st.items():
            d = t["fixed_context_displacement"]
            lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                fam, st, t["n_regions"], t["n_targets"], t["n_active_slots"],
                t["active_target_recovery_n"], _fmt(t["active_target_recovery_rate_pct"]),
                t["context_safe_n"], _fmt(t["context_safe_preservation_rate_pct"]),
                d.get("mean_ms", "-"), d.get("p95_ms", "-"), _fmt(d.get("frac_gt_200ms_pct"))))
    return lines


def _fmt(v):
    return "-" if v is None else f"{v:.2f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", default="/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify")
    args = ap.parse_args()
    root = Path(args.run_root)
    unit_rows = _load_lines(root / "03_unit_outcomes/UNIT_OUTCOMES.jsonl")
    region_rows = _load_lines(root / "03_unit_outcomes/REGION_OUTCOMES.jsonl")
    region_map = {(r["region_id"], r.get("family")): r for r in region_rows}
    req_status = _load_lines(root / "01_requests/REQUEST_STATUS.jsonl")
    forwards = _load_lines(root / "02_forwards/FORWARDS.jsonl")

    t1 = _tables_12_1(unit_rows, region_map, region_rows)
    t2 = _tables_12_2(unit_rows, region_map, region_rows)
    t3 = _tables_12_3(req_status, forwards, region_map)
    t4 = _tables_12_4(unit_rows, region_map, region_rows)

    report = {
        "schema": "unit_transition_tables_v1",
        "run_root": str(root),
        "n_unit_rows": len(unit_rows),
        "n_regions_evaluated": len(region_map),
        "stratum_semantics": {
            "S1": "safe (GT<=200ms) + detector ACCEPT",
            "S2": "safe (GT<=200ms) + detector REJECT",
            "S3": "bad (GT>1000ms) + detector REJECT",
            "S4": "bad (GT>1000ms) + detector ACCEPT"},
        "t12_1_unit_transitions": t1,
        "t12_2_reject_safe": t2,
        "t12_3_request_family_behavior": t3,
        "t12_4_sparse_vs_contiguous": t4,
    }
    analysis_dir = root / "05_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    json_path = analysis_dir / "UNIT_TRANSITION_TABLES.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    md = ["# Unit Transition Tables (P12)", "",
          f"- run: `{root}`",
          f"- unit rows: {len(unit_rows)}, regions evaluated: {len(region_map)}",
          "- stratum: S1=safe+ACCEPT, S2=safe+REJECT, S3=bad+REJECT, S4=bad+ACCEPT", ""]
    md += _md_12_1(t1) + _md_12_2(t2) + _md_12_3(t3) + _md_12_4(t4) + [""]
    md_path = root / "reports" / "UNIT_TRANSITION_TABLES.md"
    md_path.write_text("\n".join(md))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
