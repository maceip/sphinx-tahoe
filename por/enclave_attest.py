"""Client-side attestation gate for the enclave plane.

This is the sphinx-tahoe side of the TEE hardening (docs/matcher_threat_model.md).
The wire shape from ``enclave_plane.py`` stays unchanged; this module decides
*whether to trust* an enclave-plane endpoint before any matcher/mailbox call is
issued.

Trust model (runcards LLM_ATTESTED.md / DESIGN.md): "bootstrap once, then cheap".
A client verifies the enclave's attested-TLS receipt once, binds it to the TLS
channel, caches it, then trusts subsequent cheap calls.

Division of labour — we do NOT reimplement quote verification (runcards'
invariant: "do not modify the core quote verifier"). The cryptographic checks
(quote signature chain, ``report_data`` binding, ``sha256(cert_spki) ==
eat.tls_spki_hash`` channel binding, Value X registry lookup) are delegated to
runcards' own verifier via ``runcard check <url>`` (src/main.rs ``cmd_check``).
What lives here is the policy sphinx-tahoe owns: which Value X builds we accept,
which TEE platforms we accept, and **fail-closed** enforcement — the client never
silently downgrades to an unattested transport (invariant I1: security level is a
network property, not a per-call toggle).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, runtime_checkable
from urllib.request import urlopen


RUNCARD_RECEIPT_PATH = "/.well-known/runcard/receipt"
ACCEPTED_TEE_PLATFORMS = frozenset({"nitro", "sev-snp", "tdx"})
DEFAULT_ACCEPTED_REGISTRY_STATUS = frozenset({"recommended"})


class EnclaveAttestationError(RuntimeError):
    """The enclave plane could not be trusted.

    Raising this is the fail-closed path: callers must not fall back to an
    unattested transport in response.
    """


@dataclass(frozen=True)
class VerifiedAttestation:
    """A receipt whose cryptographic checks have already passed (in runcards).

    The fields here are what sphinx-tahoe *policy* reasons about. The crypto that
    proves they are authentic (quote chain + channel binding) happened in the
    verifier before this object was constructed.
    """

    value_x: str
    platform: str
    tls_spki_hash: str
    registry_status: str = "unknown"
    receipt_url: str = ""


@dataclass(frozen=True)
class EnclaveTrustPolicy:
    """sphinx-tahoe-owned acceptance policy over a verified attestation."""

    approved_value_x: frozenset[str]
    accepted_platforms: frozenset[str] = ACCEPTED_TEE_PLATFORMS
    accepted_registry_status: frozenset[str] = DEFAULT_ACCEPTED_REGISTRY_STATUS

    def evaluate(self, att: VerifiedAttestation) -> None:
        """Raise ``EnclaveAttestationError`` unless the attestation is acceptable.

        Fail closed: an empty ``approved_value_x`` rejects everything, so a
        misconfigured deployment does not silently trust an arbitrary enclave.
        """
        if not self.approved_value_x:
            raise EnclaveAttestationError(
                "no approved Value X configured; refusing to trust any enclave"
            )
        if att.platform not in self.accepted_platforms:
            raise EnclaveAttestationError(
                f"tee platform not accepted: {att.platform!r} "
                f"(accepted: {sorted(self.accepted_platforms)})"
            )
        if att.value_x not in self.approved_value_x:
            raise EnclaveAttestationError(
                f"enclave Value X not in approved set: {att.value_x}"
            )
        if att.registry_status not in self.accepted_registry_status:
            raise EnclaveAttestationError(
                f"registry status not accepted: {att.registry_status!r} "
                f"(accepted: {sorted(self.accepted_registry_status)})"
            )


@runtime_checkable
class RuncardVerifier(Protocol):
    """Adapter that performs runcards' cryptographic verification of an endpoint.

    Implementations MUST raise ``EnclaveAttestationError`` on any verification
    failure and only return a ``VerifiedAttestation`` when the quote chain and
    channel binding have passed.
    """

    def verify(self, base_url: str) -> VerifiedAttestation: ...


@dataclass
class SubprocessRuncardVerifier:
    """Real verifier: delegates crypto to the ``runcard`` binary.

    INTEGRATION SEAM (exercised only against a built ``runcard`` binary + a live
    attested enclave; not unit-tested here). ``runcard check <url>`` performs the
    full chain: quote signature verification, ``report_data`` binding,
    ``sha256(cert_spki) == eat.tls_spki_hash`` channel binding, and Value X
    registry lookup (src/main.rs ``cmd_check``). A zero exit code means all of
    that passed. We then read the published receipt for the fields policy needs.

    The receipt JSON schema is parsed defensively: if the published shape differs
    from the keys below, this raises rather than guessing (fail closed). Adjust
    ``_receipt_fields`` against a real ``/.well-known/runcard/receipt`` payload.
    """

    runcard_bin: str = "runcard"
    timeout: float = 30.0

    def verify(self, base_url: str) -> VerifiedAttestation:
        url = base_url.rstrip("/")
        proc = subprocess.run(
            [self.runcard_bin, "check", url],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or f"exit {proc.returncode}"
            raise EnclaveAttestationError(f"runcard check failed for {url}: {detail}")
        # Crypto (quote chain + channel binding + registry lookup) passed.
        receipt_url = url + RUNCARD_RECEIPT_PATH
        try:
            with urlopen(receipt_url, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - any fetch/parse failure fails closed
            raise EnclaveAttestationError(
                f"runcard check passed but receipt fetch/parse failed: {exc}"
            ) from exc
        return self._receipt_fields(raw, receipt_url)

    @staticmethod
    def _receipt_fields(raw: object, receipt_url: str) -> VerifiedAttestation:
        if not isinstance(raw, dict):
            raise EnclaveAttestationError("runcard receipt must be a JSON object")
        try:
            return VerifiedAttestation(
                value_x=str(raw["value_x"]),
                platform=str(raw["platform"]),
                tls_spki_hash=str(raw.get("tls_spki_hash", "")),
                registry_status=str(raw.get("registry_status", "unknown")),
                receipt_url=receipt_url,
            )
        except KeyError as exc:
            raise EnclaveAttestationError(
                f"runcard receipt missing required field: {exc}"
            ) from exc


class AttestedEnclavePlaneClient:
    """Wraps an enclave-plane client and gates every call on attestation.

    The inner client is any object exposing the enclave-plane interface
    (``discover``, ``routing_kem_pk_hex``, ``relay_path_for_handle``,
    ``deliver_to_handle``, ``mailbox_delivery_enabled``, ``base_url``). On first
    use it verifies the endpoint once (bootstrap-once) and caches the result; if
    verification or policy fails it raises and **never** calls the inner client.
    """

    def __init__(
        self,
        inner: object,
        *,
        verifier: RuncardVerifier,
        policy: EnclaveTrustPolicy,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._inner = inner
        self._verifier = verifier
        self._policy = policy
        self._log = log or (lambda _message: None)
        self._attestation: VerifiedAttestation | None = None

    @property
    def base_url(self) -> str:
        return self._inner.base_url

    @property
    def mailbox_delivery_enabled(self) -> bool:
        return bool(getattr(self._inner, "mailbox_delivery_enabled", False))

    @property
    def attestation(self) -> VerifiedAttestation | None:
        return self._attestation

    @property
    def pinned_spki(self) -> str | None:
        """SPKI hash bound by the verified receipt.

        Channel binding to the TLS connection is enforced inside ``runcard
        check``. Once the enclave-plane transport is real TLS (not the plain HTTP
        stand-in), subsequent connections should also pin this value; that
        enforcement is the remaining hardening item for this box.
        """
        return self._attestation.tls_spki_hash if self._attestation else None

    def establish(self) -> VerifiedAttestation:
        """Verify + apply policy once. Idempotent (bootstrap-once)."""
        if self._attestation is not None:
            return self._attestation
        att = self._verifier.verify(self._inner.base_url)
        self._policy.evaluate(att)
        self._attestation = att
        self._log(
            "client event=enclave_attested "
            f"platform={att.platform} value_x={att.value_x[:16]} "
            f"status={att.registry_status}"
        )
        return att

    def _ensure(self) -> None:
        if self._attestation is not None:
            return
        try:
            self.establish()
        except EnclaveAttestationError as exc:
            self._log(f"client event=enclave_attestation_rejected reason={exc}")
            raise

    def discover(self, request):
        self._ensure()
        return self._inner.discover(request)

    def routing_kem_pk_hex(self, handle: str):
        self._ensure()
        return self._inner.routing_kem_pk_hex(handle)

    def relay_path_for_handle(self, handle: str) -> tuple[str, ...]:
        self._ensure()
        return self._inner.relay_path_for_handle(handle)

    def deliver_to_handle(self, handle: str, datagram: bytes, *, timeout: float) -> Iterable[bytes]:
        self._ensure()
        return self._inner.deliver_to_handle(handle, datagram, timeout=timeout)
