"""Natural-Mandarin real-recording panel: MIR-1K human character GT x retained predictions.

What is new here
----------------
MIR-1K's *partial-align* subset carries **human per-character onset/offset** annotations
(``MIR1k_partial_align.json`` -> ``on_offset``), on real accompanied studio recordings, and the
project evaluated five/six different predictors on exactly that set in 2026-07-22/24.  All of it was
only ever summarised as a single scalar per run (``results/by_run/*/metrics*.json`` -> ``loss``).
No unit-level, position-level or cross-predictor analysis of natural Mandarin singing exists.

Reference provenance (checked on 2026-09-12, deliberately contrasted with round 3's trap)
----------------------------------------------------------------------------------------
* ``prepare_mir1k_partial_align.py`` keeps only records with ``on_offset`` and
  ``datasets/mir1k.py:prepare_partial_align_item`` merely validates monotonicity/duration: the times
  are the annotation itself, **not** a uniform re-timing (round 3's
  ``LONG_TIMELINE_MANIFEST.canonical_units`` lesson).
* MIR-1K is ``test-only`` in ``data/datasets_registry.md``: nothing here may be used to pick
  checkpoints or tune mechanisms; results are reporting only.

Every analysis is recomputed from per-character reference/prediction pairs (the project's own rule
for metric fixes), and the recomputation is reconciled against the frozen corrected metrics file so
a mis-join cannot masquerade as a result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DATA = Path("/home/hyan/Data/lyricalign")
GT_CHARS = DATA / "derived/mir1k_partial_align_v2/mir1k_partial_align_characters.jsonl"
GT_MANIFEST = DATA / "derived/mir1k_partial_align_v2/mir1k_partial_align_manifest.jsonl"
PRED_RUNS = {
    "base_qwen_raw_v1": DATA / "evaluation/mir1k_qwen_raw_v1_predictions.jsonl",
    "r0_raw_20260724": DATA / "runs/20260724_qwen_fa_r0_raw_mir1k_ood/predictions.jsonl",
    "r1_full_20260724": DATA / "runs/20260724_qwen_fa_r1_full_mir1k_ood/predictions.jsonl",
    "r2_full_20260723": DATA / "runs/20260723_qwen_fa_r2_full_mir1k_ood/predictions.jsonl",
    "r2_seed_20260724": DATA / "runs/20260724_qwen_fa_r2_full_seed20260724_mir1k_ood/predictions.jsonl",
    "r2_ood_20260723": DATA / "runs/20260723_qwen_fa_r2_mir1k_ood/predictions.jsonl",
}
TOLS = (0.100, 0.200, 0.250)
SEED = 20260912
N_BOOT = 1000


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def build_panel() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Join every retained predictor to the human character reference."""
    gt = read_jsonl(GT_CHARS)
    ref = {(r["item_id"], int(r["character_index"])): r for r in gt}
    # the per-item character count comes from the reference itself (the manifest row does not carry
    # `character_count`, and reading a missing key as 0 silently destroyed the position analysis)
    char_counts: dict[str, int] = {}
    gt_last_end: dict[str, float] = {}
    for (item, idx), r in ref.items():
        char_counts[item] = max(char_counts.get(item, 0), idx + 1)
        gt_last_end[item] = max(gt_last_end.get(item, 0.0), float(r["end_sec"]))
    meta = {}
    if GT_MANIFEST.exists():
        for row in read_jsonl(GT_MANIFEST):
            meta[str(row.get("item_id"))] = row

    records: list[dict[str, Any]] = []
    audit: dict[str, Any] = {
        "schema": "mir1k_natural_panel_v1",
        "reference": {"path": str(GT_CHARS), "sha256": sha256(GT_CHARS),
                      "characters": len(gt), "items": len({k[0] for k in ref}),
                      "provenance": "human per-character on/off (MIR1k_partial_align.json on_offset)"},
        "predictors": {},
    }
    for label, path in PRED_RUNS.items():
        if not path.exists():
            audit["predictors"][label] = {"present": False, "path": str(path)}
            continue
        rows = read_jsonl(path)
        matched = missed = char_mismatch = 0
        for r in rows:
            key = (str(r.get("item_id")), int(r.get("character_index", -1)))
            g = ref.get(key)
            if g is None:
                missed += 1
                continue
            if str(r.get("normalized_character", "")) != str(g.get("normalized_character", "")):
                char_mismatch += 1
            ps, pe = r.get("start_sec"), r.get("end_sec")
            if ps is None or pe is None:
                continue
            gs, ge = float(g["start_sec"]), float(g["end_sec"])
            m = meta.get(key[0], {})
            n_chars = int(char_counts.get(key[0], 0))
            dur = float(m.get("duration_sec") or 0.0) or round(gt_last_end.get(key[0], 0.0) + 1.0, 3)
            records.append({
                "predictor": label, "item_id": key[0], "character_index": key[1],
                "character": str(g.get("normalized_character", "")),
                "gt_start_sec": round(gs, 4), "gt_end_sec": round(ge, 4),
                "gt_dur_sec": round(ge - gs, 4),
                "pred_start_sec": round(float(ps), 4), "pred_end_sec": round(float(pe), 4),
                "item_duration_sec": round(dur, 3),
                "item_chars": n_chars,
                "vocal_source": (m.get("audio_contract") or {}).get("vocal_source_type", ""),
                "frac_pos": round(key[1] / max(n_chars - 1, 1), 4),
                "is_first_char": 1.0 if key[1] == 0 else 0.0,
                "is_last_char": 1.0 if key[1] == n_chars - 1 else 0.0,
            })
            matched += 1
        audit["predictors"][label] = {
            "present": True, "path": str(path), "sha256": sha256(path),
            "rows": len(rows), "matched_to_reference": matched,
            "unmatched_rows": missed, "character_mismatches": char_mismatch,
        }
    df = pd.DataFrame(records)
    df["start_err"] = (df["pred_start_sec"] - df["gt_start_sec"]).abs()
    df["end_err"] = (df["pred_end_sec"] - df["gt_end_sec"]).abs()
    df["both_err"] = np.maximum(df["start_err"], df["end_err"])
    df["start_signed"] = df["pred_start_sec"] - df["gt_start_sec"]
    df["end_signed"] = df["pred_end_sec"] - df["gt_end_sec"]
    inter = np.clip(np.minimum(df["pred_end_sec"], df["gt_end_sec"])
                    - np.maximum(df["pred_start_sec"], df["gt_start_sec"]), 0, None)
    union = np.maximum(df["pred_end_sec"], df["gt_end_sec"]) - np.minimum(
        df["pred_start_sec"], df["gt_start_sec"])
    df["iou"] = np.where(union > 0, inter / union, 0.0)
    for tol in TOLS:
        df[f"hit{int(tol * 1000)}"] = (df["both_err"] <= tol + 1e-9).astype(float)
    df["pred_reaches_zero"] = (df["pred_start_sec"].abs() <= 1e-6).astype(float)
    return df, audit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _auc(y: np.ndarray, s: np.ndarray, min_n: int = 30) -> float | None:
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    ok = np.isfinite(y) & np.isfinite(s)
    y, s = y[ok], s[ok]
    if len(y) < min_n or y.min() == y.max():
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    n_pos = float(y.sum())
    n_neg = float(len(y) - n_pos)
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _seg_ci(values: np.ndarray, groups: np.ndarray) -> tuple[float, list[float]]:
    uniq = np.unique(groups)
    idx = {g: np.flatnonzero(groups == g) for g in uniq}
    point = float(values.mean())
    if len(uniq) < 2:
        return point, [point, point]
    rng = np.random.default_rng(SEED)
    draws = np.empty(N_BOOT)
    for i in range(N_BOOT):
        picked = rng.choice(uniq, len(uniq), True)
        draws[i] = values[np.concatenate([idx[g] for g in picked])].mean()
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return point, [round(float(lo), 4), round(float(hi), 4)]


