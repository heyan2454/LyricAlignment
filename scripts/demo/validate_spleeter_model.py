#!/usr/bin/env python3
"""Validate an explicitly stored Spleeter model without requiring .probe."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.spleeter_model import resolve_spleeter_model  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--model-name", default="2stems")
    args = parser.parse_args()
    info = resolve_spleeter_model(args.model_root, args.model_name)
    print(json.dumps(info.as_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
