"""Live attested enclave client: expert-mode send via mailbox delivery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .client import ClientRunResult, run_client_once
from .config import ClusterConfig, PeerAddressConfig, TrustedReachabilityRelayConfig
from .expert_mode import ExpertModeConfig
from .live_enclave import LiveEnclaveConfig, build_attested_client
from .matcher import PLAIN_MATCHER_V1


DEFAULT_MAILBOX_CLIENT = (
    Path(__file__).resolve().parent.parent / "config" / "live-mailbox-client.json"
)


@dataclass(frozen=True)
class LiveMailboxClientConfig:
    cluster: ClusterConfig
    peer_address: PeerAddressConfig
    trusted_reachability_relays: tuple[TrustedReachabilityRelayConfig, ...]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "LiveMailboxClientConfig":
        config_path = Path(path) if path is not None else DEFAULT_MAILBOX_CLIENT
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("live mailbox client config must be a JSON object")
        cluster = ClusterConfig.from_dict(raw)
        peer_raw = raw.get("peer_address") or {}
        peer_address = PeerAddressConfig.from_dict(
            peer_raw if isinstance(peer_raw, dict) else {}
        )
        relays_raw = raw.get("trusted_reachability_relays") or ()
        if not isinstance(relays_raw, Sequence):
            raise TypeError("trusted_reachability_relays must be a sequence")
        relays = tuple(
            TrustedReachabilityRelayConfig.from_dict(item)
            for item in relays_raw
            if isinstance(item, Mapping)
        )
        return cls(
            cluster=cluster,
            peer_address=peer_address,
            trusted_reachability_relays=relays,
        )


def send_live_enclave(
    enclave_config: LiveEnclaveConfig,
    mailbox_config: LiveMailboxClientConfig,
    *,
    prompt: str,
    requested_expertise: str | None = None,
    timeout: float = 30.0,
    random_seed: int | None = 0,
) -> ClientRunResult:
    """Attest, plan, and deliver one envelope through the live enclave mailbox."""
    client = build_attested_client(enclave_config)
    client.establish()
    return run_client_once(
        cluster=mailbox_config.cluster,
        discovery_provider=client,
        prompt=prompt,
        requested_expertise=requested_expertise,
        timeout=timeout,
        expert_mode_config=ExpertModeConfig(
            discovery_mode=PLAIN_MATCHER_V1,
            min_pool_size=1,
            allow_degraded_pool=True,
            allow_public_discovery_fallback=False,
        ),
        peer_address_config=mailbox_config.peer_address,
        trusted_reachability_relays=mailbox_config.trusted_reachability_relays,
        random_seed=random_seed,
    )


def send_live_enclave_summary(
    enclave_config: LiveEnclaveConfig,
    mailbox_config: LiveMailboxClientConfig,
    *,
    prompt: str,
    requested_expertise: str | None = None,
    timeout: float = 30.0,
) -> dict[str, object]:
    client = build_attested_client(enclave_config)
    att = client.establish()
    result = run_client_once(
        cluster=mailbox_config.cluster,
        discovery_provider=client,
        prompt=prompt,
        requested_expertise=requested_expertise,
        timeout=timeout,
        expert_mode_config=ExpertModeConfig(
            discovery_mode=PLAIN_MATCHER_V1,
            min_pool_size=1,
            allow_degraded_pool=True,
            allow_public_discovery_fallback=False,
        ),
        peer_address_config=mailbox_config.peer_address,
        trusted_reachability_relays=mailbox_config.trusted_reachability_relays,
        random_seed=0,
    )
    return {
        "ok": not result.fallback_used and bool(result.response_text.strip()),
        "url": enclave_config.url,
        "prompt": prompt,
        "selected_peer_id": result.selected_peer_id,
        "fallback_used": result.fallback_used,
        "degraded_anonymity": result.degraded_anonymity,
        "response_text": result.response_text,
        "via_mailbox": "via=mailbox" in result.client_logs,
        "attestation": {
            "platform": att.platform,
            "value_x_prefix": f"{att.value_x[:16]}...",
        },
    }
