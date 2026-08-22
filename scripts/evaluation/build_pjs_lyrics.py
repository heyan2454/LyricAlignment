#!/usr/bin/env python3
"""Extract lyric text from a PJS MusicXML file for Japanese alignment smoke."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--musicxml", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    tree = ET.parse(args.musicxml)
    root = tree.getroot()
    ns = {"m": "http://www.musicxml.org/ns/musicxml/3.1"}
    texts = []
    # Try namespace-aware first, fallback to local names.
    for lyric in root.iter():
        tag = lyric.tag.rsplit("}", 1)[-1]
        if tag == "lyric":
            for child in lyric:
                if child.tag.rsplit("}", 1)[-1] == "text" and child.text:
                    texts.append(child.text.strip())
    text = "".join(texts)
    if not text:
        raise SystemExit(f"no lyric text found in {args.musicxml}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "characters": len(text), "lyric": text}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
