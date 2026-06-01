"""Tests for the client-side enclave attestation gate.

These exercise the policy + fail-closed + bootstrap-once logic with a stub
verifier and a fake inner client. The cryptographic verification itself
(``runcard check``) is runcards' job and is not unit-tested here.
"""

import pytest

from por.enclave_attest import (
    AttestedEnclavePlaneClient,
    EnclaveAttestationError,
    EnclaveTrustPolicy,
    SubprocessRuncardVerifier,
    VerifiedAttestation,
)


APPROVED_X = "a" * 96  # sha384-ish hex


def _att(value_x=APPROVED_X, platform="nitro", status="recommended"):
    return VerifiedAttestation(
        value_x=value_x,
        platform=platform,
        tls_spki_hash="b" * 64,
        registry_status=status,
        receipt_url="https://enclave.example/.well-known/runcard/receipt",
    )


class StubVerifier:
    """Returns a fixed attestation or raises; counts how often it is called."""

    def __init__(self, result=None, *, error=None):
        self._result = result
        self._error = error
        self.calls = 0

    def verify(self, base_url):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


class FakeInner:
    """Minimal enclave-plane client that records whether it was reached."""

    def __init__(self):
        self.base_url = "https://enclave.example"
        self.mailbox_delivery_enabled = True
        self.discover_calls = 0
        self.deliver_calls = 0

    def discover(self, request):
        self.discover_calls += 1
        return f"discovered:{request}"

    def routing_kem_pk_hex(self, handle):
        return "00"

    def relay_path_for_handle(self, handle):
        return ("relay-1",)

    def deliver_to_handle(self, handle, datagram, *, timeout):
        self.deliver_calls += 1
        return iter([b"packet"])


def _policy(approved=(APPROVED_X,)):
    return EnclaveTrustPolicy(approved_value_x=frozenset(approved))


# --- policy.evaluate ---------------------------------------------------------

def test_policy_accepts_approved_attestation():
    _policy().evaluate(_att())  # no raise


def test_policy_rejects_empty_approved_set_fails_closed():
    with pytest.raises(EnclaveAttestationError, match="no approved Value X"):
        EnclaveTrustPolicy(approved_value_x=frozenset()).evaluate(_att())


def test_policy_rejects_unknown_value_x():
    with pytest.raises(EnclaveAttestationError, match="not in approved set"):
        _policy().evaluate(_att(value_x="c" * 96))


def test_policy_rejects_unaccepted_platform():
    with pytest.raises(EnclaveAttestationError, match="platform not accepted"):
        _policy().evaluate(_att(platform="sgx"))


def test_policy_rejects_bad_registry_status():
    with pytest.raises(EnclaveAttestationError, match="registry status not accepted"):
        _policy().evaluate(_att(status="revoked"))


# --- AttestedEnclavePlaneClient ---------------------------------------------

def test_client_proceeds_to_inner_when_attested():
    inner = FakeInner()
    client = AttestedEnclavePlaneClient(
        inner, verifier=StubVerifier(_att()), policy=_policy()
    )
    assert client.discover("req") == "discovered:req"
    assert inner.discover_calls == 1
    assert client.attestation.platform == "nitro"
    assert client.pinned_spki == "b" * 64


def test_client_fails_closed_on_crypto_failure():
    inner = FakeInner()
    verifier = StubVerifier(error=EnclaveAttestationError("runcard check failed"))
    client = AttestedEnclavePlaneClient(inner, verifier=verifier, policy=_policy())
    with pytest.raises(EnclaveAttestationError, match="runcard check failed"):
        client.discover("req")
    assert inner.discover_calls == 0  # inner never reached


def test_client_fails_closed_on_policy_failure():
    inner = FakeInner()
    client = AttestedEnclavePlaneClient(
        inner, verifier=StubVerifier(_att(value_x="d" * 96)), policy=_policy()
    )
    with pytest.raises(EnclaveAttestationError, match="not in approved set"):
        client.deliver_to_handle("h", b"x", timeout=1.0)
    assert inner.deliver_calls == 0  # no unattested delivery


def test_client_bootstrap_once_caches_attestation():
    inner = FakeInner()
    verifier = StubVerifier(_att())
    client = AttestedEnclavePlaneClient(inner, verifier=verifier, policy=_policy())
    client.discover("a")
    client.discover("b")
    list(client.deliver_to_handle("h", b"x", timeout=1.0))
    assert verifier.calls == 1  # verified once, then cheap
    assert inner.discover_calls == 2


def test_client_does_not_downgrade_after_failure():
    inner = FakeInner()
    verifier = StubVerifier(error=EnclaveAttestationError("nope"))
    client = AttestedEnclavePlaneClient(inner, verifier=verifier, policy=_policy())
    for _ in range(3):
        with pytest.raises(EnclaveAttestationError):
            client.discover("req")
    assert inner.discover_calls == 0


def test_mailbox_delivery_enabled_passthrough():
    inner = FakeInner()
    client = AttestedEnclavePlaneClient(
        inner, verifier=StubVerifier(_att()), policy=_policy()
    )
    assert client.mailbox_delivery_enabled is True
    assert client.base_url == "https://enclave.example"


# --- SubprocessRuncardVerifier receipt parsing (no subprocess) ---------------

def test_receipt_fields_parses_expected_shape():
    att = SubprocessRuncardVerifier._receipt_fields(
        {
            "value_x": APPROVED_X,
            "platform": "tdx",
            "tls_spki_hash": "ff",
            "registry_status": "recommended",
        },
        "https://e/.well-known/runcard/receipt",
    )
    assert att.platform == "tdx"
    assert att.value_x == APPROVED_X


def test_receipt_fields_missing_value_x_fails_closed():
    with pytest.raises(EnclaveAttestationError, match="missing required field"):
        SubprocessRuncardVerifier._receipt_fields({"platform": "tdx"}, "u")


def test_receipt_fields_non_object_fails_closed():
    with pytest.raises(EnclaveAttestationError, match="must be a JSON object"):
        SubprocessRuncardVerifier._receipt_fields(["not", "a", "dict"], "u")
