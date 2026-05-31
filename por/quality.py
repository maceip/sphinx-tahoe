"""Durable v0 feedback store for validated expert jobs."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Sequence

from .expert_manifest import (
    RATING_GREAT,
    RATING_IRRELEVANT,
    RATING_LOW_EFFORT,
    RATING_UNSAFE,
    RATING_WRONG,
    STATUS_COMPLETED,
    ExpertQualitySignals,
    VerifiedQualityEvent,
)


RATING_SCORES = {
    RATING_GREAT: 1.0,
    RATING_LOW_EFFORT: 0.4,
    RATING_IRRELEVANT: 0.25,
    RATING_WRONG: 0.1,
    RATING_UNSAFE: 0.0,
}


class QualityStoreError(RuntimeError):
    pass


class UnknownRequestError(QualityStoreError):
    pass


class RequestNotCompletedError(QualityStoreError):
    pass


class DuplicateFeedbackError(QualityStoreError):
    pass


DuplicateReviewError = DuplicateFeedbackError


class QualityEventStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def record_request(self, event: VerifiedQualityEvent) -> VerifiedQualityEvent:
        with self._connect() as db:
            db.execute(
                """
                insert into request_events (
                  request_id, expert_peer_id, manifest_id, topic, status,
                  latency_ms, answer_digest, timestamp, client_peer_id_hash, signature
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(request_id) do update set
                  expert_peer_id=excluded.expert_peer_id,
                  manifest_id=excluded.manifest_id,
                  topic=excluded.topic,
                  status=excluded.status,
                  latency_ms=excluded.latency_ms,
                  answer_digest=excluded.answer_digest,
                  timestamp=excluded.timestamp,
                  client_peer_id_hash=excluded.client_peer_id_hash,
                  signature=excluded.signature
                """,
                (
                    event.request_id,
                    event.expert_peer_id,
                    event.manifest_id,
                    event.topic,
                    event.status,
                    event.latency_ms,
                    event.answer_digest,
                    event.timestamp,
                    event.client_peer_id_hash,
                    event.signature,
                ),
            )
        return event

    def submit_feedback(
        self,
        *,
        request_id: str,
        rating: str,
        complaint_reason: str | None = None,
        judge_score: float | None = None,
        probe_id: str | None = None,
        timestamp: str | None = None,
        signature: str | None = None,
    ) -> VerifiedQualityEvent:
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            row = db.execute(
                """
                select request_id, expert_peer_id, manifest_id, topic, status,
                       latency_ms, answer_digest, timestamp, client_peer_id_hash, signature
                from request_events where request_id = ?
                """,
                (request_id,),
            ).fetchone()
            if row is None:
                raise UnknownRequestError(f"unknown request_id: {request_id}")
            if row["status"] != STATUS_COMPLETED:
                raise RequestNotCompletedError(f"request_id is not completed: {request_id}")

            event = VerifiedQualityEvent.v0(
                request_id=row["request_id"],
                expert_peer_id=row["expert_peer_id"],
                manifest_id=row["manifest_id"],
                topic=row["topic"],
                status=row["status"],
                latency_ms=int(row["latency_ms"]),
                answer_digest=row["answer_digest"],
                timestamp=timestamp,
                client_peer_id_hash=row["client_peer_id_hash"],
                rating=rating,
                complaint_reason=complaint_reason,
                judge_score=judge_score,
                probe_id=probe_id,
                signature=signature,
            )
            try:
                db.execute(
                    """
                    insert into reviews (
                      request_id, rating, complaint_reason, judge_score,
                      probe_id, timestamp, signature
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.request_id,
                        event.rating,
                        event.complaint_reason,
                        event.judge_score,
                        event.probe_id,
                        event.timestamp,
                        event.signature,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateFeedbackError(f"request_id already has feedback: {request_id}") from exc
        return event

    def submit_review(self, **kwargs) -> VerifiedQualityEvent:
        return self.submit_feedback(**kwargs)

    def aggregate_manifest(self, manifest_id: str) -> ExpertQualitySignals:
        with self._connect() as db:
            rows = db.execute(
                "select status from request_events where manifest_id = ?",
                (manifest_id,),
            ).fetchall()
            completed = sum(1 for row in rows if row["status"] == STATUS_COMPLETED)
            total = len(rows)
            review_rows = db.execute(
                """
                select r.rating, r.judge_score,
                       coalesce(e.client_peer_id_hash, '__unknown__') as client_key
                from reviews r
                join request_events e on e.request_id = r.request_id
                where e.manifest_id = ?
                """,
                (manifest_id,),
            ).fetchall()

        unique_clients = {row["client_key"] for row in review_rows}
        rating_by_client: dict[str, list[float]] = {}
        judge_by_client: dict[str, list[float]] = {}
        for row in review_rows:
            client_key = row["client_key"]
            if row["rating"] in RATING_SCORES:
                rating_by_client.setdefault(client_key, []).append(RATING_SCORES[row["rating"]])
            if row["judge_score"] is not None:
                judge_by_client.setdefault(client_key, []).append(float(row["judge_score"]))
        rating_scores = [sum(values) / len(values) for values in rating_by_client.values()]
        judge_scores = [sum(values) / len(values) for values in judge_by_client.values()]
        return ExpertQualitySignals(
            completed_requests=completed,
            feedback_count=len(review_rows),
            unique_client_count=len(unique_clients),
            success_rate=(completed / total) if total else None,
            median_user_rating=median(rating_scores) if rating_scores else None,
            evaluator_score=(sum(judge_scores) / len(judge_scores)) if judge_scores else None,
        )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                create table if not exists request_events (
                  request_id text primary key,
                  expert_peer_id text not null,
                  manifest_id text not null,
                  topic text not null,
                  status text not null,
                  latency_ms integer not null,
                  answer_digest text not null,
                  timestamp text not null,
                  client_peer_id_hash text,
                  signature text
                )
                """
            )
            _ensure_column(db, "request_events", "client_peer_id_hash", "text")
            db.execute(
                """
                create table if not exists reviews (
                  request_id text primary key references request_events(request_id),
                  rating text not null,
                  complaint_reason text,
                  judge_score real,
                  probe_id text,
                  timestamp text not null,
                  signature text
                )
                """
            )


def _ensure_column(db: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
    columns = {row["name"] for row in db.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"alter table {table} add column {column} {ddl_type}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record and review verified expert quality events.")
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Record a completed/failed request event.")
    record.add_argument("--store", required=True)
    record.add_argument("--event", required=True, help="VerifiedQualityEvent JSON file")

    feedback = sub.add_parser("feedback", help="Submit feedback for a validated completed job.")
    feedback.add_argument("--store", required=True)
    feedback.add_argument("--request-id", required=True)
    feedback.add_argument("--rating", required=True)
    feedback.add_argument("--complaint-reason")
    feedback.add_argument("--judge-score", type=float)
    feedback.add_argument("--probe-id")
    feedback.add_argument("--timestamp")
    feedback.add_argument("--signature")
    review = sub.add_parser("review", help="Alias for feedback.")
    review.add_argument("--store", required=True)
    review.add_argument("--request-id", required=True)
    review.add_argument("--rating", required=True)
    review.add_argument("--complaint-reason")
    review.add_argument("--judge-score", type=float)
    review.add_argument("--probe-id")
    review.add_argument("--timestamp")
    review.add_argument("--signature")

    aggregate = sub.add_parser("aggregate", help="Aggregate manifest quality signals.")
    aggregate.add_argument("--store", required=True)
    aggregate.add_argument("--manifest-id", required=True)

    args = parser.parse_args(list(argv) if argv is not None else None)
    store = QualityEventStore(args.store)
    if args.command == "record":
        event = VerifiedQualityEvent.from_json(Path(args.event).read_text(encoding="utf-8"))
        print(store.record_request(event).to_json())
        return 0
    if args.command in {"feedback", "review"}:
        event = store.submit_feedback(
            request_id=args.request_id,
            rating=args.rating,
            complaint_reason=args.complaint_reason,
            judge_score=args.judge_score,
            probe_id=args.probe_id,
            timestamp=args.timestamp,
            signature=args.signature,
        )
        print(event.to_json())
        return 0
    if args.command == "aggregate":
        print(json.dumps(store.aggregate_manifest(args.manifest_id).__dict__, sort_keys=True, indent=2))
        return 0
    raise ValueError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
