"""QUIC-based runtime for production P-OR daemons.

Wraps WireNodeRuntime's binary dispatch over QUIC DATAGRAM frames
(RFC 9221). TLS 1.3 is mandatory — all P-OR wire traffic is encrypted.

The QUIC server receives datagrams, dispatches through the same demux
as UDP (REACH → Outfox → opaque), and sends responses back through
the QUIC connection. Forward hops to next relays use the UDP send path
for now (QUIC client-to-relay connections are a future optimization).
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
from pathlib import Path

from .quic_transport import (
    AIOQUIC_AVAILABLE,
    QuicDatagramServer,
    QuicEndpoint,
    InMemorySessionTicketStore,
    make_server_config,
    write_localhost_self_signed_cert,
    POR_QUIC_ALPN,
)
from .wire_frame import decode_datagram, encode_forward


def serve_quic_forever(
    runtime,
    *,
    certfile: str | Path | None = None,
    keyfile: str | Path | None = None,
    dev_localhost: bool = False,
) -> int:
    """Run a WireNodeRuntime over QUIC datagrams with TLS. Blocking.

    Replaces serve_forever() for QUIC transport. Same demux, same
    handlers, but incoming datagrams arrive via QUIC with TLS 1.3
    instead of raw UDP.

    Responses to clients are pushed back through the QUIC connection.
    Forward hops to next relays still use UDP sendto (relay-to-relay
    QUIC is a future optimization — TLS on the ingress is the security
    boundary that matters now).
    """
    if not AIOQUIC_AVAILABLE:
        raise RuntimeError("aioquic is required for QUIC runtime")

    return asyncio.run(_serve_quic_async(
        runtime, certfile=certfile, keyfile=keyfile, dev_localhost=dev_localhost))


async def _serve_quic_async(runtime, *, certfile, keyfile, dev_localhost):
    if certfile is None or keyfile is None:
        if not dev_localhost:
            raise ValueError(
                "certfile and keyfile are required for production. "
                "Use dev_localhost=True for local testing with self-signed certs."
            )
        tmpdir = tempfile.mkdtemp(prefix="por-quic-cert-")
        certfile, keyfile = write_localhost_self_signed_cert(
            Path(tmpdir) / "cert.pem", Path(tmpdir) / "key.pem")

    endpoint = QuicEndpoint(runtime.identity.host, runtime.identity.port)
    config = make_server_config(
        certfile, keyfile,
        alpn=POR_QUIC_ALPN,
        max_datagram_frame_size=runtime.params.payload_size + 512,
    )

    # The QUIC handler dispatches through the runtime's binary handlers.
    # For forward packets, the runtime sends to next hop via UDP (sock).
    # For circuit packets going back to the client, the handler returns
    # the response datagram which the QUIC protocol sends back on the
    # same connection.
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _handler(data: bytes) -> bytes | None:
        from .reach_wire import is_reach_datagram

        if is_reach_datagram(data):
            if runtime.on_reach_control is not None:
                runtime.on_reach_control(data, (endpoint.host, endpoint.port))
            return None

        kind, a, b = decode_datagram(data, runtime.params.payload_size)
        if kind == "shutdown":
            runtime._shutdown = True
            return None
        if kind == "forward":
            runtime._handle_forward_binary(udp_sock, a, b,
                                            src_addr=(endpoint.host, endpoint.port))
            return None
        if kind == "circuit":
            runtime._handle_circuit_binary(udp_sock, a,
                                            src_addr=(endpoint.host, endpoint.port))
            return None
        return None

    tickets = InMemorySessionTicketStore()
    server = QuicDatagramServer(
        endpoint,
        configuration=config,
        datagram_handler=_handler,
        session_ticket_store=tickets,
    )
    await server.start()
    runtime._log("started", fields={
        "wire": "quic",
        "tls": "enabled",
        "addr": f"{endpoint.host}:{endpoint.port}",
    })

    try:
        while not runtime._shutdown:
            await asyncio.sleep(0.1)
    finally:
        udp_sock.close()
        server.close()
        runtime._log("stopped", fields={"wire": "quic"})

    return 0
