#!/usr/bin/env python3
"""WP9 — E7 serial accumulated-error stress (smoke, CPU).

Constructs/runs serial episodes: window 0 commits a small cursor error, each
later window's query inherits the poisoned cursor unless its recovery strategy
resets/converges it, and we measure downstream error propagation over the whole
chain.  `--smoke` runs a deterministic CPU simulator (no GT, no writes).

Input ``--episodes``: JSONL of serial episode dicts, each::

    {
      "episode_id": str,
      "windows": [
         {"window_id":0, "units":[{"canonical_unit_id":1,"start_sec":0.0,"end_sec":0.4},...],
          "target_unit_ids":[1], "injected_cursor_error_ms":150,
          "recovery_strategy":"none", "is_safe":false},
         ...
      ]
    }

`create_smoke_episodes` emits a small deterministic bundle covering the three
required verdicts:
  - an unmitigated chain (error persists) -> long windows-to-recover;
  - a chain with a reset on a later window -> recovery, few bad windows;
  - a chain with a malicious error on an originally-safe window -> false recovery.

Outputs (under <out-root>):
   01_episodes/SERIAL_EPISODES.jsonl   serial_episode_trace_v1 rows (one per episode)
   02_metrics/SERIAL_METRICS.json      serial_episode_metrics_v1 rows + aggregate

Usage:
  PYTHONPATH=src python scripts/unit_realign/run_serial_stress.py \
      --episodes <SERIAL_EPISODES_IN.jsonl> --out-root <run> [--smoke]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.recovery_atlas import (  # noqa: E402
    build_serial_episode,
)

_EPISODES_OUT = Path("01_episodes") / "SERIAL_EPISODES.jsonl"
_METRICS_OUT = Path("02_metrics") / "SERIAL_METRICS.json"


def create_smoke_episodes() -> list[dict]:
    """Small deterministic CPU episode bundle for smoke validation."""
    def w(wid: int, err: float, strategy: str, safe: bool = False, n: int = 4, start: float = 0.0) -> dict:
        return {
            "window_id": wid,
            "units": [{"canonical_unit_id": i, "start_sec": start + i * 0.5, "end_sec": start + i * 0.5 + 0.4}
                      for i in range(1, n + 1)],
            "target_unit_ids": [1],
            "injected_cursor_error_ms": err,
            "recovery_strategy": strategy,
            "is_safe": safe,
        }

    base = [
        # (1) unmitigated: error at win0 keeps contaminating windows 1-4.
        {"episode_id": "smoke_unmitigated",
         "windows": [w(0, 150, "none")] + [w(i, 0, "none") for i in range(1, 5)]},
        # (2) reset at window 2 recovers the chain.
        {"episode_id": "smoke_reset_recovers",
         "windows": [w(0, 180, "none"), w(1, 0, "none"), w(2, 0, "reset"),
                     w(3, 0, "none"), w(4, 0, "iterative")]},
        # (3) error lands on an originally-safe window -> false recovery probe.
        {"episode_id": "smoke_false_recovery",
         "windows": [w(0, 0, "none", safe=True), w(1, 250, "none", safe=True),
                     w(2, 0, "reset"), w(3, 0, "none", safe=True)]},
    ]
    return base


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _write_jsonl(path: Path, rows) -> None:
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    _atomic_write(path, payload)


def _write_json(path: Path, value) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--episodes", default=None,
                   help="SERIAL_EPISODES_IN.jsonl; if omitted and --smoke, "
                        "create_smoke_episodes() is used")
    p.add_argument("--out-root", required=True)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.out_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "01_episodes").mkdir(parents=True, exist_ok=True)
    (root / "02_metrics").mkdir(parents=True, exist_ok=True)

    if args.episodes:
        episodes = _read_jsonl(Path(args.episodes))
    elif args.smoke:
        episodes = create_smoke_episodes()
    else:
        p.error("--episodes is required unless --smoke (which builds a synthetic bundle)")

    traces = []
    metrics = []
    for ep in episodes:
        run = build_serial_episode(ep)
        traces.append(run)
        metrics.append(run["summary"])

    if metrics:
        aggregated = {
            "schema": "serial_episode_metrics_aggregate_v1",
            "n_episodes": len(metrics),
            "mean_windows_to_recover": round(sum(
                1.0 if m["windows_to_recover"] is None else float(m["windows_to_recover"])
                for m in metrics) / len(metrics), 4),
            "max_cumulative_bad_windows": max(int(m["cumulative_bad_windows"]) for m in metrics),
            "total_extra_forwards": sum(int(m["extra_forwards"]) for m in metrics),
            "episodes_with_false_recovery": sum(1 for m in metrics if m["false_recovery_on_safe_windows"]),
        }
    else:
        aggregated = {"schema": "serial_episode_metrics_aggregate_v1", "n_episodes": 0}

    _write_jsonl(root / _EPISODES_OUT, traces)
    _write_json(root / _METRICS_OUT, {"schema": "serial_episode_metrics_v1",
                                      "episodes": metrics,
                                      "aggregate": aggregated,
                                      "executor": "smoke" if args.smoke else "provided"})

    print(json.dumps({"n_episodes": len(metrics),
                      "aggregate": aggregated,
                      "episodes": str(root / _EPISODES_OUT),
                      "metrics": str(root / _METRICS_OUT)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
