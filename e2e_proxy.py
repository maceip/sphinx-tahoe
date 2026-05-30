"""P-OR end-to-end proxy: mixnet between Claude CLI and Anthropic API.

Usage:
  ANTHROPIC_API_KEY=sk-ant-... python3 e2e_proxy.py

Then in another terminal:
  ANTHROPIC_BASE_URL=http://127.0.0.1:8000 ANTHROPIC_API_KEY=none claude --dangerously-skip-permissions

The proxy intercepts HTTP requests from Claude CLI, routes them through
a simulated 5-node Outfox mixnet, and the exit node makes the real API
call to api.anthropic.com. Responses stream back through a SURB circuit.
"""

import asyncio
import json
import os
import sys
import struct
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from sphinxmix.mixnet import MixnetSim, Client
from sphinxmix.OutfoxParams import FLAG_REAL, FLAG_DUMMY, verify_payload
from sphinxmix.OutfoxClient import surb_use

REAL_API_BASE = "https://api.anthropic.com"
REAL_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LISTEN_PORT = int(os.environ.get("PROXY_PORT", "8000"))
NUM_MIX_NODES = 5
FWD_HOPS = 3
RPLY_HOPS = 3


class MixnetProxy:
    """Wraps the mixnet simulator with forward/reply routing.

    Supports two reply modes:
      SURB:    single-shot reply for short responses (existing)
      Circuit: streaming reply for token-by-token delivery (new)
    """

    def __init__(self):
        self.sim = MixnetSim(num_nodes=NUM_MIX_NODES, payload_size=32768)
        self.client = self.sim.create_client(b"proxy_client__")
        self.fwd_path = self.sim.node_ids()[:FWD_HOPS]
        self.rply_relays = self.sim.node_ids()[FWD_HOPS:FWD_HOPS + RPLY_HOPS]
        self._active_stream = None
        self._active_circuit_id = None
        print(f"[mixnet] {NUM_MIX_NODES} nodes, fwd={FWD_HOPS} hops, rply={RPLY_HOPS} hops")

    def route_request(self, request_bytes):
        """Route a request with circuit setup. Returns (msg, surb_info, circuit_id)."""
        header, payload, circuit_id = self.client.create_repliable_with_circuit(
            self.fwd_path, self.rply_relays, request_bytes)

        result = self.sim.route_forward(self.fwd_path, header, payload)
        if result is None:
            return None, None, None

        routing, flag, msg, surb_info = result

        stream, _ = self.sim.create_circuit_stream(self.fwd_path, circuit_id)
        self._active_stream = stream
        self._active_circuit_id = circuit_id

        return msg, surb_info, circuit_id

    def stream_response_chunk(self, chunk):
        """Stream a response chunk back through the circuit. Returns decrypted bytes or None."""
        if self._active_stream is None:
            return None
        packet = self.sim.stream_token(self.fwd_path, self._active_stream, chunk)
        if packet is None:
            return None
        return self.client.decrypt_circuit(packet)

    def route_reply(self, surb_info, reply_bytes):
        """Route a reply back through the SURB (single-shot fallback)."""
        surb_header, surb_key = surb_info
        reply_header, reply_payload = surb_use(
            self.sim.params, (surb_header, surb_key), reply_bytes)

        reply_header, reply_payload = self.sim.route_reply(
            self.rply_relays, reply_header, reply_payload)
        if reply_header is None:
            return None

        return self.client.receive_reply(reply_header, reply_payload)


mixnet = MixnetProxy()


def make_real_api_call(method, path, headers_dict, body=None):
    """Make the actual API call to api.anthropic.com."""
    url = REAL_API_BASE + path

    filtered_headers = {}
    for k, v in headers_dict.items():
        k_lower = k.lower()
        if k_lower in ("host", "content-length", "transfer-encoding"):
            continue
        filtered_headers[k] = v

    filtered_headers["x-api-key"] = REAL_API_KEY
    if "anthropic-version" not in {k.lower(): k for k in filtered_headers}:
        filtered_headers["anthropic-version"] = "2023-06-01"

    req = Request(url, data=body, headers=filtered_headers, method=method)
    try:
        resp = urlopen(req, timeout=120)
        return resp.status, dict(resp.headers), resp.read()
    except HTTPError as e:
        return e.code, dict(e.headers), e.read()


