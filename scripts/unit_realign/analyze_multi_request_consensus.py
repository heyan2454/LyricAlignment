"""P12.5 multi-request consensus analysis (pure CPU, no forward).

For every target unit (UNIT_OUTCOMES role=="target"), collect candidate
(start_sec, end_sec) across the 4 evidence families (R-U/R-S/R-A/R-B) of its
region, compute consensus signals (span_ms on start center, >=3/4 views within
<100ms), compare against BASELINE_GT centers, and cross with region outcome /
stratum. Outputs:
  <run>/05_analysis/MULTI_REQUEST_CONSENSUS.json
  <run>/05_analysis/MULTI_REQUEST_CONSENSUS_REPORT.md
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path

FAMILIES = ("R-U", "R-S", "R-A", "R-B")
AGREE_MS = 100.0


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def consensus_metrics(starts_ms):
    n = len(starts_ms)
    if n < 2:
        return {"span_ms": None, "std_ms": None, "consistent_34": False, "n_views": n}, True
    span = max(starts_ms) - min(starts_ms)
    sd = statistics.pstdev(starts_ms) if n > 1 else 0.0
    agree_ge3 = False
    if n >= 3:
        s = sorted(starts_ms)
        for i in range(len(s) - 2):
            if s[i + 2] - s[i] < AGREE_MS:
                agree_ge3 = True
                break
    return {"span_ms": span, "std_ms": sd, "consistent_34": bool(agree_ge3), "n_views": n}, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-run", required=True)
    args = ap.parse_args()

    run = Path(args.main_run)
    unit_out = load_jsonl(run / "03_unit_outcomes" / "UNIT_OUTCOMES.jsonl")
    region_out = load_jsonl(run / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")
    gt_out = load_jsonl(run / "06_evaluator_only" / "BASELINE_GT.jsonl")
    ev_dir = run / "02_forwards" / "evidence"
    out_dir = run / "05_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    gt_center = {}
    for g in gt_out:
        cid = (g["song_id"], g["canonical_unit_id"])
        gt_center[cid] = (g["start_sec"] + g["end_sec"]) / 2.0 * 1000.0

    region_meta = {}
    for r in region_out:
        region_meta[r["region_id"]] = r

    region_units = defaultdict(list)
    targets = []
    for u in unit_out:
        region_units[u["region_id"]].append(u)
        if u["role"] == "target":
            targets.append(u)

    ev_cache = {}

    def load_evidence(request_id):
        if request_id in ev_cache:
            return ev_cache[request_id]
        p = ev_dir / f"{request_id}.candidate.jsonl"
        rows = load_jsonl(p) if p.exists() else None
        ev_cache[request_id] = rows
        return rows

    unit_rows = []
    for u in targets:
        song = u["song_id"]
        region = u["region_id"]
        cid = u["canonical_unit_id"]
        meta = region_meta.get(region, {})
        views = {}
        for fam in FAMILIES:
            request_id = f"{song}:{region}:{fam}"
            rows = load_evidence(request_id)
            found = None
            if rows:
                for row in rows:
                    if row.get("canonical_unit_id") == cid:
                        found = row
                        break
            if found is not None:
                views[fam] = (found["start_sec"], found["end_sec"])
        starts_ms = [v[0] * 1000.0 for v in views.values()]
        metrics, have_span = consensus_metrics(starts_ms)
        gt = gt_center.get((song, cid))
        view_err = {}
        for fam, (s, e) in views.items():
            if gt is not None:
                view_err[fam] = abs((s + e) / 2.0 * 1000.0 - gt)
        gt_err = min(view_err.values()) if view_err else None
        unit_rows.append({
            "song_id": song,
            "region_id": region,
            "canonical_unit_id": cid,
            "stratum": meta.get("stratum"),
            "family": meta.get("family"),
            "n_views": len(views),
            "families": sorted(views),
            "span_ms": metrics["span_ms"] if have_span else None,
            "std_ms": metrics["std_ms"] if have_span else None,
            "consistent_34": metrics["consistent_34"] if have_span else None,
            "gt_center_ms": gt,
            "gt_hit_100ms": bool(gt is not None and gt_err is not None and gt_err < 100.0),
            "gt_err_ms": gt_err,
            "view_err_ms": view_err,
            "views": {fam: {"start_sec": s, "end_sec": e} for fam, (s, e) in views.items()},
        })

    n_units = len(unit_rows)
    spans = [r["span_ms"] for r in unit_rows if r["span_ms"] is not None]
    consistent = [r for r in unit_rows if r["consistent_34"]]
    weak = [r for r in unit_rows if r["consistent_34"] is False and r["span_ms"] is not None]
    has_gt = [r for r in unit_rows if r["gt_err_ms"] is not None]
    strong_gt = [r for r in consistent if r["gt_err_ms"] is not None]
    weak_gt = [r for r in weak if r["gt_err_ms"] is not None]

    def hit_ratio(rows):
        if not rows:
            return None
        return sum(1 for r in rows if r["gt_hit_100ms"]) / len(rows)

    region_level = {}
    for region, units in sorted(region_units.items()):
        meta = region_meta.get(region, {})
        target_ur = [r for r in unit_rows if r["region_id"] == region]
        n_t = len(target_ur)
        cons_n = sum(1 for r in target_ur if r["consistent_34"])
        region_level[region] = {
            "region_id": region,
            "song_id": meta.get("song_id"),
            "outcome": meta.get("outcome"),
            "stratum": meta.get("stratum"),
            "n_target_units": n_t,
            "n_consistent": cons_n,
            "consistent_ratio": (cons_n / n_t) if n_t else None,
            "catastrophic": meta.get("outcome") == "catastrophic_harmful",
        }

    strong_regions = [r for r in region_level.values() if r["consistent_ratio"] is not None and r["consistent_ratio"] >= 0.5]
    weak_regions = [r for r in region_level.values() if r["consistent_ratio"] is not None and r["consistent_ratio"] < 0.5]

    def outcome_hist(rows):
        return dict(Counter(r["outcome"] for r in rows if r["outcome"]))

    def catastrophic_rate(rows):
        rows = [r for r in rows if r["outcome"]]
        if not rows:
            return None
        return sum(1 for r in rows if r["outcome"] == "catastrophic_harmful") / len(rows)

    stratum_table = {}
    for stratum in sorted({r["stratum"] for r in region_level.values()}):
        sub = [r for r in region_level.values() if r["stratum"] == stratum]
        stratum_table[stratum] = {
            "n_regions": len(sub),
            "consistent_ratio_mean": (statistics.mean(r["consistent_ratio"] for r in sub)
                                      if sub and all(x is not None for x in (r["consistent_ratio"] for r in sub)) else None),
            "catastrophic_rate": catastrophic_rate(sub),
        }

    agg = {
        "schema": "unit_realign_multi_request_consensus_v1",
        "run": str(run),
        "n_target_units": n_units,
        "n_views_dist": dict(Counter(r["n_views"] for r in unit_rows)),
        "span_ms_dist": {
            "n": len(spans),
            "mean_ms": statistics.mean(spans) if spans else None,
            "median_ms": statistics.median(spans) if spans else None,
            "p90_ms": sorted(spans)[int(len(spans) * 0.9) - 1] if spans else None,
        },
        "consistent_34_ratio": (sum(1 for r in consistent) / n_units) if n_units else None,
        "consensus_strong": {"n": len(consistent), "gt_hit_100ms_ratio": hit_ratio(strong_gt),
                             "mean_gt_err_ms": (statistics.mean(r["gt_err_ms"] for r in strong_gt) if strong_gt else None)},
        "consensus_weak": {"n": len(weak), "gt_hit_100ms_ratio": hit_ratio(weak_gt),
                           "mean_gt_err_ms": (statistics.mean(r["gt_err_ms"] for r in weak_gt) if weak_gt else None)},
        "region_outcome_x_consensus": {
            "strong_regions": {"n": len(strong_regions), "outcome_hist": outcome_hist(strong_regions),
                               "catastrophic_rate": catastrophic_rate(strong_regions)},
            "weak_regions": {"n": len(weak_regions), "outcome_hist": outcome_hist(weak_regions),
                             "catastrophic_rate": catastrophic_rate(weak_regions)},
        },
        "stratum_table": stratum_table,
    }

    with open(out_dir / "MULTI_REQUEST_CONSENSUS.json", "w", encoding="utf-8") as fh:
        json.dump(agg, fh, indent=2, ensure_ascii=False)

    def pct(x, total):
        return f"{100.0 * x / total:.1f}%" if total else "n/a"

    lines = [
        "# P12.5 Multi-request Consensus 分析报告",
        "",
        f"- run: `{run}`",
        f"- 分析时间: (脚本生成)",
        "",
        "## 1. Unit 级 consensus 信号",
        "",
        f"| 指标 | 值 |",
        f"| --- | --- |",
        f"| target units | {n_units} |",
        f"| n_views 分布 | {agg['n_views_dist']} |",
        f"| span_ms mean / median / p90 | {agg['span_ms_dist']['mean_ms']:.1f} / {agg['span_ms_dist']['median_ms']:.1f} / {agg['span_ms_dist']['p90_ms']:.1f} ms (n={agg['span_ms_dist']['n']}) |",
        f"| consistent_34 (≥3 views 彼此<100ms) | {pct(len(consistent), n_units)} ({len(consistent)}) |",
        "",
        "## 2. consensus → GT 关系",
        "",
        "| 分组 | n | GT命中<100ms | mean GT err (ms) |",
        "| --- | --- | --- | --- |",
        f"| consensus strong | {len(strong_gt)} | {pct(agg['consensus_strong']['gt_hit_100ms_ratio'] * len(strong_gt), len(strong_gt)) if strong_gt else 'n/a'} | {agg['consensus_strong']['mean_gt_err_ms']:.1f} |",
        f"| consensus weak | {len(weak_gt)} | {pct(agg['consensus_weak']['gt_hit_100ms_ratio'] * len(weak_gt), len(weak_gt)) if weak_gt else 'n/a'} | {agg['consensus_weak']['mean_gt_err_ms']:.1f} |",
        "",
        "## 3. Region outcome × consensus",
        "",
        "| Region 分组 | n | 各 outcome 分布 | catastrophic 率 |",
        "| --- | --- | --- | --- |",
        f"| consensus strong (≥50% targets consistent) | {agg['region_outcome_x_consensus']['strong_regions']['n']} | {agg['region_outcome_x_consensus']['strong_regions']['outcome_hist']} | {agg['region_outcome_x_consensus']['strong_regions']['catastrophic_rate']} |",
        f"| consensus weak | {agg['region_outcome_x_consensus']['weak_regions']['n']} | {agg['region_outcome_x_consensus']['weak_regions']['outcome_hist']} | {agg['region_outcome_x_consensus']['weak_regions']['catastrophic_rate']} |",
        "",
        "| stratum | n_regions | consistent_ratio mean | catastrophic 率 |",
        "| --- | --- | --- | --- |",
    ]
    for s, v in stratum_table.items():
        lines.append(f"| {s} | {v['n_regions']} | {v['consistent_ratio_mean']:.3f} | {v['catastrophic_rate']} |")

    # P13-E judgement
    strong_hit = agg["consensus_strong"]["gt_hit_100ms_ratio"]
    weak_hit = agg["consensus_weak"]["gt_hit_100ms_ratio"]
    if strong_hit is not None and weak_hit is not None and strong_hit > weak_hit:
        verdict = ("支持情况 E：多 view consensus 强的 unit 的 GT 命中率显著高于 consensus 弱组，"
                   "gate 可基于多 view 共识（额外 forward 换取 reliability）。")
    else:
        verdict = ("不支持情况 E（当前数据）：多 view consensus 未能比弱一致组更好地预测 GT 正确，"
                   "gate 不应单独依赖多 view 共识。")
    lines += [
        "",
        "## 4. P13-E 判定",
        "",
        verdict,
        "",
        f"- strong GT hit {strong_hit:.3f} vs weak GT hit {weak_hit:.3f}",
        "",
        "## 5. 产物",
        "",
        f"- `{out_dir / 'MULTI_REQUEST_CONSENSUS.json'}`",
        f"- `{out_dir / 'MULTI_REQUEST_CONSENSUS_REPORT.md'}`",
        "",
    ]
    with open(out_dir / "MULTI_REQUEST_CONSENSUS_REPORT.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(json.dumps({
        "n_target_units": n_units,
        "span_ms_dist": agg["span_ms_dist"],
        "consistent_34_ratio": agg["consistent_34_ratio"],
        "consensus_strong": agg["consensus_strong"],
        "consensus_weak": agg["consensus_weak"],
        "region_strong_vs_weak": {
            "strong": {k: agg["region_outcome_x_consensus"]["strong_regions"][k] for k in ("n", "catastrophic_rate")},
            "weak": {k: agg["region_outcome_x_consensus"]["weak_regions"][k] for k in ("n", "catastrophic_rate")},
        },
        "p13e_supported": bool(strong_hit is not None and weak_hit is not None and strong_hit > weak_hit),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
