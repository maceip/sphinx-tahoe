"""Pool descriptors for mixnet-bonded expert discovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping

from tenet.mixnet.control.names import TenetName, parse_tenet_name
from tenet.mixnet.control.records import ControlRecord, RECORD_TYPE_POOL_DESCRIPTOR
from tenet.protocol_invariants import reject_routeable_string

POOL_DESCRIPTOR_SCHEMA = "tenet.pool_descriptor.2026-06"


@dataclass(frozen=True)
class PoolDescriptor:
    """Public control-plane description of an expert pool.

    Membership is by client advertisement/capability records. This object names
    the pool and its policy; it is not a route and it carries no endpoints.
    """

    name: str
    topic_tags: tuple[str, ...]
    min_pool_size: int = 3
    ranking_policy: str = "manifest_fit_then_reputation"
    member_capability_refs: tuple[str, ...] = ()
    claim_refs: tuple[str, ...] = ()
    # ARC / payment commitment (Phase 1). The pool commits its blind-token issuer
    # public key, its Algorand pay-to address, the issuance epoch, and how many
    # queries each token grants. Clients verify rate-limit tokens ONLY under this
    # committed key, which is itself carried in a *signed* pool control record.
    arc_issuer_key_pem: str | None = None
    pay_to: str | None = None
    token_epoch: str | None = None
    queries_per_token: int = 1
    schema: str = POOL_DESCRIPTOR_SCHEMA

    @classmethod
    def from_name(
        cls,
        name: str | TenetName,
        *,
        topic_tags: tuple[str, ...] | None = None,
        min_pool_size: int = 3,
    ) -> "PoolDescriptor":
        parsed = parse_tenet_name(name) if isinstance(name, str) else name
        tags = topic_tags if topic_tags is not None else tuple(parsed.labels)
        return cls(
            name=parsed.normalized,
            topic_tags=tuple(tags),
            min_pool_size=min_pool_size,
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "PoolDescriptor":
        return cls(
            name=str(raw.get("name", "")),
            topic_tags=tuple(str(item) for item in raw.get("topic_tags", ()) or ()),
            min_pool_size=int(raw.get("min_pool_size", 3)),
            ranking_policy=str(raw.get("ranking_policy", "manifest_fit_then_reputation")),
            member_capability_refs=tuple(
                str(item) for item in raw.get("member_capability_refs", ()) or ()
            ),
            claim_refs=tuple(str(item) for item in raw.get("claim_refs", ()) or ()),
            arc_issuer_key_pem=_optional_str(raw.get("arc_issuer_key_pem")),
            pay_to=_optional_str(raw.get("pay_to")),
            token_epoch=_optional_str(raw.get("token_epoch")),
            queries_per_token=int(raw.get("queries_per_token", 1)),
            schema=str(raw.get("schema", POOL_DESCRIPTOR_SCHEMA)),
        )

    @property
    def key(self) -> str:
        return f"pool/{self.name}/descriptor"

    def issuer_public_key(self):
        """Parsed blind-token issuer public key, or None if the pool has no ARC."""
        if not self.arc_issuer_key_pem:
            return None
        from tenet.blind_rsa import IssuerPublicKey

        return IssuerPublicKey.from_pem(self.arc_issuer_key_pem.encode("utf-8"))

    def validate(self) -> None:
        if self.schema != POOL_DESCRIPTOR_SCHEMA:
            raise ValueError(f"unsupported pool descriptor schema: {self.schema}")
        parsed = parse_tenet_name(self.name)
        if parsed.normalized != self.name:
            raise ValueError("pool descriptor name is not normalized")
        if parsed.kind != "pool":
            raise ValueError("pool descriptor requires a pool Tenet name")
        if not self.topic_tags:
            raise ValueError("pool descriptor requires topic tags")
        if self.min_pool_size < 1:
            raise ValueError("min_pool_size must be positive")
        # A pool descriptor names a pool and its membership *by reference*. It must
        # never embed a routeable peer id/endpoint — that would collapse the
        # discovery layer onto the routing layer.
        for ref in self.member_capability_refs:
            reject_routeable_string(ref, field="pool member_capability_ref")
        for tag in self.topic_tags:
            reject_routeable_string(tag, field="pool topic_tag")
        if self.queries_per_token < 1:
            raise ValueError("queries_per_token must be positive")
        if self.arc_issuer_key_pem is not None:
            # must be a real, parseable RSA public key
            try:
                self.issuer_public_key()
            except Exception as exc:  # noqa: BLE001 - any parse failure is invalid
                raise ValueError(f"invalid arc_issuer_key_pem: {exc}") from exc

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)

    def to_record(
        self,
        *,
        network_id: str,
        seq: int,
        issued_at: float,
        expires_at: float,
    ) -> ControlRecord:
        return ControlRecord(
            network_id=network_id,
            key=self.key,
            record_type=RECORD_TYPE_POOL_DESCRIPTOR,
            seq=seq,
            issued_at=issued_at,
            expires_at=expires_at,
            value=self.to_dict(),
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
