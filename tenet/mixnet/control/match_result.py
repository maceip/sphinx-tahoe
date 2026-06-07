"""Verifiable match-result gossip records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Mapping

from tenet.mixnet.control.names import parse_tenet_name
from tenet.mixnet.control.records import ControlRecord, RECORD_TYPE_MATCH_RESULT

MATCH_RESULT_SCHEMA = "tenet.match_result.2026-06"


@dataclass(frozen=True)
class MatchCandidateDescriptor:
    handle: str
    manifest_digest: str
    peer_id_hint: str | None = None
    score: float | None = None
    cover: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "MatchCandidateDescriptor":
        score = raw.get("score")
        return cls(
            handle=str(raw.get("handle", "")),
            manifest_digest=str(raw.get("manifest_digest", "")),
            peer_id_hint=_optional_str(raw.get("peer_id_hint")),
            score=float(score) if score is not None else None,
            cover=bool(raw.get("cover", False)),
        )

    def validate(self) -> None:
        if not self.handle:
            raise ValueError("match candidate handle is required")
        if not self.manifest_digest:
            raise ValueError("match candidate manifest_digest is required")


@dataclass(frozen=True)
class MatchResultDescriptor:
    """A matcher/TEE-signed result that can be gossiped by untrusted clients."""

    query_commitment: str
    pool_name: str
    matcher_id: str
    candidates: tuple[MatchCandidateDescriptor, ...]
    result_nonce: str
    attestation_ref: str | None = None
    policy_refs: tuple[str, ...] = ()
    schema: str = MATCH_RESULT_SCHEMA

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "MatchResultDescriptor":
        return cls(
            query_commitment=str(raw.get("query_commitment", "")),
            pool_name=str(raw.get("pool_name", "")),
            matcher_id=str(raw.get("matcher_id", "")),
            candidates=tuple(
                MatchCandidateDescriptor.from_dict(item)
                for item in raw.get("candidates", ()) or ()
                if isinstance(item, Mapping)
            ),
            result_nonce=str(raw.get("result_nonce", "")),
            attestation_ref=_optional_str(raw.get("attestation_ref")),
            policy_refs=tuple(str(item) for item in raw.get("policy_refs", ()) or ()),
            schema=str(raw.get("schema", MATCH_RESULT_SCHEMA)),
        )

    @property
    def key(self) -> str:
        return f"match/{self.pool_name}/{self.query_commitment}/{self.matcher_id}"

    def validate(self) -> None:
        if self.schema != MATCH_RESULT_SCHEMA:
            raise ValueError(f"unsupported match result schema: {self.schema}")
        if not self.query_commitment:
            raise ValueError("query_commitment is required")
        if not self.matcher_id:
            raise ValueError("matcher_id is required")
        parsed = parse_tenet_name(self.pool_name)
        if parsed.normalized != self.pool_name or parsed.kind != "pool":
            raise ValueError("match result requires a normalized pool name")
        for candidate in self.candidates:
            candidate.validate()

    def to_dict(self) -> dict[str, object]:
        self.validate()
        raw = asdict(self)
        raw["candidates"] = [asdict(candidate) for candidate in self.candidates]
        return raw

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
            record_type=RECORD_TYPE_MATCH_RESULT,
            seq=seq,
            issued_at=issued_at,
            expires_at=expires_at,
            value=self.to_dict(),
        )


def query_commitment(
    *,
    prompt: str,
    pool_name: str,
    salt: str,
    requested_expertise: str | None = None,
) -> str:
    parsed = parse_tenet_name(pool_name)
    payload = {
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "pool_name": parsed.normalized,
        "requested_expertise": requested_expertise,
        "salt": salt,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def derive_query_commitment(
    *,
    network_id: str,
    pool: str,
    prompt: str,
    expertise: str | None = None,
    dataset_commitment: str | None = None,
    epoch_salt: str,
) -> str:
    """Stronger query commitment binding network, dataset, and epoch.

    A cached match result is only reusable for the *exact* query it answered, on
    the *same* network, against the *same* dataset, in the *same* epoch. Binding
    all of these into the commitment means a result for a different prompt,
    network, dataset, or epoch produces a different commitment and therefore
    cannot be mis-served as a fallback.
    """

    if not network_id:
        raise ValueError("derive_query_commitment requires network_id")
    if not epoch_salt:
        raise ValueError("derive_query_commitment requires epoch_salt")
    parsed = parse_tenet_name(pool)
    payload = {
        "network_id": network_id,
        "pool_name": parsed.normalized,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "requested_expertise": expertise,
        "dataset_commitment": dataset_commitment,
        "epoch_salt": epoch_salt,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class QueryCommitmentPolicy:
    """Binds the non-prompt inputs of a query commitment for an epoch.

    Product code holds one of these instead of threading a bare salt around, so
    the cache lookup before live-matcher fallback is automatic and consistently
    bound to network + dataset + epoch.
    """

    network_id: str
    epoch_salt: str
    dataset_commitment: str | None = None

    def derive(self, *, pool: str, prompt: str, expertise: str | None = None) -> str:
        return derive_query_commitment(
            network_id=self.network_id,
            pool=pool,
            prompt=prompt,
            expertise=expertise,
            dataset_commitment=self.dataset_commitment,
            epoch_salt=self.epoch_salt,
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
