#!/usr/bin/env python3
"""E8: writeback policy offline evaluation.

Rebuilds the E3 frozen scorer (raw target), scores every ``e5_proposal``
candidate, and for each (episode x variant) evaluates which per-unit writeback
strategies recover errors without damaging previously-correct units.

GT discipline: the only GT input is ``E7_PER_UNIT_GT.jsonl`` (per-unit
new/old absolute errors).  Detector signals (``state`` / ``p_bad`` delta) only
decide *which* units are written back; GT status decides the before/after
repair state.  Raw error seconds never enter the output -- only aggregate
counts / status labels (``ok|mid|err``, avoiding the frozen feature forbidden
literals).
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
from lyricalign.realign_recovery.writeback_policy import (
    ALL_STRATEGIES,
    RowAccumulator,
    STRATEGY_FULL,
    STRATEGY_NO_WRITEBACK,
    aggregate_counts,
    gt_state,
    select_covered_unit_ids,
)
from lyricalign.research_v7.detector_v2_evidence import (
    FORBIDDEN_FEATURE_FIELDS,
)

_SCHEMA_VERSION = "realign_recovery_e8_eval_v1"
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


def _recursive_leak_check(value, *, skip_keys=frozenset(ALL_STRATEGIES)) -> None:
    """Recursively reject forbidden label fields as dict keys.

    E8 aggregates are keyed by strategy name (e.g. ``unsafe_only``), whose
    ``unsafe`` literal is in the forbidden set by design; those strategy keys
    are allowed, but every *value* underneath them is still checked.
    """
    if isinstance(value, dict):
        for k, v in value.items():
            if k in skip_keys:
                _recursive_leak_check(v, skip_keys=skip_keys)
            else:
                if k in FORBIDDEN_FEATURE_FIELDS:
                    raise ValueError(
                        f"feature row leaks forbidden label field: {k!r}")
                _recursive_leak_check(v, skip_keys=skip_keys)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _recursive_leak_check(v, skip_keys=skip_keys)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root", default=_DEFAULT_RUN)
    args = ap.parse_args(argv)

    run = Path(args.run_root)
    out_path = run / "e8_eval" / "E8_EVAL_SUMMARY.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scorer = build_frozen_scorer_from_artifacts(
        f"{_STAGE3B}/FROZEN_OPERATING_POINTS.json",
        f"{_STAGE3B}/LABELS.jsonl",
        f"{_STAGE3B}/evidence_v2",
        _ITEMS_DIRS,
        target="raw",
    )
    print(f"scorer ready: target={scorer.target} t=({scorer.t_accept:.4f},"
          f"{scorer.t_reject:.4f}) n_feat={len(scorer.feat_keys)}")

    requests = load_requests(run / "e5_proposals" / "raw" / "REQUESTS.jsonl")
    bank = load_bank(run / "e5_proposals" / "candidate_bank" / "candidate_bank.jsonl")
    gt_rows = _load_gt(run / "e7_input" / "E7_PER_UNIT_GT.jsonl")
    print(f"bank={len(bank)} gt_rows={len(gt_rows)}")

    gt_by_epv: dict[tuple[str, str], dict[int, dict]] = {}
    for r in gt_rows:
        gt_by_epv.setdefault((r["episode_id"], r["variant"]),
                             {})[int(r["canonical_unit_id"])] = r

    epv_units: dict[tuple[str, str], dict[int, dict]] = {}
    for cand in bank:
        if cand.get("ownership") != "e5_proposal":
            continue
        req_row, rows = candidate_evidence_rows(cand, requests)
        if req_row is None:
            continue
        prov = req_row.get("provenance") or {}
        ep = prov.get("episode_id")
        variant = req_row.get("input_variant")
        if not ep or not variant:
            continue
        u = score_units(scorer, rows)
        unit_map = {int(x["canonical_unit_id"]): x for x in u["units"]}
        epv_units[(ep, variant)] = unit_map
    print(f"scored candidate (episode,variant) groups: {len(epv_units)}")

    episodes = sorted({ep for (ep, _v) in gt_by_epv})
    per_epv: dict[tuple[str, str], dict[str, dict]] = {}
    per_episode: dict[str, dict[str, dict[str, dict]]] = {}
    per_strategy_rows: dict[str, RowAccumulator] = {
        st: RowAccumulator() for st in ALL_STRATEGIES
    }

    for ep in episodes:
        original_units = epv_units.get((ep, "original_full")) or {}
        old_p_bad = {cid: u["p_bad"] for cid, u in original_units.items()}
        variants = sorted({v for (e2, v) in gt_by_epv if e2 == ep
                           and v != "original_full"})
        per_episode[ep] = {}
        for variant in variants:
            gt_units = gt_by_epv[(ep, variant)]
            new_units = list((epv_units.get((ep, variant)) or {}).values())
            if not new_units:
                continue
            epv_strat: dict[str, dict] = {}
            for st in ALL_STRATEGIES:
                covered = select_covered_unit_ids(new_units, st, old_p_bad)
                acc = RowAccumulator()
                for cid, gt in sorted(gt_units.items()):
                    old_err = gt.get("old_error_sec")
                    if not gt.get("old_covered") or old_err is None:
                        continue
                    new_err = gt.get("new_error_sec")
                    if new_err is None:
                        continue
                    old_state = gt_state(old_err)
                    new_state = gt_state(new_err)
                    use_new = cid in covered
                    acc.add(
                        old_state,
                        new_state if use_new else old_state,
                        old_err,
                        new_err if use_new else old_err,
                    )
                epv_strat[st] = acc.result()
                per_strategy_rows[st].extend(acc._rows)
            per_epv[(ep, variant)] = epv_strat
            per_episode[ep][variant] = epv_strat

    per_strategy = {st: per_strategy_rows[st].result()
                    for st in ALL_STRATEGIES}

    harmful: dict[str, dict] = {}
    for st in ALL_STRATEGIES:
        if st == STRATEGY_NO_WRITEBACK:
            continue
        bad = 0
        n = 0
        deltas: list[float] = []
        for (ep, variant), epv_strat in sorted(per_epv.items()):
            base = (epv_strat.get(STRATEGY_NO_WRITEBACK) or {}).get(
                "net_improved", 0)
            wb = (epv_strat.get(st) or {}).get("net_improved", 0)
            n += 1
            if wb < base:
                bad += 1
            deltas.append(wb - base)
        harmful[st] = {
            "n_episode_variants": n,
            "harmful_episode_variants": bad,
            "harmful_episode_rate": bad / n if n else 0.0,
            "mean_delta_net_vs_no_writeback": (
                sum(deltas) / len(deltas) if deltas else 0.0),
        }

    summary = {
        "schema_version": _SCHEMA_VERSION,
        "inputs": {
            "run_root": str(run),
            "stage3b": str(_STAGE3B),
            "per_unit_gt": str(run / "e7_input" / "E7_PER_UNIT_GT.jsonl"),
            "scorer_target": "raw",
            "improved_delta": 0.05,
        },
        "episode_count": len(per_episode),
        "strategy_count": len(per_strategy),
        "per_strategy": per_strategy,
        "harmful_writeback": harmful,
        "main": {
            st: {
                "net_improved": per_strategy[st]["net_improved"],
                "catastrophic_reduction": per_strategy[st]["catastrophic_reduction"],
                "harmful_episode_rate": harmful.get(st, {}).get(
                    "harmful_episode_rate", None),
            }
            for st in ALL_STRATEGIES
        },
        "per_episode": per_episode,
    }
    _recursive_leak_check(summary)
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print("\nE8 main metrics:")
    print(f"  {'strategy':<22} {'net_imp':>9} {'cat_reduc':>10} {'harmful_ep':>11}")
    for st in ALL_STRATEGIES:
        m = summary["main"][st]
        print(f"  {st:<22} {m['net_improved']:>9} {m['catastrophic_reduction']:>10}"
              f" {m['harmful_episode_rate'] if m['harmful_episode_rate'] is not None else '-':>11}")
    print(f"  summary written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
