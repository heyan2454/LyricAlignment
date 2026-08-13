"""P4 Overnight Expansion acceptance + P11 statistics/fairness audit.

Consumes only structured run artifacts:
  - REGION_OUTCOMES.jsonl / UNIT_OUTCOMES.jsonl (evaluator output)
  - EXHAUSTION_AUDIT.json (sampling song-diversity audit)
  - REQUESTS.jsonl (request fairness identity check)

Emits P4_ACCEPTANCE.json and P11_SONG_STATS.json under <run-root>/05_analysis/.
Unit-level semantics reuse src/lyricalign/unit_realign/unit_outcome.classify_unit_outcome
(material_ms=200). This script never recomputes alignments or GT pairing.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.unit_outcome import classify_unit_outcome

MATERIAL_MS = 200.0
BOOTSTRAP_N = 1000
BOOTSTRAP_SEED = 20260813
CLASSES = ("repair", "harm", "unchanged")
P4_REQUIREMENTS = {
    "main_cohort_min_valid_regions": 200,
    "family_min_valid_regions": 30,
    "stratum_min_valid_regions": 20,
    "song_min_regions": 8,
}


def load_jsonl(path: Path) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def unit_label(row: dict) -> str:
    cls = classify_unit_outcome(row, material_ms=MATERIAL_MS)
    if cls in {"improved_finite", "missing_to_covered"}:
        return "repair"
    if cls in {"degraded_finite", "covered_to_missing", "extra", "invalid"}:
        return "harm"
    return "unchanged"


def ci(values: list[float], lo: float = 2.5, hi: float = 97.5) -> tuple[float, float]:
    s = sorted(values)
    n = len(s)
    return s[int(n * lo / 100)], s[int(n * hi / 100)]


def bootstrap_song_ci(units: list[dict], seed: int = BOOTSTRAP_SEED) -> dict:
    by_song: dict[str, list[str]] = defaultdict(list)
    for u in units:
        by_song[u["song_id"]].append(unit_label(u))
    songs = sorted(by_song)
    rng = random.Random(seed)
    means = {c: [] for c in CLASSES}
    for _ in range(BOOTSTRAP_N):
        pooled: list[str] = []
        for _ in range(len(songs)):
            pooled.extend(by_song[rng.choice(songs)])
        if not pooled:
            continue
        counts = Counter(pooled)
        for c in CLASSES:
            means[c].append(counts.get(c, 0) / len(pooled))
    out: dict[str, dict] = {}
    for c in CLASSES:
        m = sum(means[c]) / len(means[c])
        lo, hi = ci(means[c])
        out[c] = {"mean": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)], "n_bootstrap": len(means[c])}
    return {"seed": seed, "n_bootstrap": BOOTSTRAP_N, "material_ms": MATERIAL_MS,
            "n_songs": len(songs), "n_units": len(units), "by_outcome": out}


def leave_one_song_out(units: list[dict]) -> dict:
    by_song: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        by_song[u["song_id"]].append(u)
    global_labels = Counter(unit_label(u) for u in units)
    overall = {c: global_labels.get(c, 0) / len(units) for c in CLASSES}

    def rates(rows: list[dict]) -> dict:
        c = Counter(unit_label(u) for u in rows)
        n = len(rows) or 1
        return {k: round(c.get(k, 0) / n, 4) for k in CLASSES}

    loo: dict[str, dict] = {}
    per_song: dict[str, dict] = {}
    for song, rows in by_song.items():
        held = [u for s, rs in by_song.items() if s != song for u in rs]
        loo[song] = {"held_out_song_rate": rates(rows),
                     "exclude_song_rate": rates(held),
                     "delta_repair_vs_overall": round(rates(held)["repair"] - overall["repair"], 4),
                     "delta_harm_vs_overall": round(rates(held)["harm"] - overall["harm"], 4)}
        per_song[song] = rates(rows)
    return {"overall": {k: round(v, 4) for k, v in overall.items()}, "leave_one_out": loo, "per_song": per_song}


def request_fairness(run_root: Path, evaluated_ids: set[str]) -> dict:
    reqs = load_jsonl(run_root / "01_requests" / "REQUESTS.jsonl")
    evaluated = [r for r in reqs if r.get("request_id") in evaluated_ids]
    keys = ("model_identity", "checkpoint_identity", "decoder_identity", "mapping_schema",
            "index_space", "family_version", "baseline_digest", "evaluation_only")
    summary: dict = {"n_evaluated_matched": len(evaluated),
                     "n_requests_total": len(reqs), "n_non_null_requests": sum(1 for r in reqs if r.get("status") is None)}
    ok = True
    for k in keys:
        vals = sorted(set(str(r.get(k)) for r in evaluated))
        summary[k] = {"unique_values": vals, "n_unique": len(vals)}
        if len(vals) > 1:
            ok = False
    audio = sorted(set(str(r.get("audio_sha256")) for r in evaluated))
    summary["audio_sha256"] = {"n_unique_by_song_expected": len(audio),
                               "note": "multiple audio hashes are expected (one per song)"}
    gt_pairing = sorted(set(str(x.get("evaluation_only")) for x in evaluated))
    summary["gt_pairing_evaluation_only"] = gt_pairing
    summary["single_model_checkpoint_gt_pass"] = ok
    return summary


def p4_acceptance(run_root: Path) -> dict:
    regions = load_jsonl(run_root / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")
    audit = json.load(open(run_root / "00_population" / "EXHAUSTION_AUDIT.json"))
    family_counts = Counter(r["family"] for r in regions)
    stratum_counts = Counter(r["stratum"] for r in regions)
    song_counts = Counter(r["song_id"] for r in regions)

    n_total = len(regions)
    top3 = sum(c for _, c in song_counts.most_common(3))
    top3_share = top3 / n_total
    top1_share = song_counts.most_common(1)[0][1] / n_total

    checks = {
        "main_cohort_total_valid": {"requirement": P4_REQUIREMENTS["main_cohort_min_valid_regions"],
                                    "value": n_total, "pass": n_total >= P4_REQUIREMENTS["main_cohort_min_valid_regions"]},
        "per_family_min_30": {f: {"value": c, "pass": c >= P4_REQUIREMENTS["family_min_valid_regions"]}
                              for f, c in sorted(family_counts.items())},
        "per_stratum_min_20": {s: {"value": c, "pass": c >= P4_REQUIREMENTS["stratum_min_valid_regions"]}
                               for s, c in sorted(stratum_counts.items())},
        "per_song_min_8": {s: {"value": c, "pass": c >= P4_REQUIREMENTS["song_min_regions"]}
                           for s, c in sorted(song_counts.items())},
        "song_diversity": {
            "n_songs_in_cohort": len(song_counts),
            "max_song_share": round(top1_share, 4),
            "top3_song_share": round(top3_share, 4),
            "pass_no_2_3_song_dominance": top3_share < 0.5,
            "note": "P4 forbids most of 200 regions coming from 2-3 songs; top-3 share must stay <50%",
        },
    }
    checks["exhaustion_audit"] = {
        "requested": audit.get("requested"), "selected": audit.get("selected"),
        "per_song_cap": audit.get("per_song_cap"), "status": audit.get("status"),
        "n_songs_in_audit": len(audit.get("selected_per_song", {})),
        "pass": audit.get("status") == "complete" and len(audit.get("selected_per_song", {})) >= 8,
    }

    units = load_jsonl(run_root / "03_unit_outcomes" / "UNIT_OUTCOMES.jsonl")
    labels = Counter(unit_label(u) for u in units)
    n = len(units)
    unit_dist = {
        "n_units": n,
        "repair_rate": round(labels["repair"] / n, 4),
        "harm_rate": round(labels["harm"] / n, 4),
        "unchanged_rate": round(labels["unchanged"] / n, 4),
        "n_repair": labels["repair"], "n_harm": labels["harm"], "n_unchanged": labels["unchanged"],
        "material_ms": MATERIAL_MS,
    }
    checks["unit_outcome_distribution"] = unit_dist

    accepted = all(c["pass"] if isinstance(c, dict) and "pass" in c else True
                   for c in checks.values() if isinstance(c, dict))
    family_ok = all(v["pass"] for v in checks["per_family_min_30"].values())
    stratum_ok = all(v["pass"] for v in checks["per_stratum_min_20"].values())
    song_ok = all(v["pass"] for v in checks["per_song_min_8"].values())
    overall = {
        "main_cohort_pass": checks["main_cohort_total_valid"]["pass"],
        "family_pass": family_ok, "stratum_pass": stratum_ok, "song_pass": song_ok,
        "diversity_pass": checks["song_diversity"]["pass_no_2_3_song_dominance"]
        and checks["exhaustion_audit"]["pass"],
        "overall_pass": checks["main_cohort_total_valid"]["pass"] and family_ok and stratum_ok
        and song_ok and checks["song_diversity"]["pass_no_2_3_song_dominance"]
        and checks["exhaustion_audit"]["pass"],
    }
    return {"schema": "unit_realign_p4_acceptance_v1", "n_regions": n_total,
            "requirements": P4_REQUIREMENTS, "checks": checks, "accepted": overall}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root", default="/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify")
    ap.add_argument("--out-root", default=None)
    args = ap.parse_args()
    run_root = Path(args.run_root)
    out_dir = Path(args.out_root) if args.out_root else run_root / "05_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    p4 = p4_acceptance(run_root)
    units = load_jsonl(run_root / "03_unit_outcomes" / "UNIT_OUTCOMES.jsonl")
    p11 = {
        "schema": "unit_realign_p11_song_stats_v1",
        "bootstrap": bootstrap_song_ci(units),
        "leave_one_song_out": leave_one_song_out(units),
    }
    regions = load_jsonl(run_root / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")
    evaluated_ids = {r["request_id"] for r in regions}
    p11["request_fairness"] = request_fairness(run_root, evaluated_ids)

    (out_dir / "P4_ACCEPTANCE.json").write_text(json.dumps(p4, indent=2, ensure_ascii=False))
    (out_dir / "P11_SONG_STATS.json").write_text(json.dumps(p11, indent=2, ensure_ascii=False))
    print(json.dumps({"p4_overall": p4["accepted"], "p11_bootstrap": p11["bootstrap"],
                      "fairness_pass": p11["request_fairness"]["single_model_checkpoint_gt_pass"],
                      "out": str(out_dir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
