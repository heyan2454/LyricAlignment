"""E7 pure metrics: detector-judges-realign-quality scoring helpers.

All functions here are no-GT and side-effect free, so they are unit-testable
with synthetic data.  Field names avoid the frozen feature forbidden list
(``family``/``safe``/``unsafe``/``grey``/... are reserved), so aggregated
dicts can be passed through ``assert_no_label_leak`` untouched.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence


def auroc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    """Rank-based AUROC (Mann-Whitney, tie-corrected via average ranks).

    Returns ``None`` when either class is absent (single-class degeneracy).
    """
    if len(scores) != len(labels) or not scores:
        return None
    pairs = sorted(zip(scores, labels), key=lambda p: p[0])
    n_pos = sum(1 for _, lab in pairs if lab)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1
    sum_pos_ranks = sum(r for (_, lab), r in zip(pairs, ranks) if lab)
    return (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _accuracy(deltas: Sequence[float], improved: Sequence[bool]) -> float:
    n = len(deltas)
    if n == 0:
        return 0.0
    return sum(1 for d, i in zip(deltas, improved) if (d > 0) == i) / n


def pairwise_metrics(
    deltas: Sequence[float],
    improved: Sequence[bool],
    old_errors: Sequence[float | None],
    threshold: float = 1.0,
) -> dict:
    """Q1: unit-level pairwise old-vs-new statistics.

    detector signal = ``delta_p_bad`` (old - new); improved when
    ``new_error < old_error - 1e-6``.  Also reports the catastrophic subset
    (old_error > threshold) separately.
    """
    pairs = [(d, i, o) for d, i, o in zip(deltas, improved, old_errors)
             if o is not None]
    res: dict = {
        "n": len(pairs),
        "auroc": auroc([d for d, _, _ in pairs],
                       [1 if i else 0 for _, i, _ in pairs]),
        "accuracy": _accuracy([d for d, _, _ in pairs],
                              [i for _, i, _ in pairs]),
        "threshold_sec": threshold,
    }
    cat = [(d, i) for d, i, o in pairs if o > threshold]
    res["catastrophic_n"] = len(cat)
    if cat:
        res["catastrophic_auroc"] = auroc(
            [d for d, _ in cat], [1 if i else 0 for _, i in cat])
        res["catastrophic_accuracy"] = _accuracy(
            [d for d, _ in cat], [i for _, i in cat])
    return res


def rank_metrics(
    episodes: Sequence[Mapping[str, object]],
    k: int = 2,
) -> dict:
    """Q2: episode-level best-of-K ranking statistics.

    Each episode: ``{"scored_variants": [(variant, score), ...],
    "gt_best": variant, "gt_best_is_oracle": bool}``.  Ranking is by score
    descending; only episodes whose ``gt_best`` carries a detector score are
    counted (no-score gt_best would force an unfair max regret).
    """
    top1 = top2 = n = oracle_n = oracle_hits = 0
    regret_sum = 0.0
    for ep in episodes:
        scored = [(v, s) for v, s in ep["scored_variants"] if s is not None]
        ranked = [v for v, _ in sorted(scored, key=lambda t: -t[1])]
        gb = ep["gt_best"]
        if gb not in ranked:
            continue
        n += 1
        pos = ranked.index(gb)
        if pos == 0:
            top1 += 1
        if pos < k:
            top2 += 1
        regret_sum += pos
        if ep["gt_best_is_oracle"]:
            oracle_n += 1
            if pos == 0:
                oracle_hits += 1
    return {
        "n_episodes": n,
        "top1_hit_rate": top1 / n if n else 0.0,
        "top2_hit_rate": top2 / n if n else 0.0,
        "ranking_regret_mean": regret_sum / n if n else 0.0,
        "oracle_best_n": oracle_n,
        "oracle_best_correct_rate": oracle_hits / oracle_n if oracle_n else 0.0,
        "top1_hits": top1,
        "top2_hits": top2,
    }


def classify_repair(
    old_errors: Sequence[float | None],
    new_errors: Sequence[float | None],
    threshold: float = 1.0,
) -> str:
    """Q3: GT repair class for one episode x variant.

    ``old_errors`` is per canonical unit (None = old not covered), aligned
    with ``new_errors``.  Returns ``successful_repair`` | ``harmful`` |
    ``neutral``.
    """
    old_unsafe = [i for i, o in enumerate(old_errors)
                  if o is not None and o > threshold]
    new_safe = all(e is not None and e <= threshold
                   for e in new_errors if e is not None)
    if old_unsafe and new_errors and new_safe:
        return "successful_repair"
    safe_to_unsafe = sum(
        1 for i, (o, e) in enumerate(zip(old_errors, new_errors))
        if o is not None and e is not None and o <= threshold and e > threshold)
    unsafe_to_safe = sum(
        1 for i, (o, e) in enumerate(zip(old_errors, new_errors))
        if o is not None and e is not None and o > threshold and e <= threshold)
    if safe_to_unsafe > 0 or (bool(old_unsafe) and unsafe_to_safe == 0):
        return "harmful"
    return "neutral"


def classify_unit_repair(
    old_error: float | None,
    new_error: float | None,
    threshold: float = 1.0,
) -> str:
    """Q3: GT repair class for a single canonical unit (writeback view).

    ``old_error`` is the baseline absolute error (``None`` = old not covered);
    ``new_error`` is the candidate error.  Returns ``successful_repair`` |
    ``harmful`` | ``neutral``.

    Semantics differ from ``classify_repair`` (candidate/episode level) on
    purpose and must NOT be compared directly:
    - unit level: ``harmful`` = a previously-safe unit became unsafe
      (safe->unsafe, i.e. the writeback actively damaged it); unsafe->unsafe
      (no improvement, no damage) is ``neutral``.  This matches the E8
      selective-writeback view where untouched units keep their old state.
    - candidate level: ``classify_repair`` treats "had unsafe units but
      repaired none" as ``harmful`` (no net benefit to write the whole
      candidate back).
    """
    if old_error is None or new_error is None:
        return "neutral"
    old_unsafe = old_error > threshold
    new_safe = new_error <= threshold
    if old_unsafe and new_safe:
        return "successful_repair"
    if (not old_unsafe) and (not new_safe):
        return "harmful"
    return "neutral"


def accept_reject_metrics(rows: Sequence[Mapping[str, object]]) -> dict:
    """Q3: accept/reject confusion on episode x variant level.

    Each row: ``{"repair_class": ..., "detector_accept": bool}``.
    """
    tp = fn = fp = tn = 0
    neutral_acc = neutral_rej = 0
    for r in rows:
        cls = r["repair_class"]
        acc = bool(r["detector_accept"])
        if cls == "successful_repair":
            if acc:
                tp += 1
            else:
                fn += 1
        elif cls == "harmful":
            if acc:
                fp += 1
            else:
                tn += 1
        else:
            if acc:
                neutral_acc += 1
            else:
                neutral_rej += 1
    tpr = tp / (tp + fn) if tp + fn else None
    fpr = fp / (fp + tn) if fp + tn else None
    return {
        "n": len(rows),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "successful_repair_accept_rate_tpr": tpr,
        "good_repair_rejected_rate_fnr": (1 - tpr) if tpr is not None else None,
        "harmful_repair_accepted_rate_fpr": fpr,
        "neutral_accept": neutral_acc,
        "neutral_reject": neutral_rej,
        "neutral_total": neutral_acc + neutral_rej,
    }


def unit_accept_reject_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    n_all_gt_units: int | None = None,
    n_all_det_units: int | None = None,
) -> dict:
    """Q3-unit: accept/reject confusion on canonical-unit granularity.

    Each row: ``{"repair_class": ..., "detector_accept": bool}`` for a single
    unit (per-unit ``state == accept`` is the writeback gate).  This is the
    per-unit view of ``accept_reject_metrics``.

    ``rows`` covers only units that have both a GT old and new error AND belong
    to a scored candidate (detector state exists or conservatively rejected);
    ``n_all_gt_units`` / ``n_all_det_units`` expose the denominators so the
    coverage ratio can be reconstructed (the Q3-unit sample is a strict subset
    of GT units with full error pairs).
    """
    base = accept_reject_metrics(rows)
    n_covered = sum(1 for r in rows
                    if r.get("repair_class") in ("successful_repair", "harmful"))
    base = dict(base)
    base["n_covered_status"] = n_covered
    base["n_all_gt_units"] = n_all_gt_units
    base["n_all_det_units"] = n_all_det_units
    base["coverage_gt"] = (len(rows) / n_all_gt_units
                           if n_all_gt_units else None)
    return base
