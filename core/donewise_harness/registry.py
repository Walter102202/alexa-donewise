"""Append-only SQLite registry (PRD RF-26). Only INSERTs; current state = latest row per table.

Claims and approval consumptions are single INSERTs guarded by UNIQUE constraints (RF-11, RF-23).
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .clock import Clock, SystemClock
from .contracts import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS intents (
  intent_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, submission_id TEXT NOT NULL,
  action TEXT NOT NULL, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (user_id, submission_id));
CREATE TABLE IF NOT EXISTS operations (
  operation_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL UNIQUE, action TEXT NOT NULL,
  expected_json TEXT NOT NULL, provider_key TEXT NOT NULL, approval_id TEXT,
  run_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
  attempt_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, kind TEXT NOT NULL,
  automatic INTEGER NOT NULL, provider_key TEXT NOT NULL, precondition_version TEXT,
  status TEXT, provider_ref TEXT, version TEXT, error TEXT,
  started_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS observations (
  evidence_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
  found INTEGER NOT NULL, observed_json TEXT, version TEXT, source TEXT NOT NULL,
  observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verdicts (
  verdict_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
  outcome TEXT NOT NULL, reason_code TEXT, evidence_id TEXT, rule TEXT NOT NULL,
  compared_fields TEXT NOT NULL, mismatch TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS receipts (
  receipt_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
  run_id TEXT NOT NULL, outcome TEXT NOT NULL, receipt_json TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY, kind TEXT NOT NULL, request_id TEXT, intent_id TEXT NOT NULL,
  amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, payee TEXT NOT NULL, concept TEXT NOT NULL,
  granted_by TEXT, expires_at TEXT NOT NULL, run_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approval_uses (
  approval_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claims (
  operation_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS faults (
  fault_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, operation_id TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS protocol_sessions (
  session_id TEXT NOT NULL, protocol_version TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class RegistryUnavailable(RuntimeError):
    """The registry cannot be reached. Before an intent is stored nothing may execute (RF-29)."""


def _iso(value: datetime) -> str:
    return value.isoformat()


class Registry:
    def __init__(self, path: Path | str, clock: Clock | None = None):
        self.path = Path(path)
        self.clock = clock or SystemClock()
        self.down = False  # set by the harness when the registry_down fault fires
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # -- infrastructure -------------------------------------------------------------------

    @contextmanager
    def _conn(self):
        if self.down:
            raise RegistryUnavailable("registry down")
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """Group several INSERTs atomically (approval consumption + operation creation)."""
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def _insert(self, conn: sqlite3.Connection | None, table: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({marks})"
        if conn is not None:
            conn.execute(sql, tuple(row.values()))
        else:
            with self._conn() as own:
                own.execute(sql, tuple(row.values()))

    def _one(self, sql: str, *params: Any) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def now(self) -> str:
        return _iso(self.clock.now())

    # -- writes (INSERT only) -------------------------------------------------------------

    def insert_run(self, run_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO runs (run_id, created_at) VALUES (?, ?)",
                (run_id, self.now()),
            )

    def get_or_create_intent(
        self, user_id: str, submission_id: str, action: str, fingerprint: str, run_id: str
    ) -> tuple[dict[str, Any], bool]:
        """Returns (intent row, created). A resend with the same submission_id gets the same row."""
        existing = self.intent_by_submission(user_id, submission_id)
        if existing:
            return existing, False
        row = {
            "intent_id": new_id("int_"),
            "user_id": user_id,
            "submission_id": submission_id,
            "action": action,
            "fingerprint": fingerprint,
            "run_id": run_id,
            "created_at": self.now(),
        }
        try:
            self._insert(None, "intents", row)
        except sqlite3.IntegrityError:
            found = self.intent_by_submission(user_id, submission_id)
            assert found is not None
            return found, False
        return row, True

    def insert_operation(
        self,
        conn: sqlite3.Connection | None,
        *,
        operation_id: str,
        intent_id: str,
        action: str,
        expected_json: str,
        provider_key: str,
        approval_id: str | None,
        run_id: str,
    ) -> None:
        self._insert(
            conn,
            "operations",
            {
                "operation_id": operation_id,
                "intent_id": intent_id,
                "action": action,
                "expected_json": expected_json,
                "provider_key": provider_key,
                "approval_id": approval_id,
                "run_id": run_id,
                "created_at": self.now(),
            },
        )

    def consume_approval(
        self, conn: sqlite3.Connection, approval_id: str, operation_id: str
    ) -> bool:
        try:
            self._insert(
                conn,
                "approval_uses",
                {
                    "approval_id": approval_id,
                    "operation_id": operation_id,
                    "created_at": self.now(),
                },
            )
        except sqlite3.IntegrityError:
            return False
        return True

    def claim(self, operation_id: str, worker_id: str) -> bool:
        try:
            self._insert(
                None,
                "claims",
                {"operation_id": operation_id, "worker_id": worker_id, "created_at": self.now()},
            )
        except sqlite3.IntegrityError:
            return False
        return True

    def insert_attempt(
        self,
        *,
        attempt_id: str,
        operation_id: str,
        kind: str,
        automatic: bool,
        provider_key: str,
        precondition_version: str | None,
    ) -> None:
        self._insert(
            None,
            "attempts",
            {
                "attempt_id": attempt_id,
                "operation_id": operation_id,
                "kind": kind,
                "automatic": int(automatic),
                "provider_key": provider_key,
                "precondition_version": precondition_version,
                "status": None,
                "provider_ref": None,
                "version": None,
                "error": None,
                "started_at": self.now(),
                "finished_at": None,
            },
        )

    def insert_attempt_result(
        self,
        *,
        attempt_id: str,
        operation_id: str,
        kind: str,
        automatic: bool,
        provider_key: str,
        precondition_version: str | None,
        started_at: str,
        status: str,
        provider_ref: str | None,
        version: str | None,
        error: str | None,
    ) -> None:
        """Append-only: the result of an attempt is a second row with the same attempt_id suffix."""
        self._insert(
            None,
            "attempts",
            {
                "attempt_id": attempt_id + ".result",
                "operation_id": operation_id,
                "kind": kind,
                "automatic": int(automatic),
                "provider_key": provider_key,
                "precondition_version": precondition_version,
                "status": status,
                "provider_ref": provider_ref,
                "version": version,
                "error": error,
                "started_at": started_at,
                "finished_at": self.now(),
            },
        )

    def insert_observation(
        self,
        *,
        evidence_id: str,
        operation_id: str,
        attempt_id: str,
        found: bool,
        observed_json: str | None,
        version: str | None,
        source: str,
        observed_at: datetime,
    ) -> None:
        self._insert(
            None,
            "observations",
            {
                "evidence_id": evidence_id,
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "found": int(found),
                "observed_json": observed_json,
                "version": version,
                "source": source,
                "observed_at": _iso(observed_at),
            },
        )

    def insert_verdict(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        outcome: str,
        reason_code: str | None,
        evidence_id: str | None,
        rule: str,
        compared_fields: tuple[str, ...],
        mismatch: str | None,
    ) -> str:
        verdict_id = new_id("ev_").replace("ev_", "vrd_", 1)
        self._insert(
            None,
            "verdicts",
            {
                "verdict_id": verdict_id,
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "outcome": outcome,
                "reason_code": reason_code,
                "evidence_id": evidence_id,
                "rule": rule,
                "compared_fields": json.dumps(list(compared_fields)),
                "mismatch": mismatch,
                "created_at": self.now(),
            },
        )
        return verdict_id

    def insert_receipt(
        self,
        *,
        receipt_id: str,
        operation_id: str,
        attempt_id: str,
        run_id: str,
        outcome: str,
        receipt_json: str,
    ) -> None:
        self._insert(
            None,
            "receipts",
            {
                "receipt_id": receipt_id,
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "run_id": run_id,
                "outcome": outcome,
                "receipt_json": receipt_json,
                "created_at": self.now(),
            },
        )

    def insert_approval(
        self,
        *,
        approval_id: str,
        kind: str,
        request_id: str | None,
        intent_id: str,
        amount_minor: int,
        currency: str,
        payee: str,
        concept: str,
        granted_by: str | None,
        expires_at: datetime,
        run_id: str,
    ) -> None:
        self._insert(
            None,
            "approvals",
            {
                "approval_id": approval_id,
                "kind": kind,
                "request_id": request_id,
                "intent_id": intent_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "payee": payee,
                "concept": concept,
                "granted_by": granted_by,
                "expires_at": _iso(expires_at),
                "run_id": run_id,
                "created_at": self.now(),
            },
        )

    def insert_fault(self, *, run_id: str, kind: str, operation_id: str | None) -> None:
        self._insert(
            None,
            "faults",
            {
                "fault_id": new_id("ev_").replace("ev_", "flt_", 1),
                "run_id": run_id,
                "kind": kind,
                "operation_id": operation_id,
                "created_at": self.now(),
            },
        )

    # -- reads (latest row wins) ----------------------------------------------------------

    def intent_by_submission(self, user_id: str, submission_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM intents WHERE user_id = ? AND submission_id = ?", user_id, submission_id
        )

    def intent(self, intent_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM intents WHERE intent_id = ?", intent_id)

    def operation_by_intent(self, intent_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM operations WHERE intent_id = ?", intent_id)

    def operation(self, operation_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM operations WHERE operation_id = ?", operation_id)

    def attempts(self, operation_id: str) -> list[dict[str, Any]]:
        """Attempt starts, in order (result rows are joined into each start row)."""
        rows = self._all(
            "SELECT * FROM attempts WHERE operation_id = ? ORDER BY rowid", operation_id
        )
        starts = [r for r in rows if not r["attempt_id"].endswith(".result")]
        results = {
            r["attempt_id"][: -len(".result")]: r
            for r in rows
            if r["attempt_id"].endswith(".result")
        }
        for start in starts:
            result = results.get(start["attempt_id"])
            if result:
                for key in ("status", "provider_ref", "version", "error", "finished_at"):
                    start[key] = result[key]
        return starts

    def observations(
        self, operation_id: str, attempt_id: str | None = None
    ) -> list[dict[str, Any]]:
        if attempt_id is None:
            return self._all(
                "SELECT * FROM observations WHERE operation_id = ? ORDER BY rowid", operation_id
            )
        return self._all(
            "SELECT * FROM observations WHERE operation_id = ? AND attempt_id = ? ORDER BY rowid",
            operation_id,
            attempt_id,
        )

    def verdicts(self, operation_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM verdicts WHERE operation_id = ? ORDER BY rowid", operation_id
        )

    def latest_receipt(self, operation_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM receipts WHERE operation_id = ? ORDER BY rowid DESC LIMIT 1",
            operation_id,
        )

    def latest_receipts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Last receipt of each operation in the run, oldest operation first."""
        return self._all(
            "SELECT r.* FROM receipts r JOIN ("
            "  SELECT operation_id, MAX(rowid) AS last FROM receipts"
            "  WHERE run_id = ? GROUP BY operation_id"
            ") x ON x.last = r.rowid ORDER BY r.rowid",
            run_id,
        )

    def approval(self, approval_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM approvals WHERE approval_id = ?", approval_id)

    def grant_for_request(self, request_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM approvals WHERE kind = 'grant' AND request_id = ?", request_id
        )

    def approval_use(self, approval_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM approval_uses WHERE approval_id = ?", approval_id)

    def approval_use_for_operation(self, operation_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM approval_uses WHERE operation_id = ?", operation_id)

    def operations_with_outcomes(self, *outcomes: str) -> list[dict[str, Any]]:
        marks = ",".join("?" for _ in outcomes)
        return self._all(
            "SELECT o.* FROM operations o JOIN receipts r ON r.operation_id=o.operation_id "
            "WHERE r.rowid=(SELECT MAX(r2.rowid) FROM receipts r2 "
            f"WHERE r2.operation_id=o.operation_id) AND r.outcome IN ({marks})",
            *outcomes,
        )

    def record_protocol(self, session_id: str, version: str):
        self._insert(
            None,
            "protocol_sessions",
            {
                "session_id": session_id,
                "protocol_version": version,
                "created_at": self.now(),
            },
        )
