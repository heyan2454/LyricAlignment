#!/usr/bin/env python3
"""Does the model's own confidence flag its failures?  AUC + abstention curves, two data sources.

The product needs to know whether a timeline can be trusted without listening to it.  Both artefacts
already carry what is needed, so this is pure re-reading:

* in-domain dumps (`measure_predicted_boundary_acoustics.py`): per-character `p_top1`,
  `entropy_nats`, `label_rank` against the *ground-truth* miss (`|Δ| > tolerance`);
* delivered real-song batch (`alignment.raw.json`): per-character `raw_start_entropy`,
  `raw_start_margin`, duration, etc. against the *structural* defect (zero-length interval),
  which is the failure users actually see.

Reported per source: rank-based AUC for each signal, and the abstention curve — how much of the
error is removed if the worst k% by confidence is dropped.  A signal with AUC ≈ 0.5 means the model
cannot tell us when it is wrong, which is itself an important negative result.

    PYTHONPATH=src python scripts/evaluation/confidence_abstention.py --source dump \
        --input results/by_run/20260914_long_mech_new12000/per_character.jsonl \
        --out results/by_run/20260914_confidence_abstention/dump.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any, Iterable

TOLERANCE_SEC = 0.2


def auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank-based AUC (Mann-Whitney), ties handled by mid-rank. Higher score => predicted positive."""
    pairs = list(zip(scores, labels))
    positives = [value for value, label in pairs if label]
    negatives = [value for value, label in pairs if not label]
    if not positives or not negatives:
        return None
    order = sorted(pairs, key=lambda item: item[0])
    ranks: dict[int, float] = {}
    index = 0
    while index < len(order):
        last = index
        while last + 1 < len(order) and order[last + 1][0] == order[index][0]:
            last += 1
        mid = (index + last) / 2.0 + 1
        for position in range(index, last + 1):
            ranks[position] = mid
        index = last + 1
    rank_sum = sum(ranks[position] for position, (_, label) in enumerate(order) if label)
    numerator = rank_sum - len(positives) * (len(positives) + 1) / 2.0
    return round(numerator / (len(positives) * len(negatives)), 4)


def abstention_curve(risk: list[float], bad: list[int], fractions: Iterable[float] = (0.01, 0.02, 0.05, 0.10, 0.20)) -> dict[str, Any]:
    """Drop the highest-risk `fraction` of units; report how much of the error that removes."""
    total_bad = sum(bad)
    if not total_bad:
        return {}
    order = sorted(range(len(risk)), key=lambda index: risk[index], reverse=True)
    out: dict[str, Any] = {}
    for fraction in fractions:
        cut = max(1, int(round(fraction * len(order))))
        caught = sum(bad[index] for index in order[:cut])
        out[f"drop_{int(fraction * 100)}pct"] = {
            "removed_units": cut,
            "removed_error_share": round(caught / total_bad, 4),
            "residual_rate": round((total_bad - caught) / (len(order) - cut), 4),
            "original_rate": round(total_bad / len(order), 4)}
    return out


def from_dump(path: Path, *, long_only: bool = False) -> dict[str, Any]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms" or row.get("entropy_nats") is None:
            continue
        if long_only and not row["long"]:
            continue
        rows.append(row)
    bad = [int(row["abs_err_argmax"] > TOLERANCE_SEC) for row in rows]
    signals = {
        "entropy_nats": [row["entropy_nats"] for row in rows],
        "neg_p_top1": [-row["p_top1"] for row in rows],
        "label_rank": [float(row["label_rank"]) for row in rows],
        "neg_top5_mass": [-row["top5_mass"] for row in rows],
        "duration": [row["duration"] for row in rows],
    }
    return {"units": len(rows), "error_rate": round(sum(bad) / len(rows), 4) if rows else None,
            "auc": {name: auc(values, bad) for name, values in signals.items()},
            "abstention": {name: abstention_curve(values, bad) for name, values in
                           (("entropy_nats", signals["entropy_nats"]), ("label_rank", signals["label_rank"]))},
            "by_duration": {label: _slice(rows, label) for label in ("short", "long")}}


def _slice(rows: list[dict[str, Any]], which: str) -> dict[str, Any]:
    keep = [row for row in rows if bool(row["long"]) == (which == "long")]
    if len(keep) < 20:
        return {"units": len(keep)}
    bad = [int(row["abs_err_argmax"] > TOLERANCE_SEC) for row in keep]
    return {"units": len(keep), "error_rate": round(sum(bad) / len(keep), 4),
            "auc_entropy": auc([row["entropy_nats"] for row in keep], bad),
            "auc_label_rank": auc([float(row["label_rank"]) for row in keep], bad)}


