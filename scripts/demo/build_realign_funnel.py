#!/usr/bin/env python3
"""Build multi-decoder paired realignment plans without Cartesian expansion."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_decoder_roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--decoder-root must be NAME=PATH, got {value!r}")
        name, raw_path = value.split("=", 1)
        name = name.strip()
        if not name or name in roots:
            raise ValueError(f"invalid or duplicate decoder name: {name!r}")
        roots[name] = Path(raw_path).resolve()
    if len(roots) < 2:
        raise ValueError("at least two --decoder-root entries are required")
    return roots


def evidence_payloads(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "evidence").glob("core_*s/*/*.json")):
        payload = read_json(path)
        if payload.get("status") == "complete":
            payload["_path"] = str(path)
            rows.append(payload)
    return rows


def merge_intervals(intervals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(intervals, key=lambda row: (int(row["start"]), int(row["end"])))
    merged: list[dict[str, Any]] = []
    for row in ordered:
        if not merged or int(row["start"]) > int(merged[-1]["end"]) + 1:
            merged.append({**row, "sources": list(row["sources"])})
            continue
        current = merged[-1]
        current["end"] = max(int(current["end"]), int(row["end"]))
        current["severity"] = max(float(current["severity"]), float(row["severity"]))
        current["sources"].extend(row["sources"])
    return merged


def round_robin_cap(rows: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    if maximum <= 0 or len(rows) <= maximum:
        return rows
    grouped: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for row in sorted(rows, key=lambda value: (-float(value["severity_score"]), str(value["pair_id"]))):
        grouped[str(row["item_id"])].append(row)
    selected: list[dict[str, Any]] = []
    keys = sorted(grouped)
    while len(selected) < maximum and keys:
        next_keys = []
        for key in keys:
            if grouped[key] and len(selected) < maximum:
                selected.append(grouped[key].popleft())
            if grouped[key]:
                next_keys.append(key)
        keys = next_keys
    return selected


def union_plan(
    decoder_roots: dict[str, Path],
    *,
    max_cases: int,
    max_target_units: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for decoder, root in sorted(decoder_roots.items()):
        for payload in evidence_payloads(root):
            request = payload["request"]
            key = (str(request["item_id"]), str(request["audio_variant"]), float(request["core_sec"]))
            for candidate in payload.get("natural_candidates", []):
                grouped[key].append({
                    "start": int(candidate["dependency_character_start"]),
                    "end": int(candidate["dependency_character_end"]),
                    "severity": float(candidate.get("severity_score") or 0.0),
                    "sources": [{
                        "decoder": decoder,
                        "case_id": candidate.get("case_id"),
                        "candidate_type": candidate.get("candidate_type"),
                        "trigger_counts": candidate.get("trigger_counts"),
                    }],
                })
    rows: list[dict[str, Any]] = []
    for (item_id, audio_variant, core_sec), intervals in sorted(grouped.items()):
        for merged in merge_intervals(intervals):
            start, end = int(merged["start"]), int(merged["end"])
            if end - start + 1 > max_target_units:
                center = (start + end) // 2
                half = max_target_units // 2
                start = max(0, center - half)
                end = start + max_target_units - 1
            digest = hashlib.sha256(f"{item_id}|{audio_variant}|{core_sec}|{start}|{end}".encode()).hexdigest()[:16]
            sources = merged["sources"]
            rows.append({
                "pair_id": f"pair_{digest}",
                "case_id": f"pair_{digest}",
                "item_id": item_id,
                "audio_variant": audio_variant,
                "core_sec": core_sec,
                "target_start": start,
                "target_end": end,
                "severity_score": float(merged["severity"]),
                "source_decoders": sorted({str(source["decoder"]) for source in sources}),
                "source_candidates": sources,
                "paired_decoders": sorted(decoder_roots),
                "funnel_stage": "exact",
            })
    return round_robin_cap(rows, max_cases)


def case_payloads(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "q2_natural_realign" / "cases").glob("*.json")):
        if path.name.endswith((".status.json", ".failure.json")):
            continue
        payload = read_json(path)
        if payload.get("status") == "complete":
            result[str(payload["case_id"])] = payload
    return result


def selected_rows(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    selection = payload.get("final_non_gt_selection") or {}
    ordinal = selection.get("candidate_ordinal")
    candidates = payload.get("repair_candidates") or []
    if not isinstance(ordinal, int) or not 0 <= ordinal < len(candidates):
        return None
    candidate = candidates[ordinal]
    return list(candidate.get("changed_rows") or [])


def boundary_disagreement(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> float | None:
    if not left or not right:
        return None
    by_left = {int(row["global_character_index"]): row for row in left}
    by_right = {int(row["global_character_index"]): row for row in right}
    common = sorted(set(by_left) & set(by_right))
    if not common:
        return None
    return max(
        max(
            abs(float(by_left[index]["start_sec"]) - float(by_right[index]["start_sec"])),
            abs(float(by_left[index]["end_sec"]) - float(by_right[index]["end_sec"])),
        )
        for index in common
    )


def escalation_plan(
    previous_plan: list[dict[str, Any]],
    decoder_roots: dict[str, Path],
    *,
    next_stage: str,
    disagreement_sec: float,
    max_cases: int,
) -> list[dict[str, Any]]:
    payloads = {decoder: case_payloads(root) for decoder, root in decoder_roots.items()}
    selected: list[dict[str, Any]] = []
    for row in previous_plan:
        case_id = str(row["case_id"])
        reasons: list[str] = []
        outputs: dict[str, list[dict[str, Any]] | None] = {}
        for decoder in sorted(decoder_roots):
            payload = payloads[decoder].get(case_id)
            if payload is None:
                reasons.append(f"{decoder}_missing_or_failed")
                outputs[decoder] = None
                continue
            outputs[decoder] = selected_rows(payload)
            if outputs[decoder] is None:
                reasons.append(f"{decoder}_no_non_gt_selection")
        pairwise: dict[str, float | None] = {}
        maximum_disagreement: float | None = None
        for left, right in itertools.combinations(sorted(decoder_roots), 2):
            disagreement = boundary_disagreement(outputs[left], outputs[right])
            pairwise[f"{left}__vs__{right}"] = disagreement
            if disagreement is not None:
                maximum_disagreement = disagreement if maximum_disagreement is None else max(maximum_disagreement, disagreement)
        if maximum_disagreement is not None and maximum_disagreement > disagreement_sec:
            reasons.append("decoder_selected_outputs_disagree")
        if reasons:
            selected.append({
                **row,
                "funnel_stage": next_stage,
                "escalation_reasons": reasons,
                "selected_output_max_disagreement_sec": maximum_disagreement,
                "selected_output_pairwise_disagreement_sec": pairwise,
            })
    return round_robin_cap(selected, max_cases)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("union", "escalate"), required=True)
    parser.add_argument("--decoder-root", action="append", required=True, help="Repeat NAME=PATH")
    parser.add_argument("--out-plan", type=Path, required=True)
    parser.add_argument("--previous-plan", type=Path)
    parser.add_argument("--next-stage", choices=("plus2", "plus4"))
    parser.add_argument("--max-cases", type=int, default=1000)
    parser.add_argument("--max-target-units", type=int, default=8)
    parser.add_argument("--disagreement-sec", type=float, default=0.24)
    args = parser.parse_args()
    decoder_roots = parse_decoder_roots(args.decoder_root)
    if args.mode == "union":
        rows = union_plan(
            decoder_roots,
            max_cases=args.max_cases,
            max_target_units=args.max_target_units,
        )
    else:
        if args.previous_plan is None or args.next_stage is None:
            raise ValueError("escalate mode requires --previous-plan and --next-stage")
        rows = escalation_plan(
            read_jsonl(args.previous_plan),
            decoder_roots,
            next_stage=args.next_stage,
            disagreement_sec=args.disagreement_sec,
            max_cases=args.max_cases,
        )
    write_jsonl(args.out_plan, rows)
    summary = {
        "mode": args.mode,
        "decoder_roots": {key: str(value) for key, value in decoder_roots.items()},
        "out_plan": str(args.out_plan.resolve()),
        "case_count": len(rows),
        "unique_item_count": len({str(row["item_id"]) for row in rows}),
        "source_decoder_counts": {
            decoder: sum(decoder in row.get("source_decoders", []) for row in rows)
            for decoder in decoder_roots
        },
        "cartesian_product": False,
    }
    atomic_json(args.out_plan.with_suffix(".summary.json"), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
