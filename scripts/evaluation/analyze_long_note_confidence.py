#!/usr/bin/env python3
"""Are long-note mistakes 'no idea' or 'confidently wrong'?  Splits the two by duration bucket.

Consumes the per-character dumps that carry the slot diagnostics (`p_top1`, `entropy_nats`,
`label_rank`, `top5_mass`).  The distinction decides the intervention:

* diffuse (low p_top1 / high entropy, label inside the top few)   -> decoding and context problem;
* confidently wrong (high p_top1, label ranked deep)              -> representation / training-signal
  problem, which is what duration-aware sampling is meant to attack.

    PYTHONPATH=src python scripts/evaluation/analyze_long_note_confidence.py \
        --dump new12000=results/by_run/20260914_long_mech_new12000/per_character.jsonl \
        --out results/by_run/20260914_long_note_confidence/metrics.json
"""
from __future__ import annotations
import argparse, json, statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

BUCKETS = ((0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 99.0))
TOL = 0.2


def bucket_of(duration: float) -> str:
    for low, high in BUCKETS:
        if low <= duration < high:
            return f"{low:g}-{high if high < 99 else '+'}s"
    return "2-+s"


def rows(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") == "d_rms" and row.get("entropy_nats") is not None:
            out.append(row)
    return out


def profile(data: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in data:
        groups[(bucket_of(row["duration"]), "miss" if row["abs_err_argmax"] > TOL else "hit")].append(row)
    out: dict[str, Any] = {}
    for (bucket, outcome), group in sorted(groups.items()):
        n = len(group)
        out.setdefault(bucket, {})[outcome] = {
            "n": n,
            "median_p_top1": round(st.median(r["p_top1"] for r in group), 3),
            "median_entropy_nats": round(st.median(r["entropy_nats"] for r in group), 3),
            "share_label_is_top1": round(sum(1 for r in group if r["label_rank"] == 1) / n, 3),
            "share_label_rank_gt2": round(sum(1 for r in group if r["label_rank"] > 2) / n, 3),
            "share_label_rank_gt10": round(sum(1 for r in group if r["label_rank"] > 10) / n, 3),
            "median_top5_mass": round(st.median(r["top5_mass"] for r in group), 3),
            "median_signed_err_ms": round(1000 * st.median(r["signed_err"] for r in group), 1),
            "confidently_wrong_share": round(sum(1 for r in group if r["p_top1"] > 0.5 and r["label_rank"] > 2) / n, 3),
            "diffuse_share": round(sum(1 for r in group if r["p_top1"] <= 0.25) / n, 3)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="append", default=[], help="label=path (per_character.jsonl)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    payload: dict[str, Any] = {"schema_version": "long_note_confidence_v1", "tolerance_sec": TOL,
                               "checkpoints": {}}
    for spec in args.dump:
        label, path = spec.split("=", 1)
        data = rows(Path(path))
        payload["checkpoints"][label] = {"rows": len(data), "by_bucket": profile(data)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for label, block in payload["checkpoints"].items():
        print(f"\n=== {label}（{block['rows']} 次测量）===")
        print(f"{'时长':>8} {'结果':>5} {'n':>5} {'p_top1':>7} {'熵':>6} {'标注=第1':>8} {'标注>2':>7} "
              f"{'标注>10':>8} {'自信地错':>9} {'弥散':>6} {'带符号误差':>10}")
        for bucket, outcomes in block["by_bucket"].items():
            for outcome in ("hit", "miss"):
                stats = outcomes.get(outcome)
                if not stats:
                    continue
                print(f"{bucket:>8} {outcome:>5} {stats['n']:5d} {stats['median_p_top1']:7.3f} "
                      f"{stats['median_entropy_nats']:6.2f} {stats['share_label_is_top1']:8.3f} "
                      f"{stats['share_label_rank_gt2']:7.3f} {stats['share_label_rank_gt10']:8.3f} "
                      f"{stats['confidently_wrong_share']:9.3f} {stats['diffuse_share']:6.3f} "
                      f"{stats['median_signed_err_ms']:10.0f}")


if __name__ == "__main__":
    main()
