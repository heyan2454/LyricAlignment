#!/usr/bin/env python3
"""Resumable downloader for a user-reviewed official OpenCpop archive URL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Download only from a license-reviewed official OpenCpop URL.")
    parser.add_argument("--url", required=True, help="Official direct archive URL reviewed by the user")
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dest.exists():
        actual_hash = sha256_file(args.dest) if args.expected_sha256 else None
        if args.expected_sha256 and actual_hash.lower() != args.expected_sha256.lower():
            raise SystemExit(f"Existing destination SHA256 mismatch: {actual_hash}")
        print(json.dumps({"status": "exists", "path": str(args.dest), "size_bytes": args.dest.stat().st_size, "sha256": actual_hash}))
        return
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "url": args.url, "destination": str(args.dest)}))
        return

    args.dest.parent.mkdir(parents=True, exist_ok=True)
    partial = args.dest.with_suffix(args.dest.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    request = urllib.request.Request(args.url, headers=headers)

    try:
        with urllib.request.urlopen(request) as response:
            status = getattr(response, "status", response.getcode())
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raise RuntimeError(
                    "Server returned HTML instead of an archive. The URL may require login, authorization, or form approval."
                )

            mode = "wb"
            expected_total: int | None = None
            content_range = response.headers.get("Content-Range")
            if offset:
                if status == 206:
                    match = CONTENT_RANGE_RE.fullmatch(content_range.strip()) if content_range else None
                    if not match:
                        raise RuntimeError(f"206 response missing a valid Content-Range: {content_range!r}")
                    range_start = int(match.group(1))
                    if range_start != offset:
                        raise RuntimeError(f"Range resume mismatch: requested {offset}, server started at {range_start}")
                    mode = "ab"
                    if match.group(3) != "*":
                        expected_total = int(match.group(3))
                elif status == 200:
                    # The server ignored Range. Restart safely instead of appending a full file.
                    mode = "wb"
                    offset = 0
                else:
                    raise RuntimeError(f"Unexpected HTTP status for resume: {status}")
            elif status not in (200, 206):
                raise RuntimeError(f"Unexpected HTTP status: {status}")

            content_length = response.headers.get("Content-Length")
            if expected_total is None and content_length and content_length.isdigit():
                expected_total = offset + int(content_length)

            with partial.open(mode) as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)

        actual_size = partial.stat().st_size
        if expected_total is not None and actual_size != expected_total:
            raise RuntimeError(f"Incomplete download: expected {expected_total} bytes, got {actual_size}")
        actual_hash = sha256_file(partial) if args.expected_sha256 else None
        if args.expected_sha256 and actual_hash.lower() != args.expected_sha256.lower():
            raise RuntimeError(f"SHA256 mismatch: expected {args.expected_sha256}, got {actual_hash}")
        partial.replace(args.dest)
    except (urllib.error.URLError, OSError, RuntimeError):
        # Keep a valid partial archive for a future HTTP range retry.
        raise

    print(json.dumps({"status": "downloaded", "path": str(args.dest), "size_bytes": args.dest.stat().st_size, "sha256": actual_hash}))


if __name__ == "__main__":
    main()
