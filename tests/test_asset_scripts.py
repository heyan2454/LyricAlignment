from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_verify_assets_creates_output_parent(tmp_path: Path) -> None:
    asset = tmp_path / "asset"
    asset.mkdir()
    (asset / "a.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "nested" / "inventory.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "assets" / "verify_assets.py"),
            "--asset",
            "demo",
            str(asset),
            "--out",
            str(out),
        ],
        check=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["demo"]["file_count"] == 1


class IgnoreRangeHandler(http.server.BaseHTTPRequestHandler):
    payload = b"complete archive bytes"

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, format: str, *args: object) -> None:
        pass


def test_opencpop_resume_restarts_when_server_ignores_range(tmp_path: Path) -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), IgnoreRangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        dest = tmp_path / "opencpop.zip"
        partial = tmp_path / "opencpop.zip.part"
        partial.write_bytes(b"stale partial")
        url = f"http://127.0.0.1:{server.server_port}/opencpop.zip"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "assets" / "download_opencpop.py"),
                "--url",
                url,
                "--dest",
                str(dest),
            ],
            check=True,
        )
        assert dest.read_bytes() == IgnoreRangeHandler.payload
    finally:
        server.shutdown()
        server.server_close()
