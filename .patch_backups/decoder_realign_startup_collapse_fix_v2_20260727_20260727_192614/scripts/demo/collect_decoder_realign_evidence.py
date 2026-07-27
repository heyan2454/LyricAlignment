#!/usr/bin/env python3
"""Collect a bounded-size evidence package for decoder/realign Demo review.

The collector never includes audio, videos, model weights, or full raw logs.  It
first writes compact per-character evidence; if the compressed archive exceeds
the requested cap, it automatically falls back to anomaly-only character rows
and shorter case/log excerpts.
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

BRANCHES = (
    "official_no_realign",
    "official_realign",
    "raw_no_realign",
    "raw_realign",
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"_read_error": f"{type(exc).__name__}: {exc}", "_path": str(path)}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def discover_song_roots(root: Path) -> list[Path]:
    direct = root / "alignments" / "r2_decoder_realign" / "comparison_manifest.json"
    if direct.is_file():
        return [root]
    found = []
    for manifest in root.rglob("alignments/r2_decoder_realign/comparison_manifest.json"):
        found.append(manifest.parents[2])
    return sorted(set(found))


def branch_alignment(song_root: Path, branch: str) -> Path:
    return song_root / "alignments" / "r2_decoder_realign" / "branches" / branch / "alignment.json"


def compact_character(song: str, branch: str, row: dict[str, Any]) -> dict[str, Any]:
    start = float(row.get("start_sec", 0.0))
    end = float(row.get("end_sec", start))
    return {
        "song": song,
        "branch": branch,
        "index": int(row.get("global_character_index", -1)),
        "line": row.get("line_index"),
        "character": row.get("character"),
        "start": start,
        "end": end,
        "duration": end - start,
        "raw_start": row.get("raw_global_start_sec"),
        "raw_end": row.get("raw_global_end_sec"),
        "official_start": row.get("official_fixed_global_start_sec"),
        "official_end": row.get("official_fixed_global_end_sec"),
        "selected_start": row.get("selected_start_sec"),
        "selected_end": row.get("selected_end_sec"),
        "owner_window": row.get("owner_window_index"),
        "overlap_compressed": bool(row.get("overlap_compressed")),
        "compression_sec": row.get("overlap_compression_sec"),
        "compressed_to_zero": bool(row.get("overlap_compression_collapsed_to_zero")),
        "realign_projection": row.get("quick_realign_projection"),
        "realign_source_start": row.get("quick_realign_source_start_sec"),
        "realign_source_end": row.get("quick_realign_source_end_sec"),
    }


def is_anomaly(row: dict[str, Any]) -> bool:
    return (
        float(row.get("duration", 0.0)) <= 0.08 + 1e-9
        or bool(row.get("overlap_compressed"))
        or row.get("realign_projection") is not None
    )


def is_severe(row: dict[str, Any]) -> bool:
    return (
        float(row.get("duration", 0.0)) <= 1e-9
        or bool(row.get("compressed_to_zero"))
        or row.get("realign_projection") is not None
    )


def compact_decision(song: str, branch: str, decision: dict[str, Any]) -> dict[str, Any]:
    agreement = decision.get("context_agreement") or {}
    comparison = agreement.get("comparison") or {}
    acceptance = decision.get("acceptance") or {}
    splice = decision.get("splice") or {}
    source = decision.get("source_candidate") or {}
    return {
        "song": song,
        "branch": branch,
        "case_id": decision.get("case_id"),
        "target_indices": decision.get("target_indices"),
        "candidate_kind": source.get("candidate_kind") or source.get("kind"),
        "severity_score": source.get("severity_score"),
        "selected": bool(decision.get("selected")),
        "reason": decision.get("reason"),
        "left_anchor_index": (decision.get("left_anchor") or {}).get("global_character_index"),
        "right_anchor_index": (decision.get("right_anchor") or {}).get("global_character_index"),
        "anchor_rejection_count": len(decision.get("anchor_rejections") or []),
        "agreement_supported": agreement.get("supported"),
        "agreement_max_sec": comparison.get("max_boundary_difference_sec"),
        "acceptance_accepted": acceptance.get("accepted"),
        "acceptance_reason": acceptance.get("reason"),
        "splice_valid": splice.get("valid"),
        "splice_projection": splice.get("projection"),
        "splice_structural": splice.get("structural"),
        "max_boundary_change_sec": decision.get("max_boundary_change_sec"),
        "exact_raw_structural": decision.get("exact_local_raw_structural"),
        "exact_decoded_structural": decision.get("exact_local_decoded_structural"),
    }


def tail_text(path: Path, *, lines: int, bytes_cap: int) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return f"READ ERROR: {exc}\n"
    data = data[-bytes_cap:]
    text = data.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:]) + "\n"


def make_archive(staging: Path, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz", compresslevel=6) as archive:
        archive.add(staging, arcname="decoder_realign_evidence")
    temporary.replace(output)
    return output.stat().st_size


def build_staging(
    song_roots: list[Path], staging: Path, *, character_mode: str,
    max_cases_per_branch: int, log_tail_lines: int, include_logs: bool,
    probe_roots: list[Path],
) -> dict[str, Any]:
    if character_mode not in {"all", "anomaly", "severe", "none"}:
        raise ValueError(character_mode)
    summaries: list[dict[str, Any]] = []
    character_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []

    for song_root in song_roots:
        song = song_root.name
        align_root = song_root / "alignments" / "r2_decoder_realign"
        comparison = read_json(align_root / "comparison_manifest.json")
        song_summary: dict[str, Any] = {
            "song": song,
            "song_root": str(song_root),
            "comparison": {
                "request_hash": comparison.get("request_hash"),
                "trajectory_match": comparison.get("trajectory_match"),
                "trajectory_hash": comparison.get("trajectory_hash"),
                "request": comparison.get("request"),
            },
            "branches": {},
            "batch_plan": read_json(song_root / "batch_plan.json"),
            "batch_manifest": read_json(song_root / "batch_manifest.json"),
            "render_manifest": read_json(song_root / "render_manifest.json"),
        }
        for branch in BRANCHES:
            path = branch_alignment(song_root, branch)
            payload = read_json(path)
            rows = payload.get("characters") or []
            compact = [compact_character(song, branch, row) for row in rows]
            if character_mode == "anomaly":
                compact = [row for row in compact if is_anomaly(row)]
            elif character_mode == "severe":
                compact = [row for row in compact if is_severe(row)]
            elif character_mode == "none":
                compact = []
            character_rows.extend(compact)

            realign = payload.get("realign") or read_json(path.parent / "realign.json")
            decisions = realign.get("decisions") or []
            reason_counts = collections.Counter(str(row.get("reason")) for row in decisions)
            selected_count = sum(bool(row.get("selected")) for row in decisions)
            ordered_cases = sorted(
                decisions,
                key=lambda row: (
                    not bool(row.get("selected")),
                    -float((row.get("source_candidate") or {}).get("severity_score") or 0.0),
                ),
            )[:max_cases_per_branch]
            case_rows.extend(compact_decision(song, branch, row) for row in ordered_cases)
            song_summary["branches"][branch] = {
                "identity": payload.get("identity"),
                "summary": payload.get("summary"),
                "quality": read_json(path.with_name("alignment.quality.json")),
                "realign_funnel": {
                    "candidate_count": len(decisions),
                    "selected_count": selected_count,
                    "reason_counts": dict(reason_counts),
                    "anchor_policy": realign.get("anchor_policy"),
                    "final_structural": realign.get("final_structural"),
                },
                "character_rows_collected": len(compact),
            }
        summaries.append(song_summary)

        if include_logs:
            log_dir = staging / "log_tails" / song
            for name in ("alignment.log", "render.log"):
                source = song_root / name
                if source.is_file():
                    target = log_dir / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(
                        tail_text(source, lines=log_tail_lines, bytes_cap=128 * 1024),
                        encoding="utf-8",
                    )

    probe_summaries: list[dict[str, Any]] = []
    for probe_root in probe_roots:
        diagnostics = read_json(probe_root / "raw_guarded_realign.json")
        complete = read_json(probe_root / "complete.json")
        decisions = diagnostics.get("decisions") or []
        reason_counts = collections.Counter(str(row.get("reason")) for row in decisions)
        ordered_cases = sorted(
            decisions,
            key=lambda row: (
                not bool(row.get("would_select") or row.get("selected")),
                -float((row.get("source_candidate") or {}).get("severity_score") or 0.0),
            ),
        )[:max_cases_per_branch]
        case_rows.extend(
            compact_decision(probe_root.name, f"probe:{probe_root.name}", row)
            for row in ordered_cases
        )
        probe_summaries.append({
            "name": probe_root.name,
            "path": str(probe_root),
            "complete": complete,
            "candidate_count": len(decisions),
            "selected_count": sum(bool(row.get("selected")) for row in decisions),
            "would_select_count": sum(bool(row.get("would_select")) for row in decisions),
            "reason_counts": dict(reason_counts),
            "anchor_policy": diagnostics.get("anchor_policy"),
            "final_structural": diagnostics.get("final_structural"),
        })

    write_json(staging / "summary.json", {
        "schema_version": "decoder_realign_evidence_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "collection_mode": character_mode,
        "song_count": len(song_roots),
        "songs": summaries,
        "probes": probe_summaries,
    })
    character_count = write_jsonl(staging / "characters.jsonl", character_rows)
    case_count = write_jsonl(staging / "realign_cases.jsonl", case_rows)
    return {
        "mode": character_mode,
        "song_count": len(song_roots),
        "character_row_count": character_count,
        "case_row_count": case_count,
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input_root", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--max-total-mib", type=float, default=12.0)
    p.add_argument("--max-cases-per-branch", type=int, default=100)
    p.add_argument("--log-tail-lines", type=int, default=200)
    p.add_argument(
        "--probe-root", type=Path, action="append", default=[],
        help="optional single-branch A2/A4 shadow output containing raw_guarded_realign.json",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    root = args.input_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    songs = discover_song_roots(root)
    if not songs:
        raise FileNotFoundError(f"no decoder/realign comparison outputs under {root}")
    output = args.output or root.parent / f"decoder_realign_evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
    output = output.expanduser().resolve()
    cap = int(args.max_total_mib * 1024 * 1024)
    probe_roots = [path.expanduser().resolve() for path in args.probe_root]
    for path in probe_roots:
        if not (path / "raw_guarded_realign.json").is_file():
            raise FileNotFoundError(path / "raw_guarded_realign.json")

    with tempfile.TemporaryDirectory(prefix="decoder_realign_collect_") as temporary:
        staging = Path(temporary) / "staging"
        attempts = [
            {
                "character_mode": "all",
                "max_cases": args.max_cases_per_branch,
                "log_lines": args.log_tail_lines,
                "include_logs": True,
                "fallback_reason": None,
            },
            {
                "character_mode": "anomaly",
                "max_cases": min(args.max_cases_per_branch, 50),
                "log_lines": min(args.log_tail_lines, 100),
                "include_logs": True,
                "fallback_reason": "all_characters_exceeded_size_cap",
            },
            {
                "character_mode": "severe",
                "max_cases": min(args.max_cases_per_branch, 20),
                "log_lines": 0,
                "include_logs": False,
                "fallback_reason": "anomaly_evidence_exceeded_size_cap",
            },
            {
                "character_mode": "none",
                "max_cases": 0,
                "log_lines": 0,
                "include_logs": False,
                "fallback_reason": "severe_evidence_exceeded_size_cap_summary_only",
            },
        ]
        size = 0
        metadata: dict[str, Any] = {}
        for attempt in attempts:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir()
            metadata = build_staging(
                songs, staging,
                character_mode=str(attempt["character_mode"]),
                max_cases_per_branch=int(attempt["max_cases"]),
                log_tail_lines=int(attempt["log_lines"]),
                include_logs=bool(attempt["include_logs"]),
                probe_roots=probe_roots,
            )
            write_json(staging / "collection_manifest.json", {
                **metadata,
                "input_root": str(root),
                "max_total_bytes": cap,
                "fallback_reason": attempt["fallback_reason"],
                "excluded": [
                    "audio", "video", "model weights", "full logs", "shadow-row tensors",
                    *([] if attempt["character_mode"] == "all" else ["lower-priority character rows"]),
                ],
            })
            size = make_archive(staging, output)
            if size <= cap:
                break
        if size > cap:
            output.unlink(missing_ok=True)
            raise RuntimeError(
                f"summary-only evidence still exceeds cap: {size} > {cap} bytes"
            )

    print(json.dumps({
        "status": "complete",
        "output": str(output),
        "size_bytes": size,
        "size_mib": size / (1024 * 1024),
        "cap_mib": args.max_total_mib,
        **metadata,
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
