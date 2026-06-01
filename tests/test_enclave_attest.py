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


def test_policy_does_not_enforce_registry_status_by_default():
    _policy().evaluate(_att(status="unknown"))  # opt-in signal; no raise


def test_policy_rejects_bad_registry_status_when_configured():
    policy = EnclaveTrustPolicy(
        approved_value_x=frozenset((APPROVED_X,)),
        accepted_registry_status=frozenset({"recommended"}),
    )
    with pytest.raises(EnclaveAttestationError, match="registry status not accepted"):
        policy.evaluate(_att(status="revoked"))


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


# --- SubprocessRuncardVerifier: parsing the real `runcard check` output ------

# Sample stderr matching runcards src/main.rs cmd_check output format.
_CHECK_STDERR = """[runcard] === attested-TLS check ===
[runcard] Target: matcher.example:443
[runcard] Leaf cert: 812 bytes DER
[runcard] EAT extension: 1203 bytes
[runcard] EAT profile: https://bountynet.dev/eat/v2
[runcard] Platform:    Some(Tdx)
[runcard] Value X:     {vx}
[runcard] SPKI binding:    PASS
[runcard] Quote binding:   PASS
[runcard] Quote signature: PASS
[runcard] Chain:           leaf only (no previous stage)
[runcard] CT (SCTs):       none in cert (self-signed path)
""".format(vx=APPROVED_X)


def test_parse_check_output_extracts_value_x_and_platform():
    att = SubprocessRuncardVerifier._parse_check_output(_CHECK_STDERR, "https://matcher.example")
    assert att.value_x == APPROVED_X
    assert att.platform == "tdx"
    assert att.registry_status == "unknown"


def test_parse_check_output_missing_fields_fails_closed():
    with pytest.raises(EnclaveAttestationError, match="could not be parsed"):
        SubprocessRuncardVerifier._parse_check_output("[runcard] nothing useful\n", "u")


@pytest.mark.parametrize(
    "raw,expected",
    [("Some(Tdx)", "tdx"), ("Some(Nitro)", "nitro"), ("Some(SevSnp)", "sev-snp"), ("Tdx", "tdx")],
)
def test_normalize_platform(raw, expected):
    assert SubprocessRuncardVerifier._normalize_platform(raw) == expected


def test_normalize_platform_rejects_unknown():
    with pytest.raises(EnclaveAttestationError, match="unrecognized runcard platform"):
        SubprocessRuncardVerifier._normalize_platform("Some(Sgx)")


def test_verify_missing_binary_fails_closed():
    verifier = SubprocessRuncardVerifier(runcard_bin="definitely-not-a-real-runcard-xyz")
    with pytest.raises(EnclaveAttestationError, match="could not run"):
        verifier.verify("https://matcher.example")


def test_verify_nonzero_exit_fails_closed(monkeypatch):
    import subprocess as sp

    monkeypatch.setattr(
        sp,
        "run",
        lambda *a, **k: sp.CompletedProcess([], 1, stdout="", stderr="channel binding failed"),
    )
    with pytest.raises(EnclaveAttestationError, match="channel binding failed"):
        SubprocessRuncardVerifier().verify("https://matcher.example")


def test_verify_success_flow_returns_attestation(monkeypatch):
    import subprocess as sp

    monkeypatch.setattr(
        sp,
        "run",
        lambda *a, **k: sp.CompletedProcess([], 0, stdout="", stderr=_CHECK_STDERR),
    )
    att = SubprocessRuncardVerifier().verify("https://matcher.example")
    assert att.value_x == APPROVED_X
    assert att.platform == "tdx"
