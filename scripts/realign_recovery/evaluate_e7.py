"""E7: detector judges realign quality.

Rebuilds the E3 frozen scorer (raw target), scores every ``e5_proposal``
candidate from the candidate bank, caches per-unit p_bad in memory, and emits
Q1 (pairwise old-vs-new), Q2 (best-of-K ranking) and Q3 (accept/reject gate)
metrics against ``E7_PER_UNIT_GT.jsonl``.

No-GT discipline: only ``E7_PER_UNIT_GT.jsonl`` is read as GT (old/new error
aggregations), detector signals come from ``FrozenScorer`` p_bad only, and
every aggregated output dict passes ``assert_no_label_leak`` recursively.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lyricalign.realign_recovery.candidate_scores import (
    build_frozen_scorer_from_artifacts,
    candidate_evidence_rows,
    load_bank,
    load_requests,
    score_units,
)
from lyricalign.realign_recovery.e7_metrics import (
    accept_reject_metrics,
    classify_repair,
    classify_unit_repair,
    pairwise_metrics,
    rank_metrics,
    unit_accept_reject_metrics,
)
from lyricalign.research_v7.detector_v2_evidence import assert_no_label_leak

_SCHEMA_VERSION = "realign_recovery_e7_eval_v1"
_RUNS_ROOT = "/home/hyan/Data/lyricalign/runs"
_DEFAULT_RUN = f"{_RUNS_ROOT}/realign_recovery_20260812_20260811T202813Z"
_STAGE3B = f"{_RUNS_ROOT}/research_transition_recovery_detector_20260810_realgt_expansion_handoff/stage3b_cohort_ab_eval"
_ITEMS_DIRS = [
    f"{_RUNS_ROOT}/research_transition_recovery_detector_20260810_realgt_expansion_handoff/stage3b_cohort_a_reagg/rerun_gpu/items",
    f"{_RUNS_ROOT}/research_transition_recovery_detector_20260810_realgt_expansion_handoff/stage3b_cohort_b_dev/items",
]


def _load_gt(path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _recursive_leak_check(value) -> None:
    if isinstance(value, dict):
        assert_no_label_leak(value)
        for v in value.values():
            _recursive_leak_check(v)
    elif isinstance(value, list):
        for v in value:
            _recursive_leak_check(v)


def _score_candidates(bank_rows, requests, scorer) -> dict[tuple[str, str], dict]:
    """(episode_id, input_variant) -> {"units": {cid: p_bad}, "states": {...},
    "decision": str, "n_units": int}."""
    cache: dict[tuple[str, str], dict] = {}
    skipped = 0
    for cand in bank_rows:
        if cand.get("ownership") != "e5_proposal":
            continue
        request_row, rows = candidate_evidence_rows(cand, requests)
        if request_row is None or not rows:
            skipped += 1
            continue
        ep = (request_row.get("provenance") or {}).get("episode_id")
        variant = request_row.get("input_variant")
        if not ep or not variant:
            skipped += 1
            continue
        out = score_units(scorer, rows)
        cache[(ep, variant)] = {
            "units": {u["canonical_unit_id"]: u["p_bad"] for u in out["units"]},
            "states": {u["canonical_unit_id"]: u["state"] for u in out["units"]},
            "decision": out["decision"],
            "n_units": out["n_units"],
        }
    return cache, skipped


def _q1_rows(gt_rows, cache):
    deltas, improved, old_errs = [], [], []
    for r in gt_rows:
        if not r.get("old_covered"):
            continue
        if r["variant"] == "original_full":
            continue
        cid = r["canonical_unit_id"]
        old_p = cache.get((r["episode_id"], "original_full"), {}).get(
            "units", {}).get(cid)
        new_p = cache.get((r["episode_id"], r["variant"]), {}).get(
            "units", {}).get(cid)
        old_err = r.get("old_error_sec")
        new_err = r.get("new_error_sec")
        if old_p is None or new_p is None or old_err is None or new_err is None:
            continue
        deltas.append(old_p - new_p)
        improved.append(bool(new_err < old_err - 1e-6))
        old_errs.append(old_err)
    return pairwise_metrics(deltas, improved, old_errs)


def _q2_episodes(gt_rows, cache):
    by_ep: dict[str, dict[str, list]] = {}
    for r in gt_rows:
        if r["variant"] == "original_full":
            continue
        by_ep.setdefault(r["episode_id"], {}).setdefault(
            r["variant"], []).append(r)
    episodes = []
    total = skipped_lt2 = skipped_nomeans = skipped_noscore = 0
    for ep, variants in by_ep.items():
        total += 1
        if len(variants) < 2:
            skipped_lt2 += 1
            continue
        means = {v: sum(x["new_error_sec"] for x in rows) / len(rows)
                 for v, rows in variants.items()
                 if any(x.get("new_error_sec") is not None for x in rows)}
        if not means:
            skipped_nomeans += 1
            continue
        gt_best = min(means, key=means.get)
        scored = []
        for v in variants:
            old_p = cache.get((ep, "original_full"), {}).get("units", {})
            new_p = cache.get((ep, v), {}).get("units", {})
            ds = [old_p[cid] - new_p[cid]
                  for cid in old_p.keys() & new_p.keys()]
            if ds:
                scored.append((v, sum(ds) / len(ds)))
        episodes.append({
            "scored_variants": scored,
            "gt_best": gt_best,
            "gt_best_is_oracle": str(gt_best).startswith("oracle"),
        })
    coverage = {
        "total_episodes": total,
        "evaluated_episodes": sum(
            1 for ep in episodes
            if any(v == ep["gt_best"] for v, _ in ep["scored_variants"])),
        "skipped_lt2_variants": skipped_lt2,
        "skipped_no_means": skipped_nomeans,
        "skipped_gt_best_no_score": max(0, total - skipped_lt2
                                        - skipped_nomeans - sum(
                                            1 for ep in episodes
                                            if any(
                                                v == ep["gt_best"]
                                                for v, _ in ep["scored_variants"]))),
    }
    return rank_metrics(episodes), coverage


def _q3_rows(gt_rows, cache):
    by_epv: dict[tuple[str, str], list] = {}
    for r in gt_rows:
        if r["variant"] == "original_full":
            continue
        by_epv.setdefault((r["episode_id"], r["variant"]), []).append(r)
    rows = []
    unit_rows = []
    ep_all_bad: dict[str, dict] = {}
    ep_repair_class: dict[tuple[str, str], str] = {}
    for (ep, variant), gts in by_epv.items():
        old_by = {r["canonical_unit_id"]: r.get("old_error_sec") for r in gts}
        new_by = {r["canonical_unit_id"]: r.get("new_error_sec") for r in gts}
        cids = sorted(set(old_by) | set(new_by))
        old_errs = [old_by.get(c) for c in cids]
        new_errs = [new_by.get(c) for c in cids]
        if not any(e is not None for e in new_errs):
            continue
        cls = classify_repair(old_errs, new_errs)
        ep_repair_class[(ep, variant)] = cls
        det = cache.get((ep, variant))
        rejected = det is None or det["decision"] == "reject" or any(
            st == "reject" for st in det["states"].values())
        rows.append({"repair_class": cls, "detector_accept": not rejected})
        bucket = ep_all_bad.setdefault(ep, {"harmful": 0, "total": 0,
                                            "rejected": 0})
        bucket["total"] += 1
        if cls == "harmful":
            bucket["harmful"] += 1
        if rejected:
            bucket["rejected"] += 1
        det_states = det["states"] if det is not None else {}
        for cid in cids:
            old_e = old_by.get(cid)
            new_e = new_by.get(cid)
            if old_e is None or new_e is None:
                continue
            unit_rows.append({
                "canonical_unit_id": cid,
                "gt_covered": True,
                "repair_class": classify_unit_repair(old_e, new_e),
                "detector_accept": det_states.get(cid) == "accept",
            })
    n_all_gt_units = 0
    n_all_det_units = 0
    for r in gt_rows:
        if r["variant"] == "original_full":
            continue
        if r.get("old_error_sec") is not None and r.get("new_error_sec") is not None:
            n_all_gt_units += 1
    for (ep, variant), det in cache.items():
        n_all_det_units += det["n_units"]
    all_bad = {ep: b for ep, b in ep_all_bad.items()
               if b["total"] > 0 and b["harmful"] == b["total"]}
    all_bad_reject = (sum(1 for b in all_bad.values()
                          if b["rejected"] == b["total"]), len(all_bad))
    return rows, unit_rows, all_bad_reject, {
        "n_all_gt_units": n_all_gt_units,
        "n_all_det_units": n_all_det_units,
    }, ep_repair_class


def _per_episode(gt_rows, cache, ep_repair_class=None) -> dict:
    per_ep: dict[str, dict] = {}
    ep_repair_class = ep_repair_class or {}
    for r in gt_rows:
        ep = r["episode_id"]
        variant = r["variant"]
        det = cache.get((ep, variant))
        if det is None:
            continue
        entry = per_ep.setdefault(ep, {"family_name": r["family"],
                                       "variants": {}})
        entry["family_name"] = r["family"]
        v = entry["variants"].setdefault(variant, {
            "n_units": 0, "mean_p_bad": 0.0,
            "n_reject": 0, "n_uncertain": 0, "n_accept": 0,
            "repair_class": ep_repair_class.get((ep, variant)),
        })
        v["n_units"] = det["n_units"]
        if det["units"]:
            v["mean_p_bad"] = sum(det["units"].values()) / len(det["units"])
        v["n_accept"] = sum(1 for st in det["states"].values()
                            if st == "accept")
        v["n_uncertain"] = sum(1 for st in det["states"].values()
                               if st == "uncertain")
        v["n_reject"] = sum(1 for st in det["states"].values()
                            if st == "reject")
    return per_ep


def _per_family(gt_rows, cache) -> dict:
    fam = {}
    for r in gt_rows:
        det = cache.get((r["episode_id"], r["variant"]))
        if det is None:
            continue
        f = fam.setdefault(r["family"], {"n_episodes": 0, "n_variants": 0,
                                         "mean_p_bad": 0.0, "n_units": 0})
        f["n_variants"] += 1
        f["n_units"] += det["n_units"]
        if det["units"]:
            f["mean_p_bad"] += sum(det["units"].values())
    out = {}
    for name, f in fam.items():
        d = dict(f)
        d["mean_p_bad"] = (d["mean_p_bad"] / d["n_units"]
                           if d["n_units"] else 0.0)
        out[name] = d
    out = {k: v for k, v in sorted(out.items())}
    episodes = {r["episode_id"] for r in gt_rows}
    for name in out:
        out[name]["n_episodes"] = len({r["episode_id"] for r in gt_rows
                                       if r["family"] == name})
    return out


def _per_method(gt_rows, cache) -> dict:
    meth = {}
    for r in gt_rows:
        det = cache.get((r["episode_id"], r["variant"]))
        if det is None:
            continue
        m = meth.setdefault(r["method"], {"n_variants": 0, "mean_p_bad": 0.0,
                                          "n_units": 0})
        m["n_variants"] += 1
        m["n_units"] += det["n_units"]
        if det["units"]:
            m["mean_p_bad"] += sum(det["units"].values())
    out = {}
    for name, m in meth.items():
        d = dict(m)
        d["mean_p_bad"] = (d["mean_p_bad"] / d["n_units"]
                           if d["n_units"] else 0.0)
        out[name] = d
    return {k: out[k] for k in sorted(out)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root", default=_DEFAULT_RUN)
    args = ap.parse_args()
    run = Path(args.run_root)
    gt_path = run / "e7_input" / "E7_PER_UNIT_GT.jsonl"
    requests_path = run / "e5_proposals" / "raw" / "REQUESTS.jsonl"
    bank_path = run / "e5_proposals" / "candidate_bank" / "candidate_bank.jsonl"
    out_path = run / "e7_eval" / "E7_EVAL_SUMMARY.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scorer = build_frozen_scorer_from_artifacts(
        f"{_STAGE3B}/FROZEN_OPERATING_POINTS.json",
        f"{_STAGE3B}/LABELS.jsonl",
        f"{_STAGE3B}/evidence_v2",
        list(_ITEMS_DIRS),
        target="raw",
    )
    requests = load_requests(requests_path)
    bank_rows = load_bank(bank_path)
    cache, skipped = _score_candidates(bank_rows, requests, scorer)
    gt_rows = _load_gt(gt_path)

    q1 = _q1_rows(gt_rows, cache)
    q2, q2_coverage = _q2_episodes(gt_rows, cache)
    (q3_rows, q3_unit_rows, (all_bad_rej, all_bad_n),
     q3_unit_coverage, ep_repair_class) = _q3_rows(gt_rows, cache)
    q3 = accept_reject_metrics(q3_rows)
    q3_unit = unit_accept_reject_metrics(
        q3_unit_rows,
        n_all_gt_units=q3_unit_coverage["n_all_gt_units"],
        n_all_det_units=q3_unit_coverage["n_all_det_units"],
    )

    summary = {
        "schema_version": _SCHEMA_VERSION,
        "inputs": {
            "run_root": str(run),
            "gt_path": str(gt_path),
            "requests_path": str(requests_path),
            "bank_path": str(bank_path),
            "n_gt_rows": len(gt_rows),
            "n_candidates_scored": len(cache),
            "n_candidates_skipped": skipped,
            "scorer_target": "raw",
            "safe_threshold_sec": 1.0,
        },
        "main_metrics": {
            "q1_pairwise": q1,
            "q2_best_of_k": q2,
            "q2_coverage": q2_coverage,
            "q3_accept_reject": {
                **{k: v for k, v in q3.items() if k != "neutral_accept"},
                "all_bad_episode_reject_rate": (
                    all_bad_rej / all_bad_n if all_bad_n else None),
                "all_bad_episode_rejected": all_bad_rej,
                "all_bad_episode_total": all_bad_n,
            },
            "q3_accept_reject_unit": {
                **{k: v for k, v in q3_unit.items()
                   if k not in ("neutral_accept",)},
                "coverage": q3_unit_coverage,
            },
        },
        "per_episode": _per_episode(gt_rows, cache, ep_repair_class),
        "per_family": _per_family(gt_rows, cache),
        "per_method": _per_method(gt_rows, cache),
    }
    _recursive_leak_check(summary)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    m = summary["main_metrics"]
    print("E7 main metrics:")
    print(f"  Q1 n={m['q1_pairwise']['n']} auroc={m['q1_pairwise']['auroc']:.4f} "
          f"acc={m['q1_pairwise']['accuracy']:.4f} "
          f"cat n={m['q1_pairwise']['catastrophic_n']} "
          f"cat auroc={m['q1_pairwise'].get('catastrophic_auroc')} "
          f"cat acc={m['q1_pairwise'].get('catastrophic_accuracy')}")
    print(f"  Q2 n_ep={m['q2_best_of_k']['n_episodes']} "
          f"top1={m['q2_best_of_k']['top1_hit_rate']:.4f} "
          f"top2={m['q2_best_of_k']['top2_hit_rate']:.4f} "
          f"oracle_acc={m['q2_best_of_k']['oracle_best_correct_rate']:.4f} "
          f"regret={m['q2_best_of_k']['ranking_regret_mean']:.4f} "
          f"[coverage: {m['q2_coverage']['evaluated_episodes']}/"
          f"{m['q2_coverage']['total_episodes']}]")
    print(f"  Q3 TPR={m['q3_accept_reject']['successful_repair_accept_rate_tpr']} "
          f"FNR={m['q3_accept_reject']['good_repair_rejected_rate_fnr']} "
          f"FPR={m['q3_accept_reject']['harmful_repair_accepted_rate_fpr']} "
          f"all_bad_reject={m['q3_accept_reject']['all_bad_episode_reject_rate']}")
    qu = m['q3_accept_reject_unit']
    print(f"  Q3-unit TPR={qu['successful_repair_accept_rate_tpr']} "
          f"FPR={qu['harmful_repair_accepted_rate_fpr']} "
          f"n={qu['n']}/{qu['n_all_gt_units']} gt_units "
          f"coverage_gt={qu['coverage_gt']:.3f}")
    print(f"  summary written to {out_path}")


if __name__ == "__main__":
    main()
