#!/usr/bin/env python3
"""Summarize the B-group mechanism runs (R-U / R-S / R-CF) into a JSON table
plus a comparison figure, from each family's FINAL_TRAJECTORY.json aggregates.

Outputs (under <out>):
  BGROUP_SUMMARY.json   per-family + per-song metric table (canonical numbers)
  BGROUP_SUMMARY.png    per-family bar comparison figure
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FAMILIES = ["R-U", "R-S", "R-CF"]

KEYS = [
    ("ok_ratio", "ok ratio"),
    ("nc_ratio", "not constructible"),
    ("collateral_ratio", "collateral harm"),
    ("monotonic_ratio", "monotonic improve"),
    ("improve_then_regress_ratio", "improve→regress"),
    ("oscillation_ratio", "oscillation/divergence"),
    ("catastrophic_ratio", "catastrophic regression"),
    ("recovered_ratio", "all targets recovered"),
]


def _ratio(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def _region_of(identity: str) -> str:
    # stub identity seed: "<song>:<region>:iter<it>:<reason>" (region may contain ':')
    if not identity:
        return ""
    parts = identity.split(":")
    if len(parts) < 3:
        return identity
    return ":".join(parts[:-2])


def summarize_aggregates(aggs: list[dict], input_regions: int,
                         nc_region_keys: set) -> dict:
    n = len(aggs)
    nc_regions = len(nc_region_keys)
    num = lambda key: sum(1 for a in aggs if a.get(key))
    s = {
        "n_regions_input": input_regions,
        "n_regions_with_aggregate": n,
        "n_region_not_constructible": nc_regions,
        "ok_ratio": _ratio(n, input_regions),
        "nc_ratio": _ratio(nc_regions, input_regions),
        "collateral_ratio": _ratio(num("collateral_harm"), n),
        "monotonic_ratio": _ratio(num("monotonic_improvement"), n),
        "improve_then_regress_ratio": _ratio(num("improve_then_regress"), n),
        "oscillation_ratio": _ratio(num("oscillation_or_divergence"), n),
        "catastrophic_ratio": _ratio(num("catastrophic_regression"), n),
        "recovered_ratio": _ratio(num("all_target_recovered"), n),
    }
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", required=True, help="root containing bgroup_R-U, bgroup_R-S, bgroup_R-CF")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    root = Path(args.run_root)
    summary = {"schema": "bgroup_summary_v1", "families": {}}
    per_song = {}
    for fam in FAMILIES:
        final = root / f"bgroup_{fam}" / "FINAL_TRAJECTORY.json"
        if not final.is_file():
            print(f"WARN: {final} missing", flush=True)
            continue
        s = json.loads(final.read_text(encoding="utf-8"))
        aggs = [a for a in (s.get("aggregates") or []) if a.get("row_kind") == "region"]
        # input regions = sum of per-batch FINAL n_regions (batches are the real
        # input units); stub identities from REQUESTS for region-level nc
        input_regions = 0
        for b in range(1, 19):
            bf = root / f"bgroup_{fam}_b{b}" / "FINAL_TRAJECTORY.json"
            if bf.is_file():
                input_regions += int(json.loads(bf.read_text(encoding="utf-8")).get("n_regions", 0))
        # region-level not-constructible: match RUN_STATE nc identities against
        # REQUESTS rows (nc requests carry song_id/region_id; identities are hashes)
        nc_ids = set()
        st_path = root / f"bgroup_{fam}" / "06_runtime" / "RUN_STATE.json"
        if st_path.is_file():
            nc_ids = set(json.loads(st_path.read_text(encoding="utf-8"))
                         .get("not_constructible_identities", []))
        req_rows = []
        reqs = root / f"bgroup_{fam}" / "01_requests" / "REQUESTS.jsonl"
        if reqs.is_file():
            req_rows = [json.loads(l) for l in reqs.read_text(encoding="utf-8").splitlines() if l.strip()]
        nc_region_keys = {(r.get("song_id"), r.get("region_id")) for r in req_rows
                          if r.get("request_identity") in nc_ids}
        nc_stub_identities = [r.get("request_identity") for r in req_rows
                              if r.get("row_kind") == "not_constructible_stub"]
        nc_region_keys |= {(_region_of(i).split(":")[0], ":".join(_region_of(i).split(":")[1:]))
                           for i in nc_stub_identities if i}
        summary["families"][fam] = {
            "n_regions_input": s.get("n_regions"),
            "ok": s.get("ok"), "not_constructible": s.get("not_constructible"),
            "failed": s.get("failed"),
            "metrics": summarize_aggregates(aggs, input_regions, list(nc_region_keys)),
        }
        for a in aggs:
            song = str(a.get("song_id") or "?")
            ps = per_song.setdefault(song, {})
            m = ps.setdefault(fam, {"n": 0, "collateral": 0, "monotonic": 0,
                                    "oscillation": 0, "catastrophic": 0, "recovered": 0,
                                    "improve_then_regress": 0})
            m["n"] += 1
            m["collateral"] += 1 if a.get("collateral_harm") else 0
            m["monotonic"] += 1 if a.get("monotonic_improvement") else 0
            m["oscillation"] += 1 if a.get("oscillation_or_divergence") else 0
            m["catastrophic"] += 1 if a.get("catastrophic_regression") else 0
            m["recovered"] += 1 if a.get("all_target_recovered") else 0
            m["improve_then_regress"] += 1 if a.get("improve_then_regress") else 0
    summary["per_song"] = per_song

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "BGROUP_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # figure: per-family bar comparison of ratio metrics
    fams = list(summary["families"].keys())
    if not fams:
        print("no families found", flush=True)
        return 1
    labels = [m[1] for m in KEYS[1:]]
    x = range(len(labels))
    width = 0.8 / max(len(fams), 1)
    fig, ax = plt.subplots(figsize=(12, 6))
    for i, fam in enumerate(fams):
        m = summary["families"][fam]["metrics"]
        vals = [m[k] for k, _ in KEYS[1:]]
        ax.bar([xi + i * width for xi in x], vals, width, label=fam)
    ax.set_xticks([xi + width * (len(fams) - 1) / 2 for xi in x])
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_ylabel("ratio")
    ax.set_title("B-group mechanism families — region-level ratios")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(args.out / "BGROUP_SUMMARY.png", dpi=150)
    print(json.dumps({"out": str(args.out / "BGROUP_SUMMARY.json"),
                      "families": fams,
                      "figure": str(args.out / "BGROUP_SUMMARY.png")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
