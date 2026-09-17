"""FakePayments: JSON-file PaymentIntents with an Idempotency-Key window (PRD 6.5).

Default window 24 h like Stripe; tests shrink it to exercise RF-15 (never resend out of window).
"""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

from donewise_harness.clock import Clock, SystemClock
from donewise_harness.contracts import Action, EvidenceSource, FaultKind, PaymentTarget, new_id
from donewise_harness.errors import ReadUnavailable
from donewise_harness.faults import FaultBoard
from donewise_harness.ports import ReadRequest, ReadResult, WriteRequest, WriteResult

from .state_lock import locked

SAFETY_MARGIN = timedelta(hours=1)


class FakePayments:
    source = EvidenceSource.FAKE_PAYMENTS

    def __init__(
        self,
        path: Path | str,
        faults: FaultBoard | None = None,
        clock: Clock | None = None,
        idempotency_window: timedelta = timedelta(hours=24),
        delay_seconds: float = 0,
    ):
        self._lock = RLock()
        self.path = Path(path)
        self.faults = faults
        self.clock = clock or SystemClock()
        self.window = idempotency_window
        self.delay_seconds = delay_seconds
        self.write_calls = 0
        self.read_calls = 0
        if not self.path.exists():
            self._save({"intents": {}, "keys": {}})

    @locked
    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    @locked
    def _save(self, state: dict) -> None:
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    @locked
    def intents(self) -> dict[str, dict]:
        return self._load()["intents"]

    def _fault(self, kind: FaultKind) -> bool:
        return self.faults is not None and self.faults.consume_active(kind)

    @staticmethod
    def _to_target(row: dict) -> PaymentTarget:
        return PaymentTarget(
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            payee=row["payee"],
            concept=row["concept"],
            status=row["status"],
        )

    @locked
    def write(self, req: WriteRequest) -> WriteResult:
        time.sleep(self.delay_seconds)
        self.write_calls += 1
        target = req.target
        if req.action != Action.PAYMENT_CHARGE or not isinstance(target, PaymentTarget):
            return WriteResult(
                status="error", provider_ref=None, version=None, error="not a payment"
            )
        state = self._load()
        seen = state["keys"].get(req.provider_key)
        if seen is not None:
            first = datetime.fromisoformat(seen["first_sent_at"])
            if self.clock.now() - first < self.window:
                return WriteResult(
                    status="already_exists",
                    provider_ref=seen["payment_intent_id"],
                    version=None,
                    error=None,
                )
            # Expired key: the provider would treat this as a brand-new request (a duplicate).
        if self._fault(FaultKind.ACK_WITHOUT_WRITE):
            return WriteResult(status="acked", provider_ref=new_id("pi_"), version=None, error=None)
        pi_id = new_id("pi_")
        state["intents"][pi_id] = {
            "run_id": self.faults.active_run if self.faults else None,
            "amount_minor": target.amount_minor,
            "currency": target.currency,
            "payee": target.payee,
            "concept": target.concept,
            "status": "succeeded",
            "idempotency_key": req.provider_key,
            "created_at": self.clock.now().astimezone(UTC).isoformat(),
        }
        state["keys"][req.provider_key] = {
            "payment_intent_id": pi_id,
            "first_sent_at": (req.first_sent_at or self.clock.now()).astimezone(UTC).isoformat(),
        }
        self._save(state)
        if self._fault(FaultKind.DROP_RESPONSE_AFTER_WRITE):
            return WriteResult(status="response_lost", provider_ref=None, version=None, error=None)
        return WriteResult(status="acked", provider_ref=pi_id, version=None, error=None)

    @locked
    def read(self, req: ReadRequest) -> ReadResult:
        self.read_calls += 1
        if self._fault(FaultKind.READ_UNAVAILABLE):
            raise ReadUnavailable("payments read unavailable")
        now = self.clock.now()
        row = self.intents().get(req.provider_ref) if req.provider_ref else None
        if row is None:
            return ReadResult(
                found=False, observed=None, version=None, observed_at=now, source=self.source
            )
        return ReadResult(
            found=True,
            observed=self._to_target(row),
            version=None,
            observed_at=now,
            source=self.source,
        )

    def replay_is_safe(self, req: WriteRequest) -> bool:
        first = req.first_sent_at or self.clock.now()
        return self.clock.now() - first < self.window - SAFETY_MARGIN

    @locked
    def find_by_intent(self, provider_key: str) -> list[str]:
        """Reconciliation helper (RF-17b): PaymentIntents created with this idempotency key."""
        return [pi for pi, row in self.intents().items() if row["idempotency_key"] == provider_key]

    @locked
    def reset_run(self, run_id: str):
        state = self._load()
        state["intents"] = {k: v for k, v in state["intents"].items() if v.get("run_id") != run_id}
        state["keys"] = {
            k: v for k, v in state["keys"].items() if v["payment_intent_id"] in state["intents"]
        }
        self._save(state)