def gating_crossval(songs: list[list[dict[str, Any]]], *, score: str = "start_entropy",
                    fractions: Iterable[float] = (0.05, 0.10, 0.20)) -> dict[str, Any]:
    """Leave-one-song-out gating: the threshold is chosen on the other songs only.

    An in-sample abstention curve is optimistic because the cut-off sees the same data it scores.
    Here each song is held out once, the threshold is the (1-k) quantile of the *other* songs'
    scores, and the removed/residual error is accumulated over held-out songs only.
    """
    total_units = sum(len(song) for song in songs)
    total_bad = sum(row["zero"] for song in songs for row in song)
    out: dict[str, Any] = {"songs": len(songs), "units": total_units, "defects": total_bad,
                           "score": score, "out_of_sample": {}}
    if total_bad == 0 or len(songs) < 3:
        return out
    for fraction in fractions:
        caught = 0
        dropped = 0
        for held in range(len(songs)):
            others = [float(row[score]) for index, song in enumerate(songs) if index != held
                      for row in song if row.get(score) is not None]
            held_rows = [row for row in songs[held] if row.get(score) is not None]
            if len(others) < 50 or not held_rows:
                continue
            ordered = sorted(others)
            threshold = ordered[min(len(ordered) - 1, int(round((1 - fraction) * (len(ordered) - 1))))]
            for row in held_rows:
                if float(row[score]) >= threshold:          # 高熵 = 高风险
                    dropped += 1
                    caught += row["zero"]
        out["out_of_sample"][f"review_{int(fraction * 100)}pct"] = {
            "dropped_units": dropped,
            "removed_defect_share": round(caught / total_bad, 4),
            "residual_rate": round((total_bad - caught) / max(1, total_units - dropped), 4),
            "original_rate": round(total_bad / total_units, 4)}
    return out


def from_batch(path: Path) -> dict[str, Any]:
    """Real-song batch: predict the structural defect (zero-length) from the model's own signals."""
    rows: list[dict[str, Any]] = []
    for song_file in sorted(path.glob("*/alignments/r2/vocal/windowed/alignment.raw.json")):
        document = json.loads(song_file.read_text(encoding="utf-8"))
        for character in document.get("characters", []):
            start, end = character.get("raw_global_start_sec"), character.get("raw_global_end_sec")
            if start is None or end is None:
                continue
            rows.append({"zero": int(float(end) <= float(start)),
                         "start_entropy": character.get("raw_start_entropy"),
                         "end_entropy": character.get("raw_end_entropy"),
                         "start_margin": character.get("raw_start_margin"),
                         "end_margin": character.get("raw_end_margin"),
                         "duration": float(end) - float(start)})
    if not rows:
        return {"units": 0}
    bad = [row["zero"] for row in rows]
    def present(name: str) -> tuple[list[float], list[int]]:
        keep = [row for row in rows if row[name] is not None]
        return [float(row[name]) for row in keep], [row["zero"] for row in keep]
    out: dict[str, Any] = {"units": len(rows), "zero_rate": round(sum(bad) / len(rows), 4), "auc": {}, "abstention": {}}
    for name in ("start_entropy", "end_entropy", "start_margin", "end_margin"):
        scores, labels = present(name)
        if len(scores) < 20:
            continue
        # 低 margin / 高熵 = 更可能塌
        out["auc"][name] = auc(scores, labels)
        out["auc"][f"neg_{name}"] = auc([-value for value in scores], labels)
    scores, labels = present("start_entropy")
    out["abstention"]["start_entropy"] = abstention_curve(scores, labels)
    per_song: list[list[dict[str, Any]]] = []
    for song_file in sorted(path.glob("*/alignments/r2/vocal/windowed/alignment.raw.json")):
        document = json.loads(song_file.read_text(encoding="utf-8"))
        rows = [{"zero": int(float(character["raw_global_end_sec"]) <= float(character["raw_global_start_sec"])),
                 "start_entropy": character.get("raw_start_entropy"),
                 "end_entropy": character.get("raw_end_entropy"),
                 "neg_start_margin": (-character["raw_start_margin"]
                                      if character.get("raw_start_margin") is not None else None)}
                for character in document.get("characters", [])
                if character.get("raw_global_start_sec") is not None
                and character.get("raw_global_end_sec") is not None]
        if len(rows) >= 20:
            per_song.append(rows)
    out["gating_crossval"] = {name: gating_crossval(per_song, score=name)
                              for name in ("start_entropy", "end_entropy", "neg_start_margin")}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("dump", "batch"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = from_dump(args.input) if args.source == "dump" else from_batch(args.input)
    payload["source"] = args.source
    payload["input"] = str(args.input)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False)[:2400])


if __name__ == "__main__":
    main()