def _profile(sub: pd.DataFrame) -> dict[str, Any]:
    if sub.empty:
        return {"n": 0}
    g = sub["item_id"].to_numpy()
    hit, ci = _seg_ci(sub["hit100"].to_numpy(dtype=float), g)
    hit250, ci250 = _seg_ci(sub["hit250"].to_numpy(dtype=float), g)
    return {
        "n_units": int(len(sub)), "n_items": int(sub["item_id"].nunique()),
        "hit100": round(float(sub["hit100"].mean()), 4),
        "hit100_item_boot": round(hit, 4), "hit100_ci95_item_boot": ci,
        "hit200": round(float(sub["hit200"].mean()), 4),
        "hit250": round(float(sub["hit250"].mean()), 4),
        "hit250_item_boot": round(hit250, 4), "hit250_ci95_item_boot": ci250,
        "mae_start": round(float(sub["start_err"].mean()), 4),
        "mae_end": round(float(sub["end_err"].mean()), 4),
        "median_both": round(float(sub["both_err"].median()), 4),
        "p90_both": round(float(np.percentile(sub["both_err"], 90)), 4),
        "iou_mean": round(float(sub["iou"].mean()), 4),
        "mean_signed_start": round(float(sub["start_signed"].mean()), 4),
        "median_signed_start": round(float(sub["start_signed"].median()), 4),
        "mean_signed_end": round(float(sub["end_signed"].mean()), 4),
        "share_start_late_gt100": round(float((sub["start_signed"] > 0.1).mean()), 4),
        "share_start_early_gt100": round(float((sub["start_signed"] < -0.1).mean()), 4),
        "pred_at_zero_share": round(float(sub["pred_reaches_zero"].mean()), 4),
    }


