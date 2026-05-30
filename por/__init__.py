"""P-OR application-layer helpers.

The `por` package sits above `sphinxmix`. It contains product/control-plane
building blocks such as memory manifests, candidate matching, and request
envelopes. Relays should not import this package to process packets.
"""

__all__ = (
    "CandidatePool",
    "CandidateScore",
    "ChunkProof",
    "ClientRunResult",
    "ClusterConfig",
    "ClusterNodeConfig",
    "CONFIG_VERSION",
    "DaemonConfig",
    "DirectoryConfig",
    "DirectorySnapshot",
    "DirectorySnapshotFetchError",
    "DirectorySnapshotFormatError",
    "DiscoveryRequest",
    "DiscoveryProvider",
    "DiscoveryResult",
    "EndpointConfig",
    "ExpertRoutingConfig",
    "ExpertModeConfig",
    "ExpertModePreparedRequest",
    "ExpertModeTrace",
    "ExpertRoutePlan",
    "H3WebSocketClient",
    "H3WebSocketServer",
    "InMemorySessionTicketStore",
    "IndexConfig",
    "LocalMemoryIndex",
    "LoggingConfig",
    "MemoryManifest",
    "PacketConfig",
    "PeerCandidate",
    "PeerAddressConfig",
    "PeerObservation",
    "PeerEndpointConfig",
    "PeerRecord",
    "PorConfig",
    "PorLogEvent",
    "PrivateDiscoveryUnavailable",
    "PromptRequestEnvelope",
    "ProviderConfig",
    "PublicManifestDirectory",
    "QuicDatagramClient",
    "QuicDatagramServer",
    "QuicEndpoint",
    "QuicTransportUnavailable",
    "write_localhost_self_signed_cert",
    "AddressChallenge",
    "AddressExposurePolicy",
    "DialPlan",
    "DialRoute",
    "PeerAddressRecord",
    "PeerAddressRelay",
    "RelayCandidate",
    "RetrievalHit",
    "RouteIntent",
    "UdpEndpoint",
    "build_dial_plan",
    "build_memory_index",
    "emit_log_event",
    "format_log_event",
    "load_config",
    "load_directory_snapshot",
    "load_public_snapshot_directory",
    "load_records_from_snapshot_file",
    "plan_expert_route",
    "prepare_expert_mode_request",
    "run_client_once",
    "send_prepared_envelope",
    "score_manifest",
    "verify_chunk_proof",
    "write_config",
)


def __getattr__(name):
    if name in __all__:
        if name in {
            "ClientRunResult",
            "run_client_once",
            "send_prepared_envelope",
        }:
            from . import client

            return getattr(client, name)
        if name in {
            "CandidatePool",
            "CandidateScore",
            "ExpertRoutePlan",
            "PeerCandidate",
            "PeerObservation",
            "RouteIntent",
            "plan_expert_route",
        }:
            from . import expert_route

            return getattr(expert_route, name)
        if name in {
            "CONFIG_VERSION",
            "ClusterConfig",
            "ClusterNodeConfig",
            "DaemonConfig",
            "DirectoryConfig",
            "EndpointConfig",
            "ExpertRoutingConfig",
            "LoggingConfig",
            "PacketConfig",
            "PeerAddressConfig",
            "PeerEndpointConfig",
            "PorConfig",
            "ProviderConfig",
            "load_config",
            "write_config",
        }:
            from . import config

            return getattr(config, name)
        if name in {
            "DiscoveryRequest",
            "DiscoveryProvider",
            "DiscoveryResult",
            "DirectorySnapshot",
            "DirectorySnapshotFetchError",
            "DirectorySnapshotFormatError",
            "PeerRecord",
            "PrivateDiscoveryUnavailable",
            "PublicManifestDirectory",
            "load_directory_snapshot",
            "load_public_snapshot_directory",
            "load_records_from_snapshot_file",
        }:
            from . import directory

            return getattr(directory, name)
        if name in {"PromptRequestEnvelope"}:
            from . import envelope

            return getattr(envelope, name)
        if name in {
            "AddressChallenge",
            "AddressExposurePolicy",
            "DialPlan",
            "DialRoute",
            "PeerAddressRecord",
            "PeerAddressRelay",
            "RelayCandidate",
            "UdpEndpoint",
            "build_dial_plan",
        }:
            from . import peer_address

            return getattr(peer_address, name)
        if name in {
            "H3WebSocketClient",
            "H3WebSocketServer",
            "InMemorySessionTicketStore",
            "POR_DATAGRAM_ALPN",
            "POR_H3_ALPN",
            "POR_QUIC_ALPN",
            "QuicDatagramClient",
            "QuicDatagramServer",
            "QuicEndpoint",
            "QuicTransportUnavailable",
            "write_localhost_self_signed_cert",
        }:
            from . import quic_transport

            return getattr(quic_transport, name)
        if name in {"PorLogEvent", "emit_log_event", "format_log_event"}:
            from . import log_events

            return getattr(log_events, name)
        if name in {
            "ExpertModeConfig",
            "ExpertModePreparedRequest",
            "ExpertModeTrace",
            "prepare_expert_mode_request",
        }:
            from . import expert_mode

            return getattr(expert_mode, name)
        from . import memory_index

        return getattr(memory_index, name)
    raise AttributeError(name)
