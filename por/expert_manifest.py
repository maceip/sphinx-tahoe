"""V0 expert-session manifest and quality event contracts.

These are deliberately small public/control-plane primitives. The manifest is
routeable metadata; local session ids, cwd, prompts, secrets, and raw memory stay
on the expert peer. Quality events hang off completed request ids so reputation
can start simple without becoming a governance protocol.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


EXPERT_SESSION_MANIFEST_VERSION = "tenet.expert_manifest.v0"
VERIFIED_QUALITY_EVENT_VERSION = "tenet.quality_event.v0"
CAPABILITY_EXPERT_SESSION = "expert_session"

ENGINE_CLAUDE_CODE = "claude_code"
ENGINE_CODEX = "codex"
ENGINE_OTHER = "other"
VALID_ENGINES = {ENGINE_CLAUDE_CODE, ENGINE_CODEX, ENGINE_OTHER}

STATUS_COMPLETED = "completed"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"
VALID_QUALITY_STATUSES = {STATUS_COMPLETED, STATUS_TIMEOUT, STATUS_ERROR, STATUS_CANCELLED}

RATING_GREAT = "great"
RATING_WRONG = "wrong"
RATING_IRRELEVANT = "irrelevant"
RATING_LOW_EFFORT = "low_effort"
RATING_UNSAFE = "unsafe"
VALID_RATINGS = {RATING_GREAT, RATING_WRONG, RATING_IRRELEVANT, RATING_LOW_EFFORT, RATING_UNSAFE}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]{2,}")


@dataclass(frozen=True)
class ExpertQualitySignals:
    completed_requests: int = 0
    success_rate: float | None = None
    median_user_rating: float | None = None
    evaluator_score: float | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, object] | None) -> "ExpertQualitySignals":
        raw = raw or {}
        return cls(
            completed_requests=int(raw.get("completed_requests", 0)),
            success_rate=_optional_float(raw.get("success_rate")),
            median_user_rating=_optional_float(raw.get("median_user_rating")),
            evaluator_score=_optional_float(raw.get("evaluator_score")),
        ).validate()

    def validate(self) -> "ExpertQualitySignals":
        if self.completed_requests < 0:
            raise ValueError("completed_requests must be non-negative")
        for name, value in (
            ("success_rate", self.success_rate),
            ("median_user_rating", self.median_user_rating),
            ("evaluator_score", self.evaluator_score),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        return self

    def reputation_weight(self) -> float:
        """Small-sample-safe routing weight, intentionally conservative."""

        prior = 0.75
        parts = [
            self.success_rate if self.success_rate is not None else prior,
            self.median_user_rating if self.median_user_rating is not None else prior,
            self.evaluator_score if self.evaluator_score is not None else prior,
        ]
        observed = sum(parts) / len(parts)
        confidence = self.completed_requests / (self.completed_requests + 10.0)
        estimate = (confidence * observed) + ((1.0 - confidence) * prior)
        return max(0.10, min(1.10, estimate))


@dataclass(frozen=True)
class ExpertSessionManifest:
    version: str
    peer_id: str
    manifest_id: str
    capability_type: str
    engine: str
    topics: tuple[str, ...]
    summary: str
    answer_policy: str
    freshness: str
    max_concurrency: int
    fork_per_request: bool
    quality_signals: ExpertQualitySignals = field(default_factory=ExpertQualitySignals)
    signature: str | None = None

    @classmethod
    def v0(
        cls,
        *,
        peer_id: str,
        manifest_id: str,
        engine: str,
        topics: Sequence[str],
        summary: str,
        answer_policy: str = "grounded",
        freshness: str,
        max_concurrency: int = 1,
        fork_per_request: bool = True,
        quality_signals: ExpertQualitySignals | None = None,
        signature: str | None = None,
    ) -> "ExpertSessionManifest":
        return cls(
            version=EXPERT_SESSION_MANIFEST_VERSION,
            peer_id=peer_id,
            manifest_id=manifest_id,
            capability_type=CAPABILITY_EXPERT_SESSION,
            engine=engine,
            topics=tuple(topics),
            summary=summary,
            answer_policy=answer_policy,
            freshness=freshness,
            max_concurrency=max_concurrency,
            fork_per_request=fork_per_request,
            quality_signals=quality_signals or ExpertQualitySignals(),
            signature=signature,
        ).validate()

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "ExpertSessionManifest":
        return cls(
            version=str(raw.get("version", "")),
            peer_id=str(raw.get("peer_id", "")),
            manifest_id=str(raw.get("manifest_id", "")),
            capability_type=str(raw.get("capability_type", "")),
            engine=str(raw.get("engine", "")),
            topics=tuple(str(item) for item in _sequence_or_empty(raw.get("topics"))),
            summary=str(raw.get("summary", "")),
            answer_policy=str(raw.get("answer_policy", "")),
            freshness=str(raw.get("freshness", "")),
            max_concurrency=int(raw.get("max_concurrency", 1)),
            fork_per_request=_bool(raw.get("fork_per_request", True)),
            quality_signals=ExpertQualitySignals.from_dict(_mapping_or_none(raw.get("quality_signals"))),
            signature=_optional_str(raw.get("signature")),
        ).validate()

    @classmethod
    def from_json(cls, data: str | bytes) -> "ExpertSessionManifest":
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        raw = json.loads(data)
        if not isinstance(raw, dict):
            raise ValueError("expert manifest must be a JSON object")
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["quality_signals"] = asdict(self.quality_signals)
        if self.signature is None:
            data.pop("signature", None)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)

    def validate(self) -> "ExpertSessionManifest":
        if self.version != EXPERT_SESSION_MANIFEST_VERSION:
            raise ValueError(f"unsupported expert manifest version: {self.version!r}")
        if not self.peer_id:
            raise ValueError("peer_id is required")
        if not self.manifest_id:
            raise ValueError("manifest_id is required")
        if self.capability_type != CAPABILITY_EXPERT_SESSION:
            raise ValueError("capability_type must be expert_session")
        if self.engine not in VALID_ENGINES:
            raise ValueError(f"unsupported expert session engine: {self.engine!r}")
        if not self.topics:
            raise ValueError("topics must contain at least one topic")
        if any(not topic.strip() for topic in self.topics):
            raise ValueError("topics must not contain empty values")
        if not self.summary.strip():
            raise ValueError("summary is required")
        if not self.answer_policy.strip():
            raise ValueError("answer_policy is required")
        if not self.freshness.strip():
            raise ValueError("freshness is required")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self.quality_signals.validate()
        return self


@dataclass(frozen=True)
class VerifiedQualityEvent:
    version: str
    request_id: str
    expert_peer_id: str
    manifest_id: str
    topic: str
    status: str
    latency_ms: int
    answer_digest: str
    timestamp: str
    rating: str | None = None
    complaint_reason: str | None = None
    judge_score: float | None = None
    probe_id: str | None = None
    signature: str | None = None

    @classmethod
    def v0(
        cls,
        *,
        request_id: str,
        expert_peer_id: str,
        manifest_id: str,
        topic: str,
        status: str,
        latency_ms: int,
        answer_digest: str,
        timestamp: str,
        rating: str | None = None,
        complaint_reason: str | None = None,
        judge_score: float | None = None,
        probe_id: str | None = None,
        signature: str | None = None,
    ) -> "VerifiedQualityEvent":
        return cls(
            version=VERIFIED_QUALITY_EVENT_VERSION,
            request_id=request_id,
            expert_peer_id=expert_peer_id,
            manifest_id=manifest_id,
            topic=topic,
            status=status,
            latency_ms=latency_ms,
            answer_digest=answer_digest,
            timestamp=timestamp,
            rating=rating,
            complaint_reason=complaint_reason,
            judge_score=judge_score,
            probe_id=probe_id,
            signature=signature,
        ).validate()

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "VerifiedQualityEvent":
        return cls(
            version=str(raw.get("version", "")),
            request_id=str(raw.get("request_id", "")),
            expert_peer_id=str(raw.get("expert_peer_id", "")),
            manifest_id=str(raw.get("manifest_id", "")),
            topic=str(raw.get("topic", "")),
            status=str(raw.get("status", "")),
            latency_ms=int(raw.get("latency_ms", 0)),
            answer_digest=str(raw.get("answer_digest", "")),
            timestamp=str(raw.get("timestamp", "")),
            rating=_optional_str(raw.get("rating")),
            complaint_reason=_optional_str(raw.get("complaint_reason")),
            judge_score=_optional_float(raw.get("judge_score")),
            probe_id=_optional_str(raw.get("probe_id")),
            signature=_optional_str(raw.get("signature")),
        ).validate()

    @classmethod
    def from_json(cls, data: str | bytes) -> "VerifiedQualityEvent":
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        raw = json.loads(data)
        if not isinstance(raw, dict):
            raise ValueError("quality event must be a JSON object")
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)

    def validate(self) -> "VerifiedQualityEvent":
        if self.version != VERIFIED_QUALITY_EVENT_VERSION:
            raise ValueError(f"unsupported quality event version: {self.version!r}")
        for name, value in (
            ("request_id", self.request_id),
            ("expert_peer_id", self.expert_peer_id),
            ("manifest_id", self.manifest_id),
            ("topic", self.topic),
            ("answer_digest", self.answer_digest),
            ("timestamp", self.timestamp),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")
        if self.status not in VALID_QUALITY_STATUSES:
            raise ValueError(f"unsupported quality event status: {self.status!r}")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if self.rating is not None and self.rating not in VALID_RATINGS:
            raise ValueError(f"unsupported rating: {self.rating!r}")
        if self.judge_score is not None and not 0.0 <= self.judge_score <= 1.0:
            raise ValueError("judge_score must be between 0 and 1")
        return self


def score_expert_session_manifest(manifest: ExpertSessionManifest, query_text: str) -> float:
    query_terms = _count_terms(query_text)
    manifest_terms = _count_terms(
        " ".join((*manifest.topics, manifest.summary, manifest.answer_policy))
    )
    if not query_terms or not manifest_terms:
        return 0.0
    lexical = _cosine_score(query_terms, manifest_terms)
    topic_count = math.log1p(len(manifest.topics)) / 5.0
    return lexical * (1.0 + topic_count)


def _count_terms(text: str) -> dict[str, int]:
    terms: dict[str, int] = {}
    for token in TOKEN_RE.findall(text.lower()):
        token = token.strip("_-'")
        if len(token) < 3:
            continue
        terms[token] = terms.get(token, 0) + 1
    return terms


def _cosine_score(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    shared = set(left) & set(right)
    if not shared:
        return 0.0
    dot = sum(left[term] * right[term] for term in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("expected object")
    return value


def _sequence_or_empty(value: object) -> Sequence[object]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("expected sequence")
    return value


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
