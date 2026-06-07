"""Tests for dynamic reachability assist selection (Item 7)."""

from __future__ import annotations

import time
from types import SimpleNamespace

from nacl.signing import SigningKey

from tenet.mixnet.control.descriptors import HandleAddressRecord, ReachabilityAssistDescriptor
from tenet.mixnet.control.records import sign_control_record
from tenet.mixnet.control.service import MixnetControlService
from tenet.experts.reachability_resolver import (
    ReachabilityPolicy,
    RouteHealthCache,
    resolve_reachability_for_handle,
)

HANDLE = "h" + "0123456789abcde"
NET = "net"


def _service():
    sk = SigningKey.generate()
    return MixnetControlService(network_id=NET, verify_keys={"root": sk.verify_key.encode().hex()}), sk


def _put(svc, sk, unsigned, *, now=None):
    svc.put_signed(sign_control_record(unsigned, signing_key_hex=sk.encode().hex(), key_id="root"), now=now)


def _publish_handle(svc, sk, *, assist_refs=(), direct_allowed=False, now=None, ttl=3600.0):
    issued = time.time() if now is None else now
    record = HandleAddressRecord(
        handle=HANDLE, route_candidates=tuple(assist_refs) or (("assist/x",) if not direct_allowed else ()),
        assist_refs=tuple(assist_refs), direct_allowed=direct_allowed,
        issued_at=issued, expires_at=issued + ttl, signer="root",
    )
    _put(svc, sk, svc.make_unsigned_handle_address(record, seq=1, now=now), now=now)


def _publish_assist(svc, sk, assist_id, *, now=None):
    assist = ReachabilityAssistDescriptor(assist_id=assist_id, provider_node_id="n-" + assist_id, policy="nat-relay")
    _put(svc, sk, svc.make_unsigned_reachability_assist(assist, seq=1, now=now), now=now)


def _relay(relay_id):
    return SimpleNamespace(relay_id=relay_id)


def _policy(**kw):
    return ReachabilityPolicy(**kw)


# --------------------------------------------------------------------------- #


def test_no_static_relay_but_discovered_assist_succeeds():
    svc, sk = _service()
    _publish_handle(svc, sk, assist_refs=("a1",))
    _publish_assist(svc, sk, "a1")
    sel = resolve_reachability_for_handle(HANDLE, svc, (), _policy(trusted_assist_ids=frozenset({"a1"})))
    assert sel.ok
    assert sel.route_kind == "assist"
    assert sel.assist_id == "a1"
    assert sel.handle_live_state == "live"


def test_stale_handle_address_rejected():
    svc, sk = _service()
    _publish_handle(svc, sk, assist_refs=("a1",), now=1000.0, ttl=100.0)
    _publish_assist(svc, sk, "a1", now=1000.0)
    sel = resolve_reachability_for_handle(
        HANDLE, svc, (), _policy(trusted_assist_ids=frozenset({"a1"})), now=2000.0
    )
    assert sel.ok is False
    assert "no_signed_handle_address" in (sel.fallback_reason or "")


def test_assist_trusted_but_not_live_retries_next():
    svc, sk = _service()
    _publish_handle(svc, sk, assist_refs=("a1", "a2"))
    _publish_assist(svc, sk, "a1")
    _publish_assist(svc, sk, "a2")
    # a1 has no live mapping, a2 does
    probe = lambda assist_id, handle: assist_id == "a2"
    sel = resolve_reachability_for_handle(
        HANDLE, svc, (), _policy(trusted_assist_ids=frozenset({"a1", "a2"})), live_probe=probe
    )
    assert sel.ok
    assert sel.assist_id == "a2"
    assert any(r.reason == "assist_no_live_mapping" and r.key == "a1" for r in sel.rejected)


def test_malicious_assist_rejected():
    svc, sk = _service()
    _publish_handle(svc, sk, assist_refs=("evil",))
    _publish_assist(svc, sk, "evil")  # signed, but not in the client's trusted set
    sel = resolve_reachability_for_handle(
        HANDLE, svc, (), _policy(trusted_assist_ids=frozenset({"a1"}))
    )
    assert sel.ok is False
    assert any(r.reason == "assist_untrusted" and r.key == "evil" for r in sel.rejected)


def test_direct_route_preferred_when_policy_allows():
    svc, sk = _service()
    _publish_handle(svc, sk, assist_refs=("a1",), direct_allowed=True)
    _publish_assist(svc, sk, "a1")
    sel = resolve_reachability_for_handle(
        HANDLE, svc, (), _policy(allow_direct=True, trusted_assist_ids=frozenset({"a1"}))
    )
    assert sel.ok
    assert sel.route_kind == "direct"


def test_all_assists_fail_yields_precise_error():
    svc, sk = _service()
    _publish_handle(svc, sk, assist_refs=("a1", "a2"))
    _publish_assist(svc, sk, "a1")
    _publish_assist(svc, sk, "a2")
    probe = lambda assist_id, handle: False  # nothing live
    sel = resolve_reachability_for_handle(
        HANDLE, svc, (), _policy(trusted_assist_ids=frozenset({"a1", "a2"})), live_probe=probe
    )
    assert sel.ok is False
    assert "all_assists_no_live_mapping" in (sel.fallback_reason or "")
    assert "no_static_relay" in (sel.fallback_reason or "")
    assert sel.handle_live_state == "no_live_mapping"


def test_static_relay_is_bootstrap_fallback_not_only_path():
    svc, sk = _service()
    _publish_handle(svc, sk, assist_refs=("a1",))
    _publish_assist(svc, sk, "a1")
    # assist available -> assist preferred over the static relay
    sel = resolve_reachability_for_handle(
        HANDLE, svc, (_relay("relay1"),), _policy(trusted_assist_ids=frozenset({"a1"}))
    )
    assert sel.route_kind == "assist"

    # assist not live -> static relay used as bootstrap fallback
    sel2 = resolve_reachability_for_handle(
        HANDLE, svc, (_relay("relay1"),), _policy(trusted_assist_ids=frozenset({"a1"})),
        live_probe=lambda a, h: False,
    )
    assert sel2.ok
    assert sel2.route_kind == "static_relay"
    assert sel2.static_relay_id == "relay1"


def test_unhealthy_assist_backed_off():
    svc, sk = _service()
    _publish_handle(svc, sk, assist_refs=("a1",))
    _publish_assist(svc, sk, "a1")
    health = RouteHealthCache(fail_threshold=1)
    health.record_failure("a1")  # already unhealthy
    sel = resolve_reachability_for_handle(
        HANDLE, svc, (), _policy(trusted_assist_ids=frozenset({"a1"})), health=health
    )
    assert sel.ok is False
    assert any(r.reason == "assist_unhealthy" for r in sel.rejected)
