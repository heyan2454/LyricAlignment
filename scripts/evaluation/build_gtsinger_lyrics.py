#!/usr/bin/env python3
"""Generate a plain-text lyrics file from a GTSinger JSON segment.

GTSinger JSON stores word-level lyrics with optional `<AP>` aspiration markers.
This script removes those markers and writes one line per JSON file (or a
joined line if --join-lines is used).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ASPIRATION_RE = re.compile(r"<AP>|<AP/>", re.IGNORECASE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--join-lines", action="store_true", help="Join all words into one line")
    args = parser.parse_args()

    data = json.loads(args.json.read_text(encoding="utf-8"))
    words = [str(row.get("word", "")) for row in data if isinstance(row, dict)]
    text = "".join(words)
    text = ASPIRATION_RE.sub("", text)
    # If the JSON has explicit line grouping, this simple version writes one line.
    lines = [text] if args.join_lines else [text]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "characters": len(text)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
