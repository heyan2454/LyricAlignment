#!/usr/bin/env python
"""Generate FINAL_REPORT.md for a unit_realign v2 run.

Consumes only v2 artifacts:
  00_population/ 01_requests/ 02_forwards/ 03_unit_outcomes/ 05_analysis/ 07_runtime/
Writes <run>/FINAL_REPORT.md.  Empty / all-null / exhausted runs still produce a
report carrying NOT_EVALUATED / EXHAUSTED markers and never raise, even when
every metric is null.

Usage:
    PYTHONPATH=src python scripts/unit_realign/report_final.py --run-root <run> [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from typing import Any, Mapping

STRATA = ["S1", "S2", "S3", "S4", "BOUNDARY", "NA"]
FAMILIES = ["R-U", "R-U1", "R-U3", "R-A", "R-B", "R-S", "R-O", "R-NULL"]
TOLERANCES = ["100", "200", "500", "1000"]
COUNT_FIELDS = ["selected", "constructible", "executed", "null", "failed", "valid"]
MATERIAL_MS = 200.0
CATASTROPHIC_MS = 1000.0


def _load_json(path: str) -> Any | None:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_jsonl(path: str) -> list[Mapping[str, Any]]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _num(v):
    """Null-safe scalar renderer; never feeds a numeric format string."""
    return "n/a" if v is None else v


def _fmt_ms(v):
    if v is None:
        return "n/a"
    return f"{v:.1f}"


def _rate(num, den):
    if not isinstance(num, (int, float)) or not isinstance(den, (int, float)) or den <= 0:
        return None
    return round(float(num) / float(den), 4)


def _mean(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


def _join_stratum(region_id, by_region):
    if not region_id or not by_region:
        return "NA"
    return str(by_region.get(str(region_id), "NA"))


def _classify(row: Mapping[str, Any]) -> str:
    """Match lyricalign.unit_realign.unit_outcome.classify_unit_outcome defaults."""
    if row.get("invalid_unpairable"):
        return "invalid"
    if row.get("extra_prediction"):
        return "extra"
    if row.get("old_missing") and not row.get("new_missing"):
        return "missing_to_covered"
    if not row.get("old_missing") and row.get("new_missing"):
        return "covered_to_missing"
    delta = row.get("delta_max_boundary_error_ms")
    if not isinstance(delta, (int, float)):
        return "invalid"
    if delta <= -MATERIAL_MS:
        return "improved_finite"
    if delta >= MATERIAL_MS or (isinstance(row.get("new_max_boundary_error_ms"), (int, float))
                                and row["new_max_boundary_error_ms"] > CATASTROPHIC_MS):
        return "degraded_finite"
    return "unchanged_finite"


def _role_stats(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    paired = [r for r in rows if not r.get("old_missing") and not r.get("new_missing")
              and isinstance(r.get("delta_max_boundary_error_ms"), (int, float))]
    deltas = [r["delta_max_boundary_error_ms"] for r in paired]
    improved = sum(1 for d in deltas if d <= -MATERIAL_MS)
    regressed = sum(1 for d in deltas if d >= MATERIAL_MS)
    hits = {}
    for t in TOLERANCES:
        th = float(t)
        hits[t] = {
            "old": _rate(sum(1 for r in paired if r["old_max_boundary_error_ms"] <= th), len(paired)),
            "new": _rate(sum(1 for r in paired if r["new_max_boundary_error_ms"] <= th), len(paired)),
        }
    return {
        "n_rows": len(rows),
        "n_paired": len(paired),
        "old_missing": sum(1 for r in rows if r.get("old_missing")),
        "new_missing": sum(1 for r in rows if r.get("new_missing")),
        "extra_prediction": sum(1 for r in rows if r.get("extra_prediction")),
        "covered_to_missing": sum(1 for r in rows if not r.get("old_missing") and r.get("new_missing")),
        "improved": improved,
        "unchanged": len(deltas) - improved - regressed,
        "regressed": regressed,
        "old_mean": _mean([r.get("old_max_boundary_error_ms") for r in paired]),
        "new_mean": _mean([r.get("new_max_boundary_error_ms") for r in paired]),
        "mean_delta": _mean(deltas),
        "hit_rates": hits,
        "class_counts": dict(Counter(_classify(r) for r in rows)),
    }


def _stats_block(title: str, stats: Mapping[str, Any]) -> list[str]:
    out = [f"### {title}"]
    if not stats or not stats.get("n_rows"):
        out.append("- (no data)")
        return out
    hits = stats.get("hit_rates") or {}
    out.append(
        f"- n_rows={stats.get('n_rows')} n_paired={stats.get('n_paired')} "
        f"old_missing={stats.get('old_missing')} new_missing={stats.get('new_missing')} "
        f"extra_prediction={stats.get('extra_prediction')} covered_to_missing={stats.get('covered_to_missing')}"
    )
    out.append(
        f"- improved={stats.get('improved')} unchanged={stats.get('unchanged')} regressed={stats.get('regressed')} | "
        f"old_mean={_fmt_ms(stats.get('old_mean'))} new_mean={_fmt_ms(stats.get('new_mean'))} "
        f"mean_delta={_fmt_ms(stats.get('mean_delta'))}ms"
    )
    cc = stats.get("class_counts") or {}
    out.append("- unit_class_counts: " + ", ".join(f"{k}={v}" for k, v in sorted(cc.items())))
    for t in TOLERANCES:
        h = hits.get(t) or {}
        out.append(f"- hit_rate {t}ms: old={_num(h.get('old'))} new={_num(h.get('new'))}")
    return out


def _funnel_table(funnel: Mapping[tuple[str, str], Mapping[str, int]]) -> list[str]:
    keys = sorted(funnel, key=lambda k: (k[0], k[1]))
    if not keys:
        return ["- (无请求数据)"]
    out = ["| family | stratum | " + " | ".join(COUNT_FIELDS) + " |", "| --- | --- |" + " | ".join([" ---"] * len(COUNT_FIELDS)) + " |"]
    for family, stratum in keys:
        cell = funnel[(family, stratum)]
        out.append("| {} | {} | ".format(family, stratum) + " | ".join(str(cell.get(f, 0)) for f in COUNT_FIELDS) + " |")
    return out


def build_final_report(run_root: str) -> str:
    root = run_root.rstrip("/")
    run_name = os.path.basename(root)
    lines = [f"# FINAL_REPORT — {run_name}", ""]

    meta = _load_json(os.path.join(root, "00_meta", "meta.json")) or {}
    lines.append("## 运行元信息")
    lines.append("")
    lines.append(f"- run_root: `{root}`")
    lines.append(f"- schema: `{meta.get('schema')}`")
    lines.append(f"- run_id: `{meta.get('run_id')}`")
    lines.append("")

    lines.append("## 形式声明（本轮固定）")
    lines.append("")
    lines.append("- **formal_approved = false**：无冻结 manifest sha256（无 `RUN_MANIFEST.json` + 冻结校验），"
                 "本报告一律视为 draft。")
    lines.append("- **shadow-only**：`actual_writeback = 0`，无任何真写回。")
    lines.append("- **writeback_gate = NOT_FROZEN**：未冻结，不得用于 deployable gate 决策。")
    lines.append("- **GT 只经 post-hoc evaluator**：GT 仅存在于 evaluator namespace，"
                 "no-GT 特征 / gate 输入无 GT 字段。")
    lines.append("")

    # ---- 07_runtime ----
    state = _load_json(os.path.join(root, "07_runtime", "RUN_STATE.json")) or {}
    completed = state.get("completed_identities") or []
    failed_ids = set(state.get("failed_identities") or [])
    null_ids = set(state.get("null_identities") or [])
    nc_ids = set(state.get("not_constructible_identities") or [])
    lines.append("## 执行状态（07_runtime/RUN_STATE.json）")
    lines.append("")
    lines.append(f"- completed={len(completed)} failed={len(failed_ids)} null={len(null_ids)} "
                 f"not_constructible={len(nc_ids)}")
    lines.append("")

    # ---- 00_population / 03 STRATIFIED_POOL ----
    population = _read_jsonl(os.path.join(root, "00_population", "REGION_POOL.jsonl"))
    screen_audit = _load_json(os.path.join(root, "00_population", "SCREEN_SAMPLE.jsonl") or
                              os.path.join(root, "00_population", "EXHAUSTION_AUDIT.json"))
    refill_audit = _load_json(os.path.join(root, "00_population", "P1_REFILL_AUDIT.json"))
    stratified = _read_jsonl(os.path.join(root, "03_unit_outcomes", "STRATIFIED_POOL.jsonl"))
    stratum_by_region = {str(r.get("region_id")): r.get("stratum") for r in stratified if r.get("region_id")}
    pool_statuses = {}
    for row in stratified:
        key = str(row.get("stratum_status", "unlabeled"))
        pool_statuses[key] = pool_statuses.get(key, 0) + 1
    lines.append("## 采样与队列审计（00_population / 03 STRATIFIED_POOL）")
    lines.append("")
    lines.append(f"- population rows: {len(population)}")
    if screen_audit:
        lines.append(f"- screen audit: status=`{screen_audit.get('status')}` selected={screen_audit.get('selected')}")
    if refill_audit:
        sel = refill_audit.get("selected_per_stratum") or {}
        lines.append(f"- p1-refill audit: status=`{refill_audit.get('status')}` "
                     + ", ".join(f"{k}={sel.get(k, 0)}" for k in ["S1", "S2", "S3", "S4"]))
    if pool_statuses:
        lines.append("- stratified pool status: " + ", ".join(f"{k}={v}" for k, v in sorted(pool_statuses.items())))
    lines.append("")

    # ---- 01_requests funnel ----
    requests = _read_jsonl(os.path.join(root, "01_requests", "REQUESTS.jsonl"))
    if not requests:
        requests = _read_jsonl(os.path.join(root, "01_requests", "P1_SELECTED_REGIONS.jsonl"))
    request_status = _read_jsonl(os.path.join(root, "01_requests", "REQUEST_STATUS.jsonl"))
    status_by_identity = {str(r.get("request_identity")): str(r.get("status")) for r in request_status if r.get("request_identity")}
    forwards = _read_jsonl(os.path.join(root, "02_forwards", "FORWARDS.jsonl"))
    failures = _read_jsonl(os.path.join(root, "02_forwards", "FAILURES.jsonl"))
    regions = _read_jsonl(os.path.join(root, "03_unit_outcomes", "REGION_OUTCOMES.jsonl"))
    unit_rows = _read_jsonl(os.path.join(root, "03_unit_outcomes", "UNIT_OUTCOMES.jsonl"))
    candidate = _load_json(os.path.join(root, "05_analysis", "CANDIDATE_OUTCOMES.json"))

    funnel: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for req in requests:
        family = str(req.get("family", "NA"))
        stratum = _join_stratum(req.get("region_id"), stratum_by_region)
        cell = funnel[(family, stratum)]
        cell["selected"] += 1
        identity = req.get("request_identity")
        status = req.get("status") or status_by_identity.get(str(identity)) or "unknown"
        if status == "not_constructible" or str(identity) in nc_ids:
            cell["constructible"] += 1
        elif status == "null" or str(identity) in null_ids:
            cell["null"] += 1
        elif str(identity) in failed_ids:
            cell["failed"] += 1
        elif status == "ready":
            cell["executed"] += 1
        elif status == "invalid":
            cell["failed"] += 1
    for region in regions:
        family = str(region.get("family", "NA"))
        stratum = _join_stratum(region.get("region_id"), stratum_by_region)
        funnel[(family, stratum)]["valid"] += 1

    lines.append("## 请求漏斗（family × stratum）")
    lines.append("")
    lines.append("- selected/constructible/executed/null/failed/valid 计数来自 "
                 "`01_requests`、`02_forwards`、`07_runtime` 与 `03_unit_outcomes`。")
    lines.append("")
    lines.extend(_funnel_table(funnel))
    lines.append("")
    lines.append(f"- forwards: {len(forwards)} failures: {len(failures)} "
                 f"(02_forwards: FORWARDS.jsonl / FAILURES.jsonl)")
    lines.append("")

    # ---- evaluation status ----
    exhausted = any(audit.get("status") == "exhausted" for audit in (screen_audit, refill_audit) if audit)
    if regions:
        eval_status = "EVALUATED"
    elif exhausted:
        eval_status = "EXHAUSTED"
    else:
        eval_status = "NOT_EVALUATED"
    lines.append("## 评价状态")
    lines.append("")
    lines.append(f"- **{eval_status}**：regions evaluated={len(regions)} unit rows={len(unit_rows)}")
    if not regions and (null_ids or not requests):
        lines.append(f"- 无有效评价：completed={len(completed)} null={len(null_ids)} "
                     f"not_constructible={len(nc_ids)} requests={len(requests)}")
    lines.append("")

    if regions and unit_rows:
        lines.append("## 评价结果（03_unit_outcomes / 05_analysis）")
        lines.append("")
        by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in unit_rows:
            by_family[str(row.get("family", "NA"))].append(row)
        target_all = [r for r in unit_rows if r.get("role") == "target"]
        context_all = [r for r in unit_rows if r.get("role") in {"context", "extra"}]
        lines.append("### 总体（target 与 fixed context 分开）")
        lines.append("")
        lines.extend(_stats_block("target", _role_stats(target_all)))
        lines.append("")
        lines.extend(_stats_block("fixed context（含 extra）", _role_stats(context_all)))
        lines.append("")
        lines.append("### 逐 family（target 与 fixed context 分开）")
        lines.append("")
        for fam in sorted(by_family):
            fam_rows = by_family[fam]
            t_rows = [r for r in fam_rows if r.get("role") == "target"]
            c_rows = [r for r in fam_rows if r.get("role") in {"context", "extra"}]
            lines.append(f"#### Family {fam}")
            lines.append("")
            lines.extend(_stats_block("target", _role_stats(t_rows)))
            lines.append("")
            lines.extend(_stats_block("fixed context", _role_stats(c_rows)))
            lines.append("")

        lines.append("### region outcome 汇总（REGION_OUTCOMES.jsonl）")
        lines.append("")
        outcome_counts = Counter(str(r.get("outcome", "unknown")) for r in regions)
        lines.append(f"- n_regions={len(regions)} n_target_total={sum(r.get('n_target', 0) for r in regions)} "
                     f"n_context_total={sum(r.get('n_context', 0) for r in regions)}")
        lines.append("- outcomes: " + ", ".join(f"{k}={v}" for k, v in sorted(outcome_counts.items())))
        lines.append("")

        lines.append("### candidate outcome（05_analysis/CANDIDATE_OUTCOMES.json）")
        lines.append("")
        if candidate:
            lines.append(f"- outcome=`{candidate.get('outcome')}` n_regions={candidate.get('n_regions')}")
        else:
            lines.append("- (CANDIDATE_OUTCOMES.json 缺失)")
        lines.append("")

        by_song: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in regions:
            by_song[str(r.get("song_id", "NA"))].append(r)
        lines.append("### song-cluster 汇总")
        lines.append("")
        if by_song:
            for song in sorted(by_song):
                cluster = by_song[song]
                labels = [str(r.get("outcome")) for r in cluster]
                if "catastrophic_harmful" in labels:
                    c_outcome = "catastrophic_harmful"
                elif "mixed" in labels:
                    c_outcome = "mixed"
                elif "harmful" in labels:
                    c_outcome = "harmful"
                elif "beneficial" in labels:
                    c_outcome = "beneficial"
                else:
                    c_outcome = "neutral"
                lines.append(f"- {song}: n_regions={len(cluster)} outcome={c_outcome}")
        else:
            lines.append("- (no region outcomes)")
        lines.append("")
    else:
        lines.append("> **未评价**：该 run 没有可消费的 `03_unit_outcomes/REGION_OUTCOMES.jsonl` 评价证据，"
                     "不包含任何 GT 指标。")
        lines.append("")

    lines.append("## 数据侧 v2 审计产物（05_analysis）")
    lines.append("")
    analysis_files = sorted(os.listdir(os.path.join(root, "05_analysis"))) if os.path.isdir(os.path.join(root, "05_analysis")) else []
    for name in analysis_files:
        lines.append(f"- 05_analysis/{name}")
    if not analysis_files:
        lines.append("- (无)")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"_generated by scripts/unit_realign/report_final.py from `{root}`_")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    run_root = os.path.abspath(args.run_root)
    md = build_final_report(run_root)
    out = args.out or os.path.join(run_root, "FINAL_REPORT.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"WROTE {out}")
    print(md)


if __name__ == "__main__":
    main()