# ---------------------------------------------------------------------------
# analyses
# ---------------------------------------------------------------------------

def analyse(df: pd.DataFrame, audit: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"schema": "mir1k_natural_analysis_v1", "usage": "test-only reporting",
                           "audit": audit, "panel": {
                               "unit_rows": int(len(df)), "items": int(df["item_id"].nunique()),
                               "predictors": sorted(set(df["predictor"])),
                               "item_duration_sec": {"min": round(float(df.groupby("item_id")["item_duration_sec"].first().min()), 1),
                                                     "median": round(float(df.groupby("item_id")["item_duration_sec"].first().median()), 1),
                                                     "max": round(float(df.groupby("item_id")["item_duration_sec"].first().max()), 1)},
                               "gt_dur_quantiles": {str(q): round(float(np.percentile(df["gt_dur_sec"], q)), 4)
                                                    for q in (5, 25, 50, 75, 95)},
                               "gt_first_onset_median_sec": round(float(
                                   df[df["is_first_char"] == 1]["gt_start_sec"].median()), 3),
                               "vocal_sources": sorted({str(v) for v in df["vocal_source"]})}}

    out["by_predictor"] = {str(p): _profile(sub) for p, sub in df.groupby("predictor", observed=True)}

    # A. checkpoint ladder + run-to-run reproducibility on natural recordings
    names = sorted(set(df["predictor"]))
    pairs: dict[str, Any] = {}
    for a, b in [("r0_raw_20260724", "r1_full_20260724"), ("r1_full_20260724", "r2_full_20260723"),
                 ("r2_full_20260723", "r2_seed_20260724"), ("r2_full_20260723", "r2_ood_20260723"),
                 ("base_qwen_raw_v1", "r2_full_20260723")]:
        if a not in names or b not in names:
            continue
        sa = df[df["predictor"] == a].set_index(["item_id", "character_index"])
        sb = df[df["predictor"] == b].set_index(["item_id", "character_index"])
        both = sa[["pred_start_sec", "pred_end_sec"]].join(
            sb[["pred_start_sec", "pred_end_sec"]], lsuffix="_a", rsuffix="_b", how="inner")
        if both.empty:
            continue
        spread = np.maximum((both["pred_start_sec_a"] - both["pred_start_sec_b"]).abs(),
                            (both["pred_end_sec_a"] - both["pred_end_sec_b"]).abs()).to_numpy(dtype=float)
        ea = df[df["predictor"] == a].set_index(["item_id", "character_index"])["both_err"]
        eb = df[df["predictor"] == b].set_index(["item_id", "character_index"])["both_err"]
        delta = (ea - eb).reindex(both.index).dropna()
        pairs[f"{a}__vs__{b}"] = {
            "n_units": int(len(both)),
            "agree_within_20ms": round(float((spread <= 0.02).mean()), 4),
            "agree_within_100ms": round(float((spread <= 0.1).mean()), 4),
            "median_spread_sec": round(float(np.median(spread)), 4),
            "p90_spread_sec": round(float(np.percentile(spread, 90)), 4),
            "max_spread_sec": round(float(spread.max()), 3),
            "hit100_delta_pp": round(float(
                (df[df["predictor"] == a]["hit100"].mean()
                 - df[df["predictor"] == b]["hit100"].mean()) * 100.0), 3),
            "paired_err_delta_mean_sec": round(float(delta.mean()), 4),
        }
    out["predictor_pairs"] = pairs

    # B. position effects, per predictor (pooling predictors mixes a 22.6% system with 92% ones)
    def pos_profile(sub: pd.DataFrame) -> dict[str, Any]:
        buckets = pd.cut(sub["frac_pos"], [-0.01, 0.001, 0.1, 0.9, 0.999, 1.01],
                         labels=["first char", "early", "middle", "late", "last char"])
        tab = sub.assign(pos_bucket=buckets).groupby("pos_bucket", observed=True).agg(
            n=("hit100", "size"), hit100=("hit100", "mean"), mae_start=("start_err", "mean"),
            signed_start=("start_signed", "mean"), signed_end=("end_signed", "mean"),
            at_zero=("pred_reaches_zero", "mean")).reset_index()
        return {"by_position": [{"bucket": str(r.pos_bucket), "n": int(r.n),
                                 "hit100": round(float(r.hit100), 4),
                                 "mae_start": round(float(r.mae_start), 4),
                                 "mean_signed_start": round(float(r.signed_start), 4),
                                 "mean_signed_end": round(float(r.signed_end), 4),
                                 "share_pred_start_at_zero": round(float(r.at_zero), 4)}
                                for r in tab.itertuples()],
                "first_char": _profile(sub[sub["is_first_char"] == 1]),
                "last_char": _profile(sub[sub["is_last_char"] == 1])}

    out["position_effects"] = {str(pname): pos_profile(sub)
                               for pname, sub in df.groupby("predictor", observed=True)}
    out["position_effect_note"] = (
        "MIR-1K human GT first onsets are all > 0.2 s (median "
        f"{out['panel']['gt_first_onset_median_sec']} s), so a predicted start of 0.0 is "
        "unambiguously wrong here -- unlike GTSinger, where every clip starts at 0.0 and the same "
        "prediction is free-correct")

    # C. length effect in natural audio, per predictor
    def length_profile(sub: pd.DataFrame) -> dict[str, Any]:
        dur = sub.groupby("item_id", observed=True)["item_duration_sec"].first()
        per_item = sub.groupby(["predictor", "item_id"], observed=True).agg(
            hit100=("hit100", "mean"), mae=("both_err", "mean"),
            dur=("item_duration_sec", "first"), chars=("character_index", "size")).reset_index()
        per_item["dur_bucket"] = pd.cut(per_item["dur"], [0, 45, 60, 75, 90, 1e9],
                                        labels=["<=45s", "45-60s", "60-75s", "75-90s", ">90s"])
        tab = per_item.groupby("dur_bucket", observed=True).agg(
            n_items=("hit100", "size"), hit100=("hit100", "mean"),
            mae=("mae", "mean")).reset_index()

        def corr(x, y):
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            if len(x) < 4 or x.std() == 0 or y.std() == 0:
                return None
            return round(float(np.corrcoef(x, y)[0, 1]), 4)

        return {"items_over_60s": int((dur > 60).sum()), "items_over_90s": int((dur > 90).sum()),
                "by_item_duration": [{"bucket": str(r.dur_bucket), "n_items": int(r.n_items),
                                      "hit100": round(float(r.hit100), 4),
                                      "mae_sec": round(float(r.mae), 4)} for r in tab.itertuples()],
                "pearson_hit100_vs_item_duration": corr(per_item["hit100"], per_item["dur"]),
                "pearson_hit100_vs_char_count": corr(per_item["hit100"], per_item["chars"])}

    out["length_effect"] = {str(pname): length_profile(sub)
                            for pname, sub in df.groupby("predictor", observed=True)}

    # D. no-GT signal: cross-predictor disagreement, with the predictor set controlled explicitly
    present_preds = sorted(set(df["predictor"]))
    ref_pred = "r2_full_20260723" if "r2_full_20260723" in present_preds else (
        max(present_preds, key=lambda x: out["by_predictor"][x]["hit100"]) if present_preds else "")
    ref_hit0 = out["by_predictor"].get(ref_pred, {}).get("hit100", 0.0)
    # Ensemble membership is derived, not hard-coded: a system whose own accuracy is below half
    # the reference is a different instrument, not a second opinion, and mixing it in was shown to
    # *hurt* the disagreement signal (see the including_weak variant).
    weak = [x for x in present_preds
            if x != ref_pred and out["by_predictor"][x]["hit100"] < 0.5 * max(ref_hit0, 1e-9)]
    strong = [x for x in present_preds if x not in weak and x != ref_pred]
    families = {
        "strong_peers_only": [ref_pred] + strong,
        "including_weak_systems": [ref_pred] + strong + weak,
    }
    membership_note = {
        "reference_predictor": ref_pred,
        "weak_excluded": weak,
        "rule": "a peer enters the ensemble only if its own hit@100 is >= half the reference's",
    }
    disq: dict[str, Any] = {"reference_predictor": ref_pred, "membership": membership_note,
                           "sets": {}}
    ref_rows = (df[df["predictor"] == ref_pred].set_index(["item_id", "character_index"])
                if ref_pred else pd.DataFrame())
    for set_name, preds in families.items():
        present = [x for x in preds if x in set(df["predictor"])]
        others = [x for x in present if x != ref_pred]
        if len(others) < 2 or ref_rows.empty:
            continue
        wide = df[df["predictor"].isin(present)].pivot_table(
            index=["item_id", "character_index"], columns="predictor",
            values=["pred_start_sec", "pred_end_sec"], aggfunc="first")
        starts = wide["pred_start_sec"][others]
        ends = wide["pred_end_sec"][others]
        spread = np.maximum(starts.max(axis=1) - starts.min(axis=1),
                            ends.max(axis=1) - ends.min(axis=1))
        joined = ref_rows[["hit100", "both_err", "start_err", "end_err"]].join(
            spread.rename("spread"), how="inner").dropna(subset=["spread"])
        entry: dict[str, Any] = {"predictors": present, "n_units": int(len(joined)),
                                 "median_spread_sec": round(float(joined["spread"].median()), 4),
                                 "p90_spread_sec": round(float(joined["spread"].quantile(.9)), 4)}
        for tol, tag in ((0.1, "bad100"), (0.25, "bad250")):
            y = (joined["both_err"] > tol).to_numpy(dtype=float)
            a = _auc(y, joined["spread"].to_numpy(dtype=float))
            entry[f"auc_spread_vs_{tag}"] = None if a is None else round(a, 4)
            entry[f"positive_rate_{tag}"] = round(float(y.mean()), 4)
            rc = {}
            for frac in (0.05, 0.1, 0.2):
                thr = float(np.quantile(joined["spread"].to_numpy(dtype=float), 1 - frac))
                flagged = (joined["spread"] >= thr).to_numpy(dtype=float)
                rc[f"flag_{int(frac*100)}pct"] = {
                    "precision": round(float((flagged * y).sum() / max(flagged.sum(), 1)), 4),
                    "recall": round(float((flagged * y).sum() / max(y.sum(), 1)), 4)}
            entry["review_budget_curve"] = rc
        disq["sets"][set_name] = entry
    out["disagreement_signal_natural"] = disq

    # E. per-item dispersion (what a per-song quality gate has to live with)
    if ref_pred:
        per_item_hits = (df[df["predictor"] == ref_pred]
                         .groupby("item_id", observed=True)
                         .agg(hit100=("hit100", "mean"), mae=("both_err", "mean"),
                              dur=("item_duration_sec", "first"),
                              chars=("character_index", "size")))
    else:
        per_item_hits = pd.DataFrame(columns=["hit100", "mae", "dur", "chars"])
    if per_item_hits.empty:
        out["per_item_variance"] = {"reference_predictor": ref_pred, "items": 0,
                                    "note": "no reference predictor available"}
    else:
        out["per_item_variance"] = {
            "reference_predictor": ref_pred, "items": int(len(per_item_hits)),
            "hit100_across_items": {
                "min": round(float(per_item_hits["hit100"].min()), 4),
                "p25": round(float(per_item_hits["hit100"].quantile(.25)), 4),
                "median": round(float(per_item_hits["hit100"].median()), 4),
                "p75": round(float(per_item_hits["hit100"].quantile(.75)), 4),
                "max": round(float(per_item_hits["hit100"].max()), 4)},
            "worst_5_items": [{"item": str(i), "hit100": round(float(r.hit100), 4),
                               "mae_sec": round(float(r.mae), 4),
                               "dur_sec": round(float(r.dur), 1), "chars": int(r.chars)}
                              for i, r in per_item_hits.nsmallest(5, "hit100").iterrows()],
            "best_5_items": [{"item": str(i), "hit100": round(float(r.hit100), 4),
                              "mae_sec": round(float(r.mae), 4),
                              "dur_sec": round(float(r.dur), 1), "chars": int(r.chars)}
                             for i, r in per_item_hits.nlargest(5, "hit100").iterrows()],
            "note": "item-level dispersion is what a per-song quality gate has to live with"}

    # F. structural defect counts per predictor (invalid / zero-duration / out-of-range)
    defects = {}
    for pname, sub in df.groupby("predictor", observed=True):
        dur = (sub["pred_end_sec"] - sub["pred_start_sec"]).to_numpy(dtype=float)
        defects[str(pname)] = {
            "n": int(len(sub)),
            "zero_or_negative_duration_share": round(float((dur <= 1e-9).mean()), 5),
            "negative_duration_share": round(float((dur < -1e-9).mean()), 5),
            "start_after_gt_end_share": round(float(
                (sub["pred_start_sec"] > sub["gt_end_sec"]).mean()), 5),
            "pred_start_at_zero_share": round(float(sub["pred_reaches_zero"].mean()), 5),
            "out_of_item_range_share": round(float(
                ((sub["pred_end_sec"] > sub["item_duration_sec"] + 0.05)
                 & (sub["item_duration_sec"] > 0)).mean()), 5)}
    out["structural_defects_by_predictor"] = defects

    # G. reconciliation against the project's frozen canonical metrics (lineage gate)
    recon = {}
    run_map = {
        "r2_full_20260723": "20260723_qwen_fa_r2_full_mir1k_ood",
        "r2_seed_20260724": "20260724_qwen_fa_r2_full_seed20260724_mir1k_ood",
        "r2_ood_20260723": "20260723_qwen_fa_r2_mir1k_ood",
    }
    results_root = Path("/home/hyan/LyricAlignment/results/by_run")
    for pname, run_name in run_map.items():
        if pname not in out["by_predictor"]:
            continue                      # never emit a reconciliation row for an absent predictor
        for suffix in ("metrics.corrected.json", "metrics.json"):
            f = results_root / run_name / suffix
            if not f.exists():
                continue
            try:
                canon = json.loads(f.read_text(encoding="utf-8")).get("metric", {})
            except (OSError, ValueError):
                continue
            if not canon:
                continue
            mine = out["by_predictor"].get(pname, {})
            entry = {
                "canonical_file": f"{run_name}/{suffix}",
                "canonical_mean_iou": canon.get("mean_iou"),
                "recomputed_iou_mean": mine.get("iou_mean"),
                "iou_delta": (None if canon.get("mean_iou") is None or mine.get("iou_mean") is None
                              else round(float(mine["iou_mean"]) - float(canon["mean_iou"]), 5)),
                "canonical_onset_mae_sec": canon.get("onset_mae_sec"),
                "recomputed_mae_start_sec": mine.get("mae_start"),
                "canonical_invalid_prediction_count": canon.get("invalid_prediction_count"),
                "recomputed_zero_or_negative_duration": (
                    out["structural_defects_by_predictor"].get(pname, {})
                    .get("zero_or_negative_duration_share")),
                "canonical_joint_within_160ms": canon.get("joint_within_160ms"),
                "recomputed_hit200": mine.get("hit200"),
                "verdict": None,
            }
            if entry["iou_delta"] is not None:
                entry["verdict"] = ("join_ok" if abs(entry["iou_delta"]) < 2e-3
                                    else "join_mismatch")
            recon[pname] = entry
            break
    out["canonical_reconciliation"] = {"per_predictor": recon,
                                       "note": "mean_iou is the only quantity defined identically in "
                                               "both implementations; MAE differences trace to the "
                                               "canonical song-macro / invalid-penalty conventions"}

    # H. error clustering on natural recordings (round 1's region question, new domain)
    runs_len: dict[int, int] = {}
    for (_p, item), g in df[df["predictor"].isin([ref_pred])].groupby(
            ["predictor", "item_id"], observed=True):
        arr = (g.sort_values("character_index")["both_err"] > 0.1).to_numpy(dtype=float)
        cur = 0
        for v in arr:
            if v:
                cur += 1
            elif cur:
                runs_len[cur] = runs_len.get(cur, 0) + 1
                cur = 0
        if cur:
            runs_len[cur] = runs_len.get(cur, 0) + 1
    tot = sum(k * v for k, v in runs_len.items()) or 1
    ref_hit = out["by_predictor"].get(ref_pred, {}).get("hit100")
    out["error_runs_natural"] = {
        "reference_predictor": ref_pred, "tolerance_sec": 0.1,
        "run_lengths": {str(k): v for k, v in sorted(runs_len.items())},
        "share_bad_in_runs_ge2": round(float(sum(k * v for k, v in runs_len.items() if k >= 2) / tot), 4),
        "bad_rate": None if ref_hit is None else round(float(1 - ref_hit), 4),
    }
    return out

