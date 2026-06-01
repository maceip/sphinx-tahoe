"""The enclave-plane server entry point actually binds and serves over HTTP."""

import json
import threading
from urllib.request import urlopen

from por.directory import DiscoveryRequest
from por.enclave_plane import PlainEnclavePlaneHttpClient
from por.enclave_plane_server import serve_enclave_plane
from por.expert_route import RouteIntent
from por.matcher import (
    PLAIN_MATCHER_V1,
    PlainEnclavePlaneDiscoveryProvider,
    PlainMailbox,
    PlainMatcher,
)


def _serve(provider):
    server = serve_enclave_plane(provider, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_server_serves_healthz_and_empty_match():
    provider = PlainEnclavePlaneDiscoveryProvider(
        PlainMatcher([], top_k=3), PlainMailbox()
    )
    server = _serve(provider)
    try:
        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
            health = json.loads(response.read())
        assert health["ok"] is True

        client = PlainEnclavePlaneHttpClient(f"http://127.0.0.1:{port}")
        result = client.discover(
            DiscoveryRequest(
                RouteIntent(prompt="hello", requested_expertise="anything"),
                mode=PLAIN_MATCHER_V1,
            )
        )
        assert result.mode == PLAIN_MATCHER_V1
        assert result.candidates == ()
        assert result.private_query_used is False
    finally:
        server.shutdown()
