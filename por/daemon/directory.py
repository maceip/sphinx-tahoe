"""Public P-OR directory snapshot server."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence


def make_directory_handler(snapshot_path: str | Path, *, route: str = "/snapshot"):
    """Build a request handler that serves one public directory snapshot file."""

    path = Path(snapshot_path)
    if not route.startswith("/"):
        raise ValueError("route must start with /")

    class DirectorySnapshotHandler(BaseHTTPRequestHandler):
        server_version = "por-directory/0.1"

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._send_bytes(b"ok\n", content_type="text/plain; charset=utf-8")
                return
            if self.path != route:
                self.send_error(404, "not found")
                return
            try:
                data = path.read_bytes()
            except OSError as exc:
                self.send_error(503, f"snapshot unavailable: {exc}")
                return
            self._send_bytes(data, content_type="application/json")

        def log_message(self, _format: str, *_args) -> None:
            return

        def _send_bytes(self, data: bytes, *, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return DirectorySnapshotHandler


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve a public P-OR directory snapshot.")
    parser.add_argument("--snapshot", required=True, help="Directory snapshot JSON file")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--path", default="/snapshot")
    args = parser.parse_args(argv)

    handler = make_directory_handler(args.snapshot, route=args.path)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    host, port = server.server_address
    print(f"directory event=started addr={host}:{port} path={args.path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("directory event=stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