# ---------------------------------------------------------------------------
# follow-ups raised by the first pass on this panel
# ---------------------------------------------------------------------------

def analyse_last_character(df: pd.DataFrame, ref_pred: str) -> dict[str, Any]:
    """Attribute the last-character deficit: truncation, duration, or onset-only shift?"""
    d = df[df["predictor"] == ref_pred]
    last = d[d["is_last_char"] == 1]
    mid = d[(d["frac_pos"] > 0.1) & (d["frac_pos"] < 0.9)]
    if last.empty:
        return {"available": False}
    out: dict[str, Any] = {"available": True, "reference_predictor": ref_pred,
                           "n_last": int(len(last)), "n_middle": int(len(mid))}
    out["last_signature"] = {
        "hit100": round(float(last["hit100"].mean()), 4),
        "mae_start": round(float(last["start_err"].mean()), 4),
        "mae_end": round(float(last["end_err"].mean()), 4),
        "signed_end_mean": round(float(last["end_signed"].mean()), 4),
        "signed_end_median": round(float(last["end_signed"].median()), 4),
        "signed_start_mean": round(float(last["start_signed"].mean()), 4),
        "start_hit100_only": round(float((last["start_err"] <= 0.1).mean()), 4),
        "end_hit100_only": round(float((last["end_err"] <= 0.1).mean()), 4),
        "pred_end_beyond_item_share": round(float(
            (last["pred_end_sec"] > last["item_duration_sec"]).mean()), 4),
        "gt_end_beyond_item_share": round(float(
            (last["gt_end_sec"] > last["item_duration_sec"]).mean()), 4),
        "mean_gt_dur": round(float(last["gt_dur_sec"].mean()), 4),
        "mean_pred_dur": round(float((last["pred_end_sec"] - last["pred_start_sec"]).mean()), 4),
    }
    out["middle_signature"] = {
        "hit100": round(float(mid["hit100"].mean()), 4),
        "start_hit100_only": round(float((mid["start_err"] <= 0.1).mean()), 4),
        "end_hit100_only": round(float((mid["end_err"] <= 0.1).mean()), 4),
        "mean_gt_dur": round(float(mid["gt_dur_sec"].mean()), 4),
    }
    # is the deficit explained by long final notes (melisma-like tail) or by item truncation?
    long_tail = last[last["gt_dur_sec"] >= last["gt_dur_sec"].median()]
    short_tail = last[last["gt_dur_sec"] < last["gt_dur_sec"].median()]
    out["by_gt_duration_of_last_char"] = {
        "longer_half": {"n": int(len(long_tail)),
                        "hit100": round(float(long_tail["hit100"].mean()), 4),
                        "mae_end": round(float(long_tail["end_err"].mean()), 4),
                        "signed_end_mean": round(float(long_tail["end_signed"].mean()), 4)},
        "shorter_half": {"n": int(len(short_tail)),
                         "hit100": round(float(short_tail["hit100"].mean()), 4),
                         "mae_end": round(float(short_tail["end_err"].mean()), 4),
                         "signed_end_mean": round(float(short_tail["end_signed"].mean()), 4)}}
    # how many last-char failures are shared across predictors (systematic vs random)?
    per_unit = df.pivot_table(index=["item_id", "character_index"], columns="predictor",
                             values="hit100", aggfunc="first")
    last_idx = last.set_index(["item_id", "character_index"]).index
    sel = per_unit.loc[per_unit.index.isin(last_idx)]
    if not sel.empty:
        ok_share = sel.mean(axis=1)
        out["last_char_failure_concordance"] = {
            "n_last_units": int(len(sel)),
            "share_all_predictors_fail": round(float((ok_share == 0).mean()), 4),
            "share_at_least_half_fail": round(float((ok_share <= 0.5).mean()), 4),
            "share_all_pass": round(float((ok_share == 1).mean()), 4)}
    return out


