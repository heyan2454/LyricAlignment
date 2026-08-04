#!/usr/bin/env python3
"""Build a production-like wrong-prefix then corrected-prefix recovery chain."""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def units(path: str, limit: int) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line][:limit]


def duration(path: str) -> float:
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--manifest", required=True); parser.add_argument("--out", required=True)
    parser.add_argument("--dataset", default="mir1k"); parser.add_argument("--split", default="heldout"); parser.add_argument("--unit-count", type=int, default=80)
    args = parser.parse_args(argv); output = []
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if not line: continue
        row = json.loads(line)
        if row.get("dataset") != args.dataset or row.get("split") != args.split: continue
        text = units(row["gt_path"], args.unit_count)
        if len(text) < args.unit_count: continue
        n, cut1, cut2 = len(text), args.unit_count // 3, 2 * args.unit_count // 3
        bad_prefix = list(reversed(text[:cut1])) + text[cut1:cut2]
        common = {key: row.get(key) for key in ("song_id", "source_song_id", "dataset", "split", "language", "audio_path", "gt_path", "text_source")}
        common.update({"item_id": row["item_id"], "audio_start_sec": 0.0, "audio_end_sec": duration(row["audio_path"]), "duration_sec": duration(row["audio_path"]),
                       "audio_relation": "full_source_audio", "provenance": {"recovery_chain": "correct_first__reversed_committed_prefix__corrected_prefix"}})
        def add(tag, mode, parent, prefix, start, end, relation):
            output.append({**common, "request_id": f"{row['item_id']}:REC:{tag}", "workflow_mode": mode, "parent_request_id": parent,
                           "mutation_type": "baseline" if tag != "corrupt" else "replace", "text_units": prefix,
                           "text_start_index": 0, "text_end_index": len(prefix), "source_text_start_index": start, "source_text_end_index": end,
                           "timestamp_slot_indices": list(range(len(prefix))), "input_variant": "strict_serial_committed_prefix_all_slots",
                           "text_relation": relation, "baseline_unit_count": n, "n_base": n})
        p0 = f"{row['item_id']}:REC:p0"; first = f"{row['item_id']}:REC:first"; corrupt = f"{row['item_id']}:REC:corrupt"
        add("p0", "production_full_once", None, text, 0, n, "exact")
        add("first", "recovery_correct_prefix", None, text[:cut1], 0, cut1, "exact")
        add("corrupt", "recovery_corrupted_prefix", first, bad_prefix, cut1, cut2, "reversed_committed_prefix")
        add("recovered", "recovery_corrected_prefix", corrupt, text, cut2, n, "corrected_after_corruption")
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")
    print(json.dumps({"ok": True, "items": len({row['item_id'] for row in output}), "requests": len(output), "out": str(target)}, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
