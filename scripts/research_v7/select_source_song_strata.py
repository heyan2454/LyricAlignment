#!/usr/bin/env python3
"""Select one deterministic, longest usable item per source song from a manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True); parser.add_argument("--out", required=True)
    parser.add_argument("--dataset", required=True); parser.add_argument("--split", required=True)
    args = parser.parse_args(argv)
    selected = {}
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if not line: continue
        row = json.loads(line)
        if row.get("dataset") != args.dataset or row.get("split") != args.split: continue
        path = Path(row.get("audio_path", "")); gt = Path(row.get("gt_path", ""))
        if not path.is_file() or not gt.is_file(): continue
        song = row.get("source_song_id") or row["item_id"]
        key = (float(row.get("duration_sec") or 0), row["item_id"])
        if song not in selected or key > (float(selected[song].get("duration_sec") or 0), selected[song]["item_id"]): selected[song] = row
    rows = [selected[song] for song in sorted(selected)]
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True); target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"ok": True, "items": len(rows), "source_songs": len(selected), "out": str(target)}, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
