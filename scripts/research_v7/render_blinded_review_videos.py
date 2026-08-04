#!/usr/bin/env python3
"""Render anonymized karaoke videos from frozen research-v7 review packets."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.media_render import detect_font, render_media_video


def _number(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _alignment(evidence: dict[str, Any]) -> dict[str, Any]:
    attempt = evidence["attempt"]
    request = attempt["request"]
    rows = list(attempt["decoder_outputs"]["official"]["rows"])
    characters: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        start = _number(row.get("official_fixed_global_start_sec", row.get("fixed_global_start_sec")), 0.0)
        end = max(start, _number(row.get("official_fixed_global_end_sec", row.get("fixed_global_end_sec")), start))
        characters.append({
            "global_character_index": index,
            "line_index": index // 18,
            "index_in_line": index % 18,
            "character": str(row.get("character") or row.get("alignment_unit") or ""),
            "alignment_unit": str(row.get("alignment_unit") or row.get("character") or ""),
            "display_text": str(row.get("display_text") or row.get("alignment_unit") or row.get("character") or ""),
            "display_prefix": str(row.get("display_prefix") or ""),
            "display_suffix": str(row.get("display_suffix") or ""),
            "start_sec": start,
            "end_sec": end,
        })
    line_count = (len(characters) + 17) // 18
    duration = _number(request.get("audio_end_sec"), 0.0) - _number(request.get("audio_start_sec"), 0.0)
    return {
        "schema_version": "research_v7_review_alignment_v1",
        "identity": {"request_hash": str(attempt.get("attempt_id") or request.get("request_id") or "unknown")},
        "summary": {"audio_duration_sec": max(0.01, duration)},
        "lines": [{"line_index": index} for index in range(line_count)],
        "characters": characters,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True,
                        help="experimenter-only blind key; it is never copied to reviewer outputs")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--profile", choices=("review", "final"), default="review")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    packet_path = args.packets.resolve()
    run_root = packet_path.parent
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    key_payload = json.loads(args.key.resolve().read_text(encoding="utf-8"))
    request_by_blind_id = {str(row["blind_id"]): str(row["request_id"]) for row in key_payload["key"]}
    packets = list(payload["packets"])
    if args.limit is not None:
        packets = packets[:args.limit]
    font = detect_font("Noto Sans CJK SC")
    args.out.mkdir(parents=True, exist_ok=True)
    completed = 0
    for packet in packets:
        blind_id = str(packet["blind_id"])
        request_id = request_by_blind_id.get(blind_id)
        if request_id is None:
            raise RuntimeError(f"blind key has no request mapping for {blind_id}")
        # The key resolves an evidence file only inside the renderer.  The
        # reviewer output contains the blind ID alone, preserving blinding.
        candidates = sorted((run_root / "items" / str(packet["comparison_group"])).glob("*.json"))
        matched: Path | None = None
        for candidate in candidates:
            candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
            request = candidate_payload.get("attempt", {}).get("request", {})
            if str(request.get("request_id")) == request_id:
                matched = candidate
                break
        if matched is None:
            raise RuntimeError(f"cannot uniquely resolve blinded packet {blind_id}; use a packet/evidence mapping artifact")
        evidence_payload = json.loads(matched.read_text(encoding="utf-8"))
        alignment_path = args.out / "alignments" / f"{blind_id}.json"
        alignment_path.parent.mkdir(parents=True, exist_ok=True)
        alignment_path.write_text(json.dumps(_alignment(evidence_payload), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        output = args.out / "videos" / f"{blind_id}.mp4"
        render_media_video(
            alignment_path=alignment_path,
            visual_source=None,
            audio_track=Path(packet["audio_path"]),
            output_path=output,
            ass_path=args.out / "ass" / f"{blind_id}.ass",
            label=f"Blind review · {blind_id}", font=font, profile=args.profile, force=args.force,
        )
        completed += 1
        print(json.dumps({"status": "complete", "blind_id": blind_id, "output": str(output)}, ensure_ascii=False), flush=True)
    print(json.dumps({"status": "complete", "rendered": completed, "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