def analyse_unstable_units(df: pd.DataFrame, strong: list[str],
                           min_agree_ms: float = 20.0) -> dict[str, Any]:
    """Cross-predictor instability census: a deployable, GT-free candidate list.

    Units whose predicted boundary moves by more than ``min_agree_ms`` across strong predictors
    are the cheapest realign candidates: no ground truth is needed to find them, and the panel can
    already measure how well they actually predict error.
    """
    present = [x for x in strong if x in set(df["predictor"])]
    if len(present) < 2:
        return {"available": False, "reason": "need >=2 strong predictors"}
    wide = df[df["predictor"].isin(present)].pivot_table(
        index=["item_id", "character_index"], columns="predictor",
        values=["pred_start_sec", "pred_end_sec", "both_err", "hit100"], aggfunc="first")
    starts = wide["pred_start_sec"][present]
    ends = wide["pred_end_sec"][present]
    spread = np.maximum(starts.max(axis=1) - starts.min(axis=1),
                        ends.max(axis=1) - ends.min(axis=1)).to_numpy(dtype=float)
    err = wide["both_err"][present].mean(axis=1).to_numpy(dtype=float)
    hit = wide["hit100"][present].mean(axis=1).to_numpy(dtype=float)
    thresh = min_agree_ms / 1000.0
    unstable = spread > thresh
    out: dict[str, Any] = {
        "available": True, "predictors": present, "threshold_sec": thresh,
        "n_units": int(len(spread)),
        "unstable_share": round(float(unstable.mean()), 4),
        "unstable_n": int(unstable.sum()),
        "mean_error_unstable_sec": round(float(err[unstable].mean()), 4) if unstable.any() else None,
        "mean_error_stable_sec": round(float(err[~unstable].mean()), 4) if (~unstable).any() else None,
        "hit100_unstable": round(float(hit[unstable].mean()), 4) if unstable.any() else None,
        "hit100_stable": round(float(hit[~unstable].mean()), 4) if (~unstable).any() else None,
        "lift_overall_unstable": (round(float(hit[unstable].mean()), 4) if unstable.any() else None),
    }
    a = _auc((err > 0.1).astype(float), spread)
    b = _auc((err > 0.25).astype(float), spread)
    out["auc_spread_vs_bad100"] = None if a is None else round(a, 4)
    out["auc_spread_vs_bad250"] = None if b is None else round(b, 4)
    if unstable.any():
        out["recall_of_bad250_by_unstable"] = round(float(
            ((err > 0.25) & unstable).sum() / max((err > 0.25).sum(), 1)), 4)
        out["precision_of_unstable"] = round(float((err[unstable] > 0.25).mean()), 4)
    # where do unstable units sit?  (position + item)
    pos = wide.index.get_level_values(1).to_numpy(dtype=float)
    idx = pd.MultiIndex.from_tuples(list(wide.index))
    idx = idx.set_names(["item_id", "character_index"])
    frame = pd.DataFrame({"spread": spread, "err": err, "unstable": unstable}, index=idx)
    joined = frame.join(df[df["predictor"] == present[0]].set_index(
        ["item_id", "character_index"])[["frac_pos", "is_last_char", "is_first_char"]], how="left")
    if "frac_pos" in joined:
        b2 = pd.qcut(joined["frac_pos"].dropna(), 5, duplicates="drop")
        tab = joined.assign(bk=b2).groupby("bk", observed=True).agg(
            n=("unstable", "size"), unstable=("unstable", "mean"),
            err=("err", "mean")).reset_index()
        out["unstable_by_position"] = [{"bucket": str(r.bk), "n": int(r.n),
                                        "unstable_share": round(float(r.unstable), 4),
                                        "mean_err_sec": round(float(r.err), 4)}
                                       for r in tab.itertuples()]
        out["unstable_share_last_char"] = round(float(
            joined[joined["is_last_char"] == 1]["unstable"].mean()), 4)
        out["unstable_share_first_char"] = round(float(
            joined[joined["is_first_char"] == 1]["unstable"].mean()), 4)
        top = joined.sort_values("spread", ascending=False).head(10)
        out["top_10_unstable_units"] = [{"item": str(i[0]), "char_index": int(i[1]),
                                         "spread_sec": round(float(r.spread), 3),
                                         "mean_err_sec": round(float(r.err), 3)}
                                        for i, r in top.iterrows()]
    return out
