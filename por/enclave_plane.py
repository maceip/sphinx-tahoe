"""Plain HTTP enclave-plane endpoint for matcher/mailbox plumbing.

The committed architecture hardens this box later. This module only provides
the stable wire shape: match over an enclave-plane endpoint, return opaque
handles, and deliver sealed packets through the mailbox path.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler
from typing import Callable, Iterable
from urllib.request import Request, urlopen

from .arc import NoopArcCredential, noop_arc_credential_from_dict
from .attested_transport import EnclaveAttestationError, build_pinned_opener
from .directory import DiscoveryRequest, DiscoveryResult
from .expert_route import PeerCandidate, PeerObservation, RouteIntent
from .memory_index import MemoryManifest


DEFAULT_ENCLAVE_PLANE_TIMEOUT_SECONDS = 8.0


class PlainEnclavePlaneHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = DEFAULT_ENCLAVE_PLANE_TIMEOUT_SECONDS,
        arc_credential: NoopArcCredential | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.mailbox_delivery_enabled = True
        self.arc_credential = arc_credential or NoopArcCredential.issue()
        self._opener = None
        self.tls_pin: str | None = None

    def set_tls_pin(self, spki_hex: str) -> None:
        """Pin every subsequent connection's TLS SPKI to ``spki_hex`` (H3).

        Called by ``AttestedEnclavePlaneClient`` after attestation. Pinning is
        only meaningful over TLS; refuse (fail closed) to pin a plaintext
        ``http://`` transport rather than give a false sense of protection.
        """
        if not self.base_url.lower().startswith("https://"):
            raise EnclaveAttestationError(
                f"cannot pin SPKI on a non-TLS transport: {self.base_url}"
            )
        self.tls_pin = spki_hex
        self._opener = build_pinned_opener(spki_hex)

    def _open(self, req, *, timeout: float):
        if self._opener is not None:
            return self._opener.open(req, timeout=timeout)
        return urlopen(req, timeout=timeout)

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        raw = self._post_json(
            "/v1/match",
            {
                "mode": request.mode,
                "max_records": request.max_records,
                "intent": asdict(request.intent),
            },
        )
        return _discovery_result_from_dict(raw)

    def routing_kem_pk_hex(self, handle: str) -> str | None:
        raw = self._post_json("/v1/routing-key", {"handle": handle})
        value = raw.get("routing_kem_pk_hex")
        return str(value) if value else None

    def relay_path_for_handle(self, handle: str) -> tuple[str, ...]:
        raw = self._post_json("/v1/relay-path", {"handle": handle})
        return tuple(str(item) for item in raw.get("relay_path", ()))

    def deliver_to_handle(
        self,
        handle: str,
        datagram: bytes,
        *,
        timeout: float,
    ) -> Iterable[bytes]:
        body = json.dumps(
            {
                "handle": handle,
                "timeout": timeout,
                "datagram_b64": base64.b64encode(datagram).decode("ascii"),
                "arc_credential": self.arc_credential.to_public_dict(),
            }
        ).encode("utf-8")
        req = Request(
            self.base_url + "/v1/deliver",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )

        def packets() -> Iterable[bytes]:
            with self._open(req, timeout=timeout + 1.0) as response:
                for line in response:
                    if not line.startswith(b"data: "):
                        continue
                    yield base64.b64decode(line[6:].strip())

        return packets()

    def _post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
        body = {**body, "arc_credential": self.arc_credential.to_public_dict()}
        req = Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with self._open(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def make_plain_enclave_plane_handler(provider) -> Callable[..., BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "por-plain-enclave-plane/0.1"

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._send_json({"ok": True, "schema": "por.plain_enclave_plane.health.v1"})
                return
            self.send_error(404)

        def do_POST(self) -> None:
            try:
                raw = self._read_json()
                noop_arc_credential_from_dict(_dict_field(raw, "arc_credential"))
                if self.path == "/v1/match":
                    request = DiscoveryRequest(
                        intent=RouteIntent(**dict(raw["intent"])),
                        mode=str(raw["mode"]),
                        max_records=raw.get("max_records"),
                    )
                    self._send_json(_discovery_result_to_dict(provider.discover(request)))
                    return
                if self.path == "/v1/routing-key":
                    handle = str(raw["handle"])
                    self._send_json({"routing_kem_pk_hex": provider.routing_kem_pk_hex(handle)})
                    return
                if self.path == "/v1/relay-path":
                    handle = str(raw["handle"])
                    self._send_json({"relay_path": list(provider.relay_path_for_handle(handle))})
                    return
                if self.path == "/v1/deliver":
                    self._stream_delivery(raw)
                    return
            except (KeyError, TypeError, ValueError) as exc:
                self.send_error(400, str(exc))
                return
            self.send_error(404)

        def _stream_delivery(self, raw: dict[str, object]) -> None:
            handle = str(raw["handle"])
            timeout = float(raw.get("timeout", DEFAULT_ENCLAVE_PLANE_TIMEOUT_SECONDS))
            datagram = base64.b64decode(str(raw["datagram_b64"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            for packet in provider.deliver_to_handle(handle, datagram, timeout=timeout):
                line = b"data: " + base64.b64encode(packet) + b"\n\n"
                try:
                    self.wfile.write(line)
                    self.wfile.flush()
                except BrokenPipeError:
                    break

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("request body must be an object")
            return raw

        def _send_json(self, body: dict[str, object]) -> None:
            data = json.dumps(body, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format, *_args) -> None:
            return

    return Handler


def _discovery_result_to_dict(result: DiscoveryResult) -> dict[str, object]:
    return {
        "candidates": [_candidate_to_dict(candidate) for candidate in result.candidates],
        "mode": result.mode,
        "snapshot_size": result.snapshot_size,
        "exact_query_sent": result.exact_query_sent,
        "private_query_used": result.private_query_used,
        "generated_at": result.generated_at,
        "note": result.note,
    }


def _discovery_result_from_dict(raw: dict[str, object]) -> DiscoveryResult:
    return DiscoveryResult(
        candidates=tuple(
            _candidate_from_dict(item)
            for item in raw.get("candidates", ())
            if isinstance(item, dict)
        ),
        mode=str(raw["mode"]),
        snapshot_size=int(raw["snapshot_size"]),
        exact_query_sent=bool(raw["exact_query_sent"]),
        private_query_used=bool(raw["private_query_used"]),
        generated_at=str(raw["generated_at"]),
        note=str(raw["note"]),
    )


def _candidate_to_dict(candidate: PeerCandidate) -> dict[str, object]:
    return {
        "manifest": json.loads(candidate.manifest.to_json()),
        "observation": (
            asdict(candidate.observation)
            if candidate.observation is not None
            else None
        ),
    }


def _candidate_from_dict(raw: dict[str, object]) -> PeerCandidate:
    manifest_raw = raw["manifest"]
    if not isinstance(manifest_raw, dict):
        raise ValueError("candidate manifest must be an object")
    observation_raw = raw.get("observation")
    observation = None
    if isinstance(observation_raw, dict):
        observation = PeerObservation(**observation_raw)
    return PeerCandidate(
        MemoryManifest.from_json(json.dumps(manifest_raw)),
        observation,
    )


def _dict_field(raw: dict[str, object], key: str) -> dict[str, object]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value
