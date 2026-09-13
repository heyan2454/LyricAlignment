#!/usr/bin/env python3
"""Post-hoc affine calibration of (centre, duration): does the diagnosed bias actually explain the error?

Two measured facts about the failing subset of long characters — the interval is compressed
(duration ratio 0.709) and shifted early (centre −328 ms) — make a testable prediction: a monotone
correction applied to the predicted interval, fitted on *other* songs, should remove part of the
error.  If it does, the "duration regression to the common value" story is quantitatively right and
there is a free inference-time gain; if it does not, the bias description was decorative and only
training can help.

Nothing is fitted on the song it is evaluated on: the 29 validation songs are held out one at a time,
the correction is a piecewise-linear map over duration knots learned from the remaining songs.

    PYTHONPATH=src python scripts/evaluation/duration_calibration_test.py \
        --dump results/by_run/20260914_long_mech_new12000/per_character.jsonl \
        --out results/by_run/20260914_duration_calibration/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
KNOTS = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0)


def characters(path: Path) -> list[dict[str, Any]]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    songs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
        # item_id is Singer#Song#NNNN — group by singer+song so the hold-out is per song,
        # matching every other macro-over-songs metric in this project
        parts = str(row["item_id"]).split("#")
        songs[row["item_id"]] = "#".join(parts[:2]) if len(parts) >= 2 else str(row["item_id"])
    out: list[dict[str, Any]] = []
    for (item, index), kinds in per.items():
        if len(kinds) != 2:
            continue
        onset, offset = kinds["onset"], kinds["offset"]
        gt_onset = float(onset["pred_sec"]) - float(onset["signed_err"])
        gt_offset = float(offset["pred_sec"]) - float(offset["signed_err"])
        pred_onset, pred_offset = float(onset["pred_sec"]), float(offset["pred_sec"])
        out.append({"key": f"{item}|{index}", "song": songs[item],
                    "pred_entropy": float(onset["entropy_nats"]) + float(offset["entropy_nats"]),
                    "pred_p_top1": min(float(onset.get("p_top1") or 1.0), float(offset.get("p_top1") or 1.0)),
                    "pred_centre": (pred_onset + pred_offset) / 2.0, "pred_dur": pred_offset - pred_onset,
                    "gt_centre": (gt_onset + gt_offset) / 2.0, "gt_dur": gt_offset - gt_onset,
                    "gt_dur_label": float(onset["duration"]),
                    "raw_max_err": max(abs(pred_onset - gt_onset), abs(pred_offset - gt_offset))})
    return [row for row in out if row["gt_dur"] > 0 and row["pred_dur"] > 0]


def fit_map_conditional(rows: list[dict[str, Any]], *, target: str) -> dict[tuple[int, int], tuple[float, float]]:
    """Duration correction conditioned on the model's own entropy.

    The unconditional map above fails because the diagnosed compression is conditional on the
    character being *wrong*: fitting it on the whole population moves the 90% that are already
    correct.  Entropy is observable at inference, so this conditions the correction on
    (predicted-duration bin, entropy bin) — the honest version of the same idea.
    """
    table: dict[tuple[int, int], tuple[float, float]] = {}
    by_cell: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cell[(duration_bin(row["pred_dur"]), entropy_bin(row.get("pred_entropy")))].append(row)
    for cell, group in by_cell.items():
        if len(group) < 30:
            continue
        table[cell] = (st.median([row["gt_dur"] for row in group]) /
                       max(1e-6, st.median([row["pred_dur"] for row in group])),
                       st.median([row["gt_centre"] - row["pred_centre"] for row in group]))
    return table


def duration_bin(value: float) -> int:
    for index, high in enumerate((0.25, 0.5, 1.0, 2.0, 4.0)):
        if value < high:
            return index
    return 5


def entropy_bin(value: Any) -> int:
    if value is None:
        return -1
    for index, high in enumerate((0.5, 1.0, 2.0, 3.0)):
        if value < high:
            return index
    return 5


def fit_map(rows: list[dict[str, Any]], *, target: str) -> tuple[list[float], list[float]]:
    """Piecewise-linear map from predicted duration to the average ground-truth value in that bin."""
    xs: list[float] = []
    ys: list[float] = []
    for low, high in zip(KNOTS[:-1], KNOTS[1:]):
        bucket = [row for row in rows if low <= row["pred_dur"] < high]
        if len(bucket) < 20:
            continue
        xs.append(st.median([row["pred_dur"] for row in bucket]))
        ys.append(st.median([row["gt_dur"] if target == "duration" else row["gt_centre"] - row["pred_centre"]
                             for row in bucket]))
    if len(xs) < 2:
        return [], []
    order = sorted(range(len(xs)), key=lambda index: xs[index])
    return [xs[index] for index in order], [ys[index] for index in order]


def interp(x: float, xs: list[float], ys: list[float]) -> float:
    if not xs:
        return 0.0
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for index in range(len(xs) - 1):
        if xs[index] <= x <= xs[index + 1]:
            span = xs[index + 1] - xs[index]
            ratio = 0.0 if span <= 0 else (x - xs[index]) / span
            return ys[index] + ratio * (ys[index + 1] - ys[index])
    return ys[-1]


def bucket_of(duration: float) -> str:
    if duration < 0.5:
        return "0-0.5s"
    if duration < 1.0:
        return "0.5-1s"
    if duration < 2.0:
        return "1-2s"
    return "2s+"


def evaluate(rows: list[dict[str, Any]], *, min_fit_rows: int = 60) -> dict[str, Any]:
    songs = sorted({row["song"] for row in rows})
    if len(songs) < 3:
        return {"status": "insufficient_songs", "songs": len(songs)}
    corrected: dict[str, list[float]] = defaultdict(list)
    raw: dict[str, list[float]] = defaultdict(list)
    cond: dict[str, list[float]] = defaultdict(list)
    corrections_used = 0
    for held in songs:
        train = [row for row in rows if row["song"] != held]
        test = [row for row in rows if row["song"] == held]
        if len(train) < min_fit_rows or not test:
            continue
        duration_map = fit_map(train, target="duration")
        centre_map = fit_map(train, target="centre")
        table = fit_map_conditional(train, target="duration")
        if len(duration_map[0]) < 2:
            continue
        corrections_used += 1
        for row in test:
            raw[bucket_of(row["gt_dur_label"])].append(row["raw_max_err"])
            raw["all"].append(row["raw_max_err"])
            new_dur = interp(row["pred_dur"], *duration_map)
            # the centre correction is a duration-conditioned bias, so keep the centre where the
            # duration map says nothing rather than inventing a shift
            bias = interp(row["pred_dur"], *centre_map) if len(centre_map[0]) >= 2 else 0.0
            new_centre = row["pred_centre"] + bias
            corrected_error = max(abs(new_centre - new_dur / 2.0 - row["gt_centre"] + row["gt_dur"] / 2.0),
                                  abs(new_centre + new_dur / 2.0 - row["gt_centre"] - row["gt_dur"] / 2.0))
            corrected[bucket_of(row["gt_dur_label"])].append(corrected_error)
            corrected["all"].append(corrected_error)
            cell = (duration_bin(row["pred_dur"]), entropy_bin(row.get("pred_entropy")))
            factor, bias_c = table.get(cell, (1.0, 0.0))
            dur_c = row["pred_dur"] * factor
            centre_c = row["pred_centre"] + bias_c
            cond_error = max(abs(centre_c - dur_c / 2.0 - (row["gt_centre"] - row["gt_dur"] / 2.0)),
                             abs(centre_c + dur_c / 2.0 - (row["gt_centre"] + row["gt_dur"] / 2.0)))
            cond[bucket_of(row["gt_dur_label"])].append(cond_error)
            cond["all"].append(cond_error)
    out: dict[str, Any] = {"status": "measured", "songs": len(songs), "songs_held_out": corrections_used,
                           "characters": len(rows), "buckets": {}}
    for name in ("all", "0-0.5s", "0.5-1s", "1-2s", "2s+"):
        raw_values, corrected_values = raw.get(name, []), corrected.get(name, [])
        if len(raw_values) < 20:
            continue
        out["buckets"][name] = {
            "characters": len(raw_values),
            "miss_rate_raw": round(sum(1 for value in raw_values if value > TOL) / len(raw_values), 4),
            "miss_rate_corrected": round(sum(1 for value in corrected_values if value > TOL) / len(corrected_values), 4),
            "median_err_raw_ms": round(1000 * st.median(raw_values), 1),
            "median_err_corrected_ms": round(1000 * st.median(corrected_values), 1),
            "mean_delta_ms": round(1000 * st.mean(c - r for c, r in zip(corrected_values, raw_values)), 2)}
        cond_values = cond.get(name, [])
        if len(cond_values) == len(raw_values):
            out["buckets"][name]["miss_rate_conditional"] = round(
                sum(1 for value in cond_values if value > TOL) / len(cond_values), 4)
            out["buckets"][name]["median_err_conditional_ms"] = round(1000 * st.median(cond_values), 1)
            out["buckets"][name]["conditional_mean_delta_ms"] = round(
                1000 * st.mean(c - r for c, r in zip(cond_values, raw_values)), 2)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = characters(args.dump)
    payload = {"schema_version": "duration_calibration_v1", "dump": str(args.dump),
               "tolerance_sec": TOL, "knots": list(KNOTS), **evaluate(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key not in ("knots",)},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
