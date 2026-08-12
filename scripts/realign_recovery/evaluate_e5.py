"""E5 no-GT realign proposals: offline real-GT evaluation runner.

Offline GT evaluation of E5 proposals (per-episode original vs R-A/R-B/R-C vs
oracle best). All logic lives in
``src/lyricalign/realign_recovery/e5_eval.py``; GT is read here (and only
here) and never written back into REQUESTS/evidence.
"""
from __future__ import annotations

import argparse
import json
import sys

from lyricalign.realign_recovery.e5_eval import evaluate_e5_episodes


def _print_repair_table(summary: dict) -> None:
    per_method = summary.get("per_method", {})
    thresholds = summary.get("catastrophic_sec", [])
    print("\nper-method repair rate (E5 offline GT, err_s <= threshold):")
    header = f"{'method':<12}" + "".join(f"{'<=%gs' % t:>12}" for t in thresholds) + f"{'n_units':>10}"
    print(header)
    for method, m in per_method.items():
        rates = "".join(f"{m['repair_rate'][str(t)]:>12.4f}" for t in thresholds)
        print(f"{method:<12}{rates}{m['n_units']:>10}")
    print(f"\nlabeled episodes: {summary.get('labeled_episode_count')}, "
          f"unlabeled: {summary.get('unlabeled_episode_count')}")
    print(f"summary written to: {summary['out_path']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", required=True, help="E5 REQUESTS.jsonl")
    parser.add_argument("--evidence-dir", required=True, help="evidence dir (run_behavior_suite out/evidence)")
    parser.add_argument("--annotations", required=True, help="real GT annotations jsonl")
    parser.add_argument("--timeline-manifests", nargs="+", required=True,
                        help="LONG_TIMELINE_MANIFEST.jsonl (later files override same song)")
    parser.add_argument("--out", required=True, help="output summary JSON path")
    parser.add_argument("--catastrophic-sec", default="1,2,5,10",
                        help="comma-separated catastrophic thresholds (seconds)")
    args = parser.parse_args(argv)

    thresholds = tuple(float(x) for x in args.catastrophic_sec.split(",") if x.strip())
    summary = evaluate_e5_episodes(
        args.requests,
        args.evidence_dir,
        args.annotations,
        args.timeline_manifests,
        args.out,
        catastrophic_sec=thresholds,
    )
    summary["out_path"] = args.out
    print(json.dumps({
        "schema_version": summary["schema_version"],
        "episode_count": summary["episode_count"],
        "labeled_episode_count": summary["labeled_episode_count"],
        "unlabeled_episode_count": summary["unlabeled_episode_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
