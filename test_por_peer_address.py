import pytest

from por.peer_address import (
    ROUTE_DIRECT,
    ROUTE_RELAY,
    TRANSPORT_H3_WEBSOCKET,
    TRANSPORT_QUIC_DATAGRAM,
    AddressExposurePolicy,
    PeerAddressRelay,
    UdpEndpoint,
    build_dial_plan,
)


def _assist():
    return PeerAddressRelay(
        relay_id="relay-a",
        relay_endpoint=UdpEndpoint("203.0.113.10", 4433),
        secret=b"peer-address-test-secret",
    )


def test_registration_confirm_publishes_relay_first_address_record():
    assist = _assist()
    challenge = assist.request_registration(
        peer_id="expert-art",
        observed_endpoint=UdpEndpoint("198.51.100.20", 50000),
        now=100.0,
    )

    record = assist.confirm_registration(
        challenge,
        supported_transports=(TRANSPORT_QUIC_DATAGRAM, TRANSPORT_H3_WEBSOCKET),
        now=101.0,
    )

    assert record.peer_id == "expert-art"
    assert record.relay_candidates[0].relay_id == "relay-a"
    assert record.relay_candidates[0].inline_required is True
    assert record.observed_udp_endpoints == ()
    assert record.signature

    plan = build_dial_plan(record, allow_direct=True, now=102.0)
    assert plan.contactable is True
    assert plan.primary.kind == ROUTE_RELAY
    assert plan.primary.endpoint == UdpEndpoint("203.0.113.10", 4433)
    assert plan.fallbacks == ()


def test_direct_endpoint_is_policy_gated_and_never_required():
    assist = _assist()
    challenge = assist.request_registration(
        peer_id="expert-art",
        observed_endpoint=UdpEndpoint("198.51.100.20", 50000),
        now=200.0,
    )
    record = assist.confirm_registration(
        challenge,
        address_policy=AddressExposurePolicy(expose_direct_endpoint=True, stable_relay_only=False),
        now=201.0,
    )

    relay_only = build_dial_plan(record, allow_direct=False, now=202.0)
    assert relay_only.primary.kind == ROUTE_RELAY
    assert relay_only.fallbacks == ()

    relay_first = build_dial_plan(record, allow_direct=True, now=202.0)
    assert relay_first.primary.kind == ROUTE_RELAY
    assert relay_first.fallbacks[0].kind == ROUTE_DIRECT
    assert relay_first.fallbacks[0].endpoint == UdpEndpoint("198.51.100.20", 50000)

    direct_first = build_dial_plan(
        record,
        allow_direct=True,
        prefer_direct=True,
        now=202.0,
    )
    assert direct_first.primary.kind == ROUTE_DIRECT
    assert direct_first.fallbacks[0].kind == ROUTE_RELAY


def test_bad_cookie_is_rejected():
    assist = _assist()
    challenge = assist.request_registration(
        peer_id="expert-art",
        observed_endpoint=UdpEndpoint("198.51.100.20", 50000),
        now=300.0,
    )
    tampered = challenge.__class__(
        **{**challenge.__dict__, "cookie": b"\x00" * len(challenge.cookie)}
    )

    with pytest.raises(ValueError, match="invalid peer address challenge cookie"):
        assist.confirm_registration(tampered, now=301.0)


def test_heartbeat_refreshes_ttl_and_can_learn_observed_endpoint():
    assist = _assist()
    challenge = assist.request_registration(
        peer_id="expert-art",
        observed_endpoint=UdpEndpoint("198.51.100.20", 50000),
        now=400.0,
    )
    record = assist.confirm_registration(
        challenge,
        address_policy=AddressExposurePolicy(expose_direct_endpoint=True, stable_relay_only=False),
        now=401.0,
    )

    refreshed = assist.heartbeat(
        "expert-art",
        observed_endpoint=UdpEndpoint("198.51.100.21", 50010),
        now=500.0,
    )

    assert refreshed is not None
    assert refreshed.expires_at > record.expires_at
    assert refreshed.observed_udp_endpoints == (UdpEndpoint("198.51.100.21", 50010),)


def test_expired_address_record_is_not_contactable_and_purges():
    assist = _assist()
    challenge = assist.request_registration(
        peer_id="expert-art",
        observed_endpoint=UdpEndpoint("198.51.100.20", 50000),
        now=600.0,
    )
    record = assist.confirm_registration(challenge, now=601.0)

    expired_plan = build_dial_plan(record, now=1000.0)
    assert expired_plan.contactable is False
    assert "expired" in expired_plan.warnings[0]

    assert assist.address_record("expert-art", now=1000.0) is None
    assert assist.purge_expired(now=1000.0) == 0
