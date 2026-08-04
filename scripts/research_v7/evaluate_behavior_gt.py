#!/usr/bin/env python3
"""Evaluate v7 GT attempts and report paired micro/macro/source-song summaries."""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


def source_song_id(text_source: str, item_id: str) -> str:
    """Recover source-song identity from a materialized GT directory when present."""
    manifest = Path(text_source).parent / "source_manifest.json"
    if manifest.is_file():
        try:
            return str(json.loads(manifest.read_text(encoding="utf-8")).get("song_id") or item_id)
        except (OSError, json.JSONDecodeError):
            pass
    return item_id


def gt_index_for_request_index(request: dict, index: int) -> int | None:
    """Map a mutated request index back to the baseline GT index.

    This prevents head/middle extra or missing text from being scored against a
    coincidentally equal character at the wrong original position.
    """
    params = request.get("mutation_parameters", {})
    n = int(params.get("baseline_unit_count") or len(request["text_units"]))
    kind = request["mutation_type"]; position = params.get("position") or params.get("mutation_position") or "whole"
    if kind in {"baseline", "replace"}:
        return index if index < n else None
    if kind == "extra":
        added = int(params.get("actual_added_units") or max(0, len(request["text_units"]) - n))
        if position == "tail": return index if index < n else None
        if position == "head": return index - added if added <= index < added + n else None
        pivot = n // 2
        if index < pivot: return index
        if index >= pivot + added and index - added < n: return index - added
        return None
    if kind == "missing":
        removed = int(params.get("actual_removed_units") or max(0, n - len(request["text_units"])))
        if position == "tail": return index
        if position == "head": return index + removed
        if position == "middle":
            pivot = (n - removed) // 2
            return index if index < pivot else index + removed
        if position == "dispersed":
            discarded = set(random.Random(int(params.get("selection_seed") or 0)).sample(range(n), removed))
            kept = [i for i in range(n) if i not in discarded]
            return kept[index] if index < len(kept) else None
    return None


def summarize(pairs: list[dict], seed: int, replicates: int, eligible_count: int | None = None) -> dict:
    values = [row["delta_mae_sec"] for row in pairs]
    by_song: dict[str, list[float]] = defaultdict(list)
    for row in pairs:
        by_song[row["source_song_id"]].append(row["delta_mae_sec"])
    song_means = {song: sum(v) / len(v) for song, v in by_song.items()}
    bootstrap = []
    if song_means:
        rng = random.Random(seed); songs = sorted(song_means)
        for _ in range(replicates):
            sample = [song_means[rng.choice(songs)] for _ in songs]
            bootstrap.append(sum(sample) / len(sample))
        bootstrap.sort()
    def quantile(q: float):
        if not bootstrap:
            return None
        return bootstrap[round((len(bootstrap) - 1) * q)]
    return {
        "eligible_non_no_match_count": eligible_count, "applicable_count": len(pairs),
        "unscorable_no_matching_unit_count": (eligible_count - len(pairs)) if eligible_count is not None else None,
        "source_song_count": len(song_means),
        "improve": sum(row["verdict"] == "improve" for row in pairs),
        "harm": sum(row["verdict"] == "harm" for row in pairs),
        "no_change": sum(row["verdict"] == "no_change" for row in pairs),
        "micro_mean_delta_mae_sec": sum(values) / len(values) if values else None,
        "macro_source_song_mean_delta_mae_sec": sum(song_means.values()) / len(song_means) if song_means else None,
        "source_song_bootstrap": {"seed": seed, "replicates": replicates,
                                  "p025": quantile(.025), "median": quantile(.5), "p975": quantile(.975)},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True); parser.add_argument("--out", required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000); parser.add_argument("--seed", type=int, default=3407)
    args = parser.parse_args(argv)
    collection = json.loads(Path(args.collection).read_text(encoding="utf-8")); root = Path(collection["out_root"])
    results = []
    for record in collection["records"]:
        evidence = json.loads((root / record["source"]).read_text(encoding="utf-8")); attempt = evidence["attempt"]; request = attempt["request"]
        relation = request.get("mutation_parameters", {}).get("audio_relation")
        text_relation = request.get("mutation_parameters", {}).get("text_relation")
        common = {"request_id": request["request_id"], "item_id": request["item_id"], "mutation_type": request["mutation_type"], "audio_relation": relation, "text_relation": text_relation,
                  "source_song_id": source_song_id(request["text_source"], request["item_id"])}
        if attempt["status"] != "ok" or request["mutation_type"] == "no_match":
            results.append({**common, "scored": False, "reason": "no_match_or_failed"}); continue
        try:
            gt = [json.loads(line) for line in Path(request["text_source"]).read_text(encoding="utf-8").splitlines() if line]
        except (OSError, json.JSONDecodeError):
            results.append({**common, "scored": False, "reason": "no_gt"}); continue
        limit = int(request.get("mutation_parameters", {}).get("baseline_unit_count") or len(request["text_units"]))
        errors = []
        for row in attempt["decoder_outputs"]["official"]["rows"]:
            index = int(row["global_character_index"]); gt_index = gt_index_for_request_index(request, index)
            if gt_index is not None and gt_index < limit and gt_index < len(gt) and index < len(request["text_units"]) and request["text_units"][index] == gt[gt_index]["normalized_character"]:
                errors.extend((abs(float(row["fixed_global_start_sec"]) - float(gt[gt_index]["start_sec"])),
                               abs(float(row["fixed_global_end_sec"]) - float(gt[gt_index]["end_sec"]))))
        results.append({**common, "scored": bool(errors), "matched_unit_count": len(errors) // 2,
                        "boundary_mae_sec": sum(errors) / len(errors) if errors else None})
    def is_baseline(row: dict) -> bool:
        return row["mutation_type"] == "baseline" and row.get("audio_relation") in {None, "full_source_audio"}
    baselines = {row["item_id"]: row for row in results if is_baseline(row) and row["scored"]}
    paired = []
    for row in results:
        baseline = baselines.get(row["item_id"])
        if not is_baseline(row) and row["scored"] and baseline:
            delta = row["boundary_mae_sec"] - baseline["boundary_mae_sec"]
            paired.append({**row, "baseline_mae_sec": baseline["boundary_mae_sec"], "delta_mae_sec": delta,
                           "verdict": "improve" if delta < 0 else "harm" if delta > 0 else "no_change"})
    def condition(row: dict) -> str:
        if row["mutation_type"] == "baseline":
            return str(row.get("audio_relation"))
        if row["mutation_type"] == "replace" and row.get("text_relation") not in {None, "partial_cross_song"}:
            return str(row["text_relation"])
        return row["mutation_type"]
    eligible = [row for row in results if row["mutation_type"] != "no_match" and not is_baseline(row) and row.get("reason") != "no_gt"]
    names = sorted({condition(row) for row in eligible})
    by_mutation = {name: summarize([row for row in paired if condition(row) == name], args.seed, args.bootstrap_replicates,
                                   sum(condition(row) == name for row in eligible)) for name in names}
    output = {"schema": "v7/behavior_gt_paired_v2", "attempts": results, "paired": paired,
              "paired_summary": summarize(paired, args.seed, args.bootstrap_replicates, len(eligible)), "by_mutation": by_mutation,
              "note": "No-match is deliberately not scored as GT accuracy; it is a behavior/taxonomy case."}
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "scored": sum(row["scored"] for row in results), "paired": len(paired), "out": args.out}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