class ProxyHandler(BaseHTTPRequestHandler):
    """HTTP handler that routes requests through the mixnet."""

    def do_POST(self):
        self._handle()

    def do_GET(self):
        self._handle()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def _handle(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        request_meta = json.dumps({
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers),
        }).encode()

        if body:
            request_payload = request_meta + b"\n---BODY---\n" + body
        else:
            request_payload = request_meta

        t0 = time.time()

        if len(request_payload) > mixnet.sim.params.payload_size - 1024:
            print(f"[mixnet] payload too large ({len(request_payload)} bytes), direct routing")
            msg_bytes = request_payload
            surb_info = None
            circuit_id = None
        else:
            msg_bytes, surb_info, circuit_id = mixnet.route_request(request_payload)
            if msg_bytes is None:
                self.send_error(502, "Mixnet forward routing failed")
                return

        t_fwd = time.time() - t0

        if b"\n---BODY---\n" in msg_bytes:
            meta_part, body_part = msg_bytes.split(b"\n---BODY---\n", 1)
        else:
            meta_part = msg_bytes
            body_part = None

        meta = json.loads(meta_part)

        status, resp_headers, resp_body = make_real_api_call(
            meta["method"], meta["path"], meta["headers"], body_part)

        t_api = time.time() - t0 - t_fwd

        if circuit_id and mixnet._active_stream:
            decrypted = mixnet.stream_response_chunk(resp_body)
            if decrypted is not None:
                resp_body = decrypted
            t_rply = time.time() - t0 - t_fwd - t_api
        elif surb_info and len(resp_body) <= mixnet.sim.params.payload_size - 1024:
            reply_msg = mixnet.route_reply(surb_info, resp_body)
            if reply_msg is not None:
                resp_body = reply_msg
            t_rply = time.time() - t0 - t_fwd - t_api
        else:
            t_rply = 0

        self.send_response(status)
        for k, v in resp_headers.items():
            k_lower = k.lower()
            if k_lower in ("transfer-encoding", "content-encoding", "content-length"):
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp_body)))
        rply_mode = "circuit" if (circuit_id and mixnet._active_stream) else "surb"
        self.send_header("X-Mixnet-Fwd-Ms", f"{t_fwd * 1000:.1f}")
        self.send_header("X-Mixnet-Rply-Ms", f"{t_rply * 1000:.1f}")
        self.send_header("X-Mixnet-Reply-Mode", rply_mode)
        self.end_headers()
        self.wfile.write(resp_body)

        stats = mixnet.sim.stats()
        print(f"[mixnet] {meta['method']} {meta['path']} → {status} "
              f"fwd={t_fwd*1000:.1f}ms api={t_api*1000:.0f}ms rply={t_rply*1000:.1f}ms "
              f"hops={stats['forward']}")

    def log_message(self, format, *args):
        pass


def main():
    if not REAL_API_KEY:
        print("ERROR: Set ANTHROPIC_API_KEY to your real API key")
        print("Usage: ANTHROPIC_API_KEY=sk-ant-... python3 e2e_proxy.py")
        sys.exit(1)

    server = HTTPServer(("127.0.0.1", LISTEN_PORT), ProxyHandler)
    print(f"[proxy] listening on http://127.0.0.1:{LISTEN_PORT}")
    print(f"[proxy] forwarding to {REAL_API_BASE}")
    print()
    print("Run in another terminal:")
    print(f'  ANTHROPIC_BASE_URL=http://127.0.0.1:{LISTEN_PORT} ANTHROPIC_API_KEY=none claude --dangerously-skip-permissions')
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[proxy] shutting down")
        stats = mixnet.sim.stats()
        print(f"[proxy] total hops processed: {stats['forward']}")
        server.server_close()


if __name__ == "__main__":
    main()
