"""Verified-execution harness (PRD 6.3, 6.4, 6.6).

intent → approval → idempotency → write → read-back → verdict → receipt.
The harness knows adapters only through ports.Adapter; it never knows Google or Stripe.
"""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from threading import Event, RLock, Thread
from typing import Any

from .clock import Clock, SystemClock
from .contracts import (
    Action,
    ApprovalGrantInput,
    ApprovalGrantResult,
    ApprovalRequest,
    CalendarCreateInput,
    CalendarCreateResult,
    CalendarRescheduleInput,
    CalendarRescheduleResult,
    CalendarTarget,
    Evidence,
    FaultKind,
    GrantedBy,
    HistoryEntry,
    NextAction,
    OperationView,
    Outcome,
    PaymentChargeInput,
    PaymentChargeResult,
    PaymentTarget,
    ReasonCode,
    RecapItem,
    RecapResult,
    Receipt,
    ReceiptsRecapInput,
    Target,
    claims_for,
    may_claim_success,
    new_id,
)
from .errors import ReadUnavailable
from .faults import FaultBoard
from .ports import Adapter, ReadRequest, ReadResult, WriteRequest, WriteResult
from .registry import Registry, RegistryUnavailable
from .replay import decide_replay
from .spoken import amount, render_spoken, span
from .verdict import Judgement, judge

APPROVAL_TTL = timedelta(minutes=5)
READ_WINDOW_SECONDS = 5.0
READS_PER_WINDOW = 3


@dataclass(frozen=True)
class Context:
    user_id: str
    run_id: str
    worker_id: str = "worker-1"


@dataclass
class Observation:
    judgement: Judgement | None  # None when every read failed
    evidence: Evidence | None
    observed: Target | None
    version: str | None
    provider_ref: str | None


@dataclass
class Resolution:
    outcome: Outcome
    reason_code: ReasonCode | None
    next_action: NextAction
    observed: Target | None
    evidence: Evidence | None
    writes_applied: int
    automatic_retries: int
    provider_ref: str | None
    attempt_id: str


@dataclass
class Job:
    cls: type
    op: dict
    adapter: Adapter
    req: WriteRequest
    expected: Target
    extra_for: Callable[[Resolution], dict]
    spoken_subject: str | None = None


def serialized_submission(fn):
    @wraps(fn)
    def call(self, inp, ctx, *args, **kwargs):
        key = (
            getattr(inp, "retry_of_operation_id", None)
            or getattr(inp, "approval_request_id", None)
            or f"{ctx.user_id}:{inp.submission_id}"
        )
        deadline = time.monotonic() + self.pending_after if self.pending_after is not None else None
        token = self._pending_deadline.set(deadline)
        try:
            with self._lock("submission:" + key):
                return fn(self, inp, ctx, *args, **kwargs)
        finally:
            self._pending_deadline.reset(token)

    return call


class Rejected(Exception):
    """Internal: stop the flow and answer with a REJECTED / NEEDS_INPUT receipt."""

    def __init__(self, outcome: Outcome, reason: ReasonCode | None, next_action: NextAction):
        self.outcome, self.reason, self.next_action = outcome, reason, next_action


def fingerprint(action: Action, expected: Target) -> str:
    payload = {
        "action": action.value,
        "target": expected.model_dump(mode="json", exclude={"status"}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _suffix(intent_id: str) -> str:
    return intent_id.split("_", 1)[1]


class Harness:
    def __init__(
        self,
        *,
        registry: Registry,
        calendar: Adapter,
        payments: Adapter,
        faults: FaultBoard,
        clock: Clock | None = None,
        consent_token_for: Callable[[str], str | None] | None = None,
        pending_after: float | None = None,
        background_timeout: float = 15.0,
        calendar_id: str = "sandbox_calendar",
    ):
        self.registry = registry
        self.calendar = calendar
        self.payments = payments
        self.faults = faults
        self.clock = clock or SystemClock()
        self.consent_token_for = consent_token_for or (lambda _: None)
        self.pending_after = pending_after
        self.background_timeout = background_timeout
        self._locks: dict[str, RLock] = {}
        self._locks_guard = RLock()
        self._workers: dict[str, Thread] = {}
        self._pending_deadline = ContextVar("pending_deadline", default=None)
        self.calendar_id = calendar_id

    # ------------------------------------------------------------------ public tools ----

    @serialized_submission
    def calendar_create(self, inp: CalendarCreateInput, ctx: Context) -> CalendarCreateResult:
        self._enter(ctx)
        provisional = CalendarTarget(
            calendar_id=self.calendar_id,
            event_id="evt_provisional",
            title=inp.title,
            start=inp.start,
            end=inp.end,
            timezone=inp.timezone,
            status="confirmed",
        )
        fp = fingerprint(
            Action.CALENDAR_CREATE, provisional.model_copy(update={"event_id": "evt_"})
        )
        intent, op, resumed = self._intent_and_operation(
            ctx,
            inp.submission_id,
            None,
            Action.CALENDAR_CREATE,
            fp,
            lambda intent_id: provisional.model_copy(
                update={"event_id": "evt_" + _suffix(intent_id)}
            ),
            lambda intent_id: "evt_" + _suffix(intent_id),
        )
        if isinstance(intent, Receipt):
            return intent  # rejected before any operation
        expected = CalendarTarget.model_validate_json(op["expected_json"])
        if resumed:
            return self._resume(op, ctx, CalendarCreateResult, {"event_id": expected.event_id})
        req = WriteRequest(
            action=Action.CALENDAR_CREATE,
            target=expected,
            provider_key=op["provider_key"],
            precondition_version=None,
            first_sent_at=self.clock.now(),
        )
        return self._run(
            Job(
                CalendarCreateResult,
                op,
                self.calendar,
                req,
                expected,
                lambda res: {"event_id": expected.event_id},
            ),
            ctx,
        )

    @serialized_submission
    def calendar_reschedule(
        self, inp: CalendarRescheduleInput, ctx: Context
    ) -> CalendarRescheduleResult:
        self._enter(ctx)
        try:
            previous, version = self._resolve_event(inp)
        except Rejected as rej:
            # Nothing written: answer on a provisional operation so the receipt is still traceable.
            placeholder = CalendarTarget(
                calendar_id=self.calendar_id,
                event_id=inp.event_id or "evt_unresolved",
                title=inp.event_query or "event",
                start=inp.new_start,
                end=inp.new_end,
                timezone=inp.timezone,
                status="confirmed",
            )
            return self._rejection(
                CalendarRescheduleResult,
                ctx,
                Action.CALENDAR_RESCHEDULE,
                placeholder,
                rej,
                {"event_id": placeholder.event_id, "previous": placeholder},
            )
        expected = previous.model_copy(
            update={"start": inp.new_start, "end": inp.new_end, "timezone": inp.timezone}
        )
        fp = fingerprint(Action.CALENDAR_RESCHEDULE, expected)
        intent, op, resumed = self._intent_and_operation(
            ctx,
            inp.submission_id,
            inp.retry_of_operation_id,
            Action.CALENDAR_RESCHEDULE,
            fp,
            lambda _: expected,
            lambda _: expected.event_id,
        )
        if isinstance(intent, Receipt):
            return intent
        extra = {"event_id": expected.event_id, "previous": previous}
        worker = self._workers.get(op["operation_id"])
        latest = self.registry.latest_receipt(op["operation_id"]) if resumed else None
        retryable = latest and latest["outcome"] in (
            Outcome.NOT_OBSERVED,
            Outcome.UNKNOWN,
            Outcome.REJECTED,
        )
        if resumed and (
            inp.retry_of_operation_id is None or not retryable or (worker and worker.is_alive())
        ):
            return self._resume(op, ctx, CalendarRescheduleResult, extra)
        req = WriteRequest(
            action=Action.CALENDAR_RESCHEDULE,
            target=expected,
            provider_key=expected.event_id,
            precondition_version=version,
            first_sent_at=self.clock.now(),
        )
        subject = inp.event_query[0].upper() + inp.event_query[1:] if inp.event_query else None
        return self._run(
            Job(
                CalendarRescheduleResult,
                op,
                self.calendar,
                req,
                expected,
                lambda res: extra,
                subject,
            ),
            ctx,
        )

    @serialized_submission
    def payment_charge(self, inp: PaymentChargeInput, ctx: Context) -> PaymentChargeResult:
        self._enter(ctx)
        expected = PaymentTarget(
            amount_minor=inp.amount_minor,
            currency=inp.currency,
            payee=inp.payee,
            concept=inp.concept,
            status="succeeded",
        )
        fp = fingerprint(Action.PAYMENT_CHARGE, expected)
        intent, op, resumed = self._intent_and_operation(
            ctx,
            inp.submission_id,
            inp.retry_of_operation_id,
            Action.PAYMENT_CHARGE,
            fp,
            lambda _: expected,
            lambda intent_id: "idem_" + _suffix(intent_id),
        )
        if isinstance(intent, Receipt):
            return intent
        latest = self.registry.latest_receipt(op["operation_id"])
        consumed = self.registry.approval_use_for_operation(op["operation_id"])
        if consumed is not None and (latest is None or latest["outcome"] != Outcome.NEEDS_APPROVAL):
            # The approval was already consumed by this operation: resend returns its state (T11).
            return self._resume(
                op, ctx, PaymentChargeResult, self._payment_extra(op, consumed["approval_id"])
            )
        if inp.approval_id is None:
            return self._needs_approval(op, intent, expected, ctx)
        try:
            self._consume_approval(inp.approval_id, intent, op, expected)
        except Rejected as rej:
            return self._rejection(
                PaymentChargeResult,
                ctx,
                Action.PAYMENT_CHARGE,
                expected,
                rej,
                self._payment_extra(op, None),
                operation=op,
            )
        req = WriteRequest(
            action=Action.PAYMENT_CHARGE,
            target=expected,
            provider_key=op["provider_key"],
            precondition_version=None,
            first_sent_at=self.clock.now(),
        )

        def extra_for(res):
            extra = self._payment_extra(op, inp.approval_id)
            extra["payment_intent_id"] = (
                res.provider_ref
                if res.provider_ref and res.provider_ref.startswith("pi_")
                else None
            )
            extra["charges_applied"] = res.writes_applied
            return extra

        return self._run(
            Job(
                PaymentChargeResult,
                op,
                self.payments,
                req,
                expected,
                extra_for,
            ),
            ctx,
        )

    @serialized_submission
    def approval_grant(
        self, inp: ApprovalGrantInput, ctx: Context, granted_by: GrantedBy = GrantedBy.SESSION_UI
    ) -> ApprovalGrantResult:
        self._enter(ctx)
        token = self.consent_token_for(ctx.run_id)
        if token is None or not hmac.compare_digest(inp.consent_token.encode(), token.encode()):
            raise PermissionError("UNAUTHORIZED: consent_token is not valid for this session")
        return self._grant_request(inp.approval_request_id, ctx, granted_by)

    def _grant_request(self, request_id: str, ctx: Context, granted_by: GrantedBy):
        request = self.registry.approval(request_id)
        if request is None or request["kind"] != "request" or request["run_id"] != ctx.run_id:
            raise LookupError("approval request not found")
        if datetime.fromisoformat(request["expires_at"]) <= self.clock.now():
            raise TimeoutError("APPROVAL_EXPIRED: the approval request expired")
        existing = self.registry.grant_for_request(request_id)
        if existing is not None:
            return self._grant_result(existing)
        approval_id = new_id("apr_")
        expires_at = self.clock.now() + APPROVAL_TTL
        self.registry.insert_approval(
            approval_id=approval_id,
            kind="grant",
            request_id=request_id,
            intent_id=request["intent_id"],
            amount_minor=request["amount_minor"],
            currency=request["currency"],
            payee=request["payee"],
            concept=request["concept"],
            granted_by=granted_by.value,
            expires_at=expires_at,
            run_id=ctx.run_id,
        )
        return self._grant_result(self.registry.approval(approval_id))

    @serialized_submission
    def complete_elicitation(
        self, inp: PaymentChargeInput, ctx: Context, pending: PaymentChargeResult, accepted: bool
    ) -> PaymentChargeResult:
        """Trusted server-only path after validated MCP elicitation, never an exposed tool."""
        self._enter(ctx)
        op = self.registry.operation(pending.operation_id)
        if op is None or op["run_id"] != ctx.run_id or pending.approval_request is None:
            raise LookupError("approval operation not found")
        # Another invocation may have consumed approval while this client was deciding.
        if self.registry.approval_use_for_operation(op["operation_id"]) is not None:
            return self.payment_charge(inp, ctx)
        if not accepted:
            return self._rejection(
                PaymentChargeResult,
                ctx,
                Action.PAYMENT_CHARGE,
                pending.expected,
                Rejected(Outcome.REJECTED, ReasonCode.NO_APPROVAL, NextAction.ASK_USER),
                self._payment_extra(op, None),
                operation=op,
            )
        request_id = pending.approval_request.approval_request_id
        with self._lock("submission:" + request_id):
            grant = self._grant_request(request_id, ctx, GrantedBy.ELICITATION)
        return self.payment_charge(inp.model_copy(update={"approval_id": grant.approval_id}), ctx)

    def operation_get(self, operation_id: str, ctx: Context) -> OperationView:
        self._enter(ctx)
        op = self.registry.operation(operation_id)
        if op is None:
            raise LookupError("operation not found")
        latest = self.registry.latest_receipt(operation_id)
        if latest is None:
            raise LookupError("operation has no receipt yet")
        data = json.loads(latest["receipt_json"])
        if data["outcome"] == Outcome.UNKNOWN:
            data = self.reconcile_operation(op, data, ctx)
        return self._view(op, data)

    def receipts_recap(
        self, inp: ReceiptsRecapInput, ctx: Context, timezone: str = "America/Los_Angeles"
    ) -> RecapResult:
        self._enter(ctx)
        run_id = inp.run_id or ctx.run_id
        items: list[RecapItem] = []
        selected = {}
        for row in self.registry.latest_receipts_for_run(run_id):
            data = json.loads(row["receipt_json"])
            if data["outcome"] != Outcome.VERIFIED:
                continue
            target = data["expected"]
            key = (
                (target["calendar_id"], target["event_id"])
                if "event_id" in target
                else (data["operation_id"],)
            )
            # A later verified move supersedes the original create for this event.
            # Preserve first-seen order so the calendar and payment stay grouped in the story.
            selected[key] = data
        for data in selected.values():
            action = Action(data["action"])
            if action == Action.PAYMENT_CHARGE:
                target = PaymentTarget.model_validate(data["expected"])
                summary = f"One {amount(target)} test charge for the {target.concept}"
            else:
                target = CalendarTarget.model_validate(data["expected"])
                subject = data.get("spoken_subject") or target.title
                summary = f"{subject[0].lower() + subject[1:]} is at {span(target)}"
            items.append(
                RecapItem(
                    operation_id=data["operation_id"],
                    action=action,
                    outcome=Outcome.VERIFIED,
                    observed_at=datetime.fromisoformat(data["observed_at"]),
                    summary=summary,
                )
            )
        recap = RecapResult(
            spoken="x", run_id=run_id, items=items, generated_at=self.clock.now(), timezone=timezone
        )
        return recap.model_copy(update={"spoken": render_spoken(recap)})

    # ------------------------------------------------------------------ intent/operation --

    def _enter(self, ctx: Context) -> None:
        self.faults.active_run = ctx.run_id
        if self.faults.consume(FaultKind.REGISTRY_DOWN, ctx.run_id):
            raise RegistryUnavailable(
                "registry down before the intent was stored; nothing executed"
            )
        self.registry.insert_run(ctx.run_id)

    def _intent_and_operation(
        self, ctx, submission_id, retry_of, action, fp, expected_for, key_for
    ):
        """Returns (intent | rejection receipt, operation row, resumed)."""
        if retry_of is not None:
            op = self.registry.operation(retry_of)
            if op is None:
                raise LookupError("retry_of_operation_id not found")
            intent = self.registry.intent(op["intent_id"])
            if intent["fingerprint"] != fp:
                rej = Rejected(
                    Outcome.REJECTED, ReasonCode.IDEMPOTENCY_PAYLOAD_MISMATCH, NextAction.ASK_USER
                )
                return (
                    self._mismatch_receipt(
                        ctx, action, expected_for(intent["intent_id"]), rej, intent
                    ),
                    op,
                    True,
                )
            return intent, op, True
        intent, created = self.registry.get_or_create_intent(
            ctx.user_id, submission_id, action.value, fp, ctx.run_id
        )
        op = self.registry.operation_by_intent(intent["intent_id"])
        if not created and intent["fingerprint"] != fp:
            rej = Rejected(
                Outcome.REJECTED, ReasonCode.IDEMPOTENCY_PAYLOAD_MISMATCH, NextAction.ASK_USER
            )
            return (
                self._mismatch_receipt(ctx, action, expected_for(intent["intent_id"]), rej, intent),
                op,
                True,
            )
        if op is not None:
            return intent, op, True
        expected = expected_for(intent["intent_id"])
        op_id = new_id("op_")
        self.registry.insert_operation(
            None,
            operation_id=op_id,
            intent_id=intent["intent_id"],
            action=action.value,
            expected_json=expected.model_dump_json(),
            provider_key=key_for(intent["intent_id"]),
            approval_id=None,
            run_id=ctx.run_id,
        )
        if not self.registry.claim(op_id, ctx.worker_id):
            raise RuntimeError("another worker claimed this operation")
        return intent, self.registry.operation(op_id), False

    def _resolve_event(self, inp: CalendarRescheduleInput) -> tuple[CalendarTarget, str | None]:
        if inp.event_id is not None:
            read = self._read(
                self.calendar,
                ReadRequest(action=Action.CALENDAR_RESCHEDULE, provider_ref=inp.event_id),
            )
            if read is None or not read.found or not isinstance(read.observed, CalendarTarget):
                raise Rejected(
                    Outcome.NEEDS_INPUT, ReasonCode.AMBIGUOUS_TARGET, NextAction.ASK_USER
                )
            return read.observed, read.version
        search = getattr(self.calendar, "search", None)
        hits = search(inp.event_query) if search else []
        if len(hits) != 1:
            raise Rejected(Outcome.NEEDS_INPUT, ReasonCode.AMBIGUOUS_TARGET, NextAction.ASK_USER)
        read = self._read(
            self.calendar,
            ReadRequest(action=Action.CALENDAR_RESCHEDULE, provider_ref=hits[0].event_id),
        )
        if read is None or not isinstance(read.observed, CalendarTarget):
            raise Rejected(Outcome.NEEDS_INPUT, ReasonCode.AMBIGUOUS_TARGET, NextAction.ASK_USER)
        return read.observed, read.version

    # ------------------------------------------------------------------ approval ----------

    def _needs_approval(
        self, op, intent, expected: PaymentTarget, ctx: Context
    ) -> PaymentChargeResult:
        request_id = new_id("apr_")
        expires_at = self.clock.now() + APPROVAL_TTL
        self.registry.insert_approval(
            approval_id=request_id,
            kind="request",
            request_id=None,
            intent_id=intent["intent_id"],
            amount_minor=expected.amount_minor,
            currency=expected.currency,
            payee=expected.payee,
            concept=expected.concept,
            granted_by=None,
            expires_at=expires_at,
            run_id=ctx.run_id,
        )
        request = ApprovalRequest(
            approval_request_id=request_id,
            intent_id=intent["intent_id"],
            amount_minor=expected.amount_minor,
            currency=expected.currency,
            payee=expected.payee,
            concept=expected.concept,
            expires_at=expires_at,
        )
        res = Resolution(
            Outcome.NEEDS_APPROVAL,
            ReasonCode.NO_APPROVAL,
            NextAction.GRANT_APPROVAL,
            None,
            None,
            0,
            0,
            None,
            new_id("att_"),
        )
        extra = {
            "payment_intent_id": None,
            "charges_applied": 0,
            "approval_id": None,
            "approval_request": request,
        }
        return self._finish(PaymentChargeResult, op, res, expected, ctx, extra)

    def _consume_approval(self, approval_id: str, intent, op, expected: PaymentTarget) -> None:
        grant = self.registry.approval(approval_id)
        if grant is None or grant["kind"] != "grant":
            raise Rejected(Outcome.REJECTED, ReasonCode.NO_APPROVAL, NextAction.GRANT_APPROVAL)
        use = self.registry.approval_use(approval_id)
        if use is not None and use["operation_id"] != op["operation_id"]:
            raise Rejected(Outcome.REJECTED, ReasonCode.APPROVAL_USED, NextAction.GRANT_APPROVAL)
        bound = (grant["intent_id"], grant["amount_minor"], grant["currency"], grant["payee"])
        if bound != (intent["intent_id"], expected.amount_minor, expected.currency, expected.payee):
            raise Rejected(
                Outcome.REJECTED, ReasonCode.APPROVAL_MISMATCH, NextAction.GRANT_APPROVAL
            )
        if use is None:
            if datetime.fromisoformat(grant["expires_at"]) <= self.clock.now():
                raise Rejected(
                    Outcome.REJECTED, ReasonCode.APPROVAL_EXPIRED, NextAction.GRANT_APPROVAL
                )
            with self.registry.transaction() as conn:
                if not self.registry.consume_approval(conn, approval_id, op["operation_id"]):
                    raise Rejected(
                        Outcome.REJECTED, ReasonCode.APPROVAL_USED, NextAction.GRANT_APPROVAL
                    )

    def _payment_extra(self, op, approval_id: str | None) -> dict[str, Any]:
        latest = self.registry.latest_receipt(op["operation_id"])
        data = json.loads(latest["receipt_json"]) if latest else {}
        approval_id = approval_id or data.get("approval_id")
        grant = self.registry.approval(approval_id) if approval_id else None
        return {
            "payment_intent_id": data.get("payment_intent_id"),
            "charges_applied": data.get("charges_applied", 0),
            "approval_id": approval_id,
            "granted_by": grant["granted_by"] if grant else None,
            "approval_request": None,
        }

    def _grant_result(self, grant) -> ApprovalGrantResult:
        result = ApprovalGrantResult(
            approval_id=grant["approval_id"],
            expires_at=datetime.fromisoformat(grant["expires_at"]),
            bound_to={
                "intent_id": grant["intent_id"],
                "amount_minor": grant["amount_minor"],
                "currency": grant["currency"],
                "payee": grant["payee"],
            },
            granted_by=GrantedBy(grant["granted_by"]),
        )
        return result.model_copy(update={"spoken": render_spoken(result)})

    # ------------------------------------------------------------------ execution cycle ---

    def _cycle(
        self,
        op,
        adapter: Adapter,
        req: WriteRequest,
        ctx: Context,
        attempt_id: str | None = None,
        retries: int = 0,
    ) -> Resolution:
        """One execution cycle: write, observe, at most one automatic replay (RF-15/16)."""
        op_id = op["operation_id"]
        attempt_id = attempt_id or self._attempt(op_id, "write", False, req)
        result = self._write(adapter, op_id, attempt_id, req)
        lost = result.status == "response_lost"
        last_obs: Observation | None = None
        while True:
            if result.status == "error":
                return Resolution(
                    Outcome.REJECTED,
                    None,
                    NextAction.ASK_USER,
                    None,
                    None,
                    0,
                    retries,
                    None,
                    attempt_id,
                )
            if result.status == "precondition_failed":
                obs = self._observe(
                    op_id, attempt_id, adapter, result.provider_ref, req.target, single=True
                )
                if obs.judgement is not None and obs.judgement.matches:
                    # The first write did land (its response was lost); the newer version is ours.
                    reason = ReasonCode.WRITE_RESPONSE_LOST_RECOVERED if lost else None
                    self._verdict(op_id, attempt_id, Outcome.VERIFIED, reason, obs)
                    return Resolution(
                        Outcome.VERIFIED,
                        reason,
                        NextAction.NONE,
                        obs.observed,
                        obs.evidence,
                        1 if lost else 0,
                        retries,
                        result.provider_ref,
                        attempt_id,
                    )
                self._verdict(
                    op_id, attempt_id, Outcome.NOT_OBSERVED, ReasonCode.VERSION_CONFLICT, obs
                )
                return Resolution(
                    Outcome.NOT_OBSERVED,
                    ReasonCode.VERSION_CONFLICT,
                    NextAction.ASK_USER,
                    obs.observed,
                    obs.evidence,
                    0,
                    retries,
                    result.provider_ref,
                    attempt_id,
                )
            if result.status == "response_lost":
                if decide_replay(result.status, retries, adapter.replay_is_safe(req)) == "replay":
                    retries = 1
                    attempt_id = self._attempt(op_id, "replay", True, req)
                    result = self._write(adapter, op_id, attempt_id, req)
                    continue
                reason = (
                    ReasonCode.REPLAY_WINDOW_EXPIRED if retries == 0 else ReasonCode.READ_TIMEOUT
                )
                self._verdict(op_id, attempt_id, Outcome.UNKNOWN, reason, None)
                return Resolution(
                    Outcome.UNKNOWN,
                    reason,
                    NextAction.CHECK_EXISTING_OPERATION,
                    None,
                    None,
                    0,
                    retries,
                    None,
                    attempt_id,
                )
            obs = self._observe(op_id, attempt_id, adapter, result.provider_ref, req.target)
            last_obs = obs
            if obs.judgement is None:
                self._verdict(op_id, attempt_id, Outcome.UNKNOWN, ReasonCode.READ_TIMEOUT, obs)
                return Resolution(
                    Outcome.UNKNOWN,
                    ReasonCode.READ_TIMEOUT,
                    NextAction.CHECK_EXISTING_OPERATION,
                    None,
                    None,
                    0,
                    retries,
                    result.provider_ref,
                    attempt_id,
                )
            if obs.judgement.matches:
                reason = ReasonCode.WRITE_RESPONSE_LOST_RECOVERED if lost else None
                self._verdict(op_id, attempt_id, Outcome.VERIFIED, reason, obs)
                return Resolution(
                    Outcome.VERIFIED,
                    reason,
                    NextAction.NONE,
                    obs.observed,
                    obs.evidence,
                    1,
                    retries,
                    result.provider_ref,
                    attempt_id,
                )
            if decide_replay(result.status, retries, adapter.replay_is_safe(req)) == "replay":
                retries = 1
                attempt_id = self._attempt(op_id, "replay", True, req)
                result = self._write(adapter, op_id, attempt_id, req)
                lost = lost or result.status == "response_lost"
                continue
            self._verdict(
                op_id,
                attempt_id,
                Outcome.NOT_OBSERVED,
                ReasonCode.REPLAY_BUDGET_EXHAUSTED,
                last_obs,
            )
            return Resolution(
                Outcome.NOT_OBSERVED,
                ReasonCode.REPLAY_BUDGET_EXHAUSTED,
                NextAction.ASK_USER,
                last_obs.observed,
                last_obs.evidence,
                0,
                retries,
                result.provider_ref,
                attempt_id,
            )

    def _attempt(self, op_id: str, kind: str, automatic: bool, req: WriteRequest) -> str:
        attempt_id = new_id("att_")
        self.registry.insert_attempt(
            attempt_id=attempt_id,
            operation_id=op_id,
            kind=kind,
            automatic=automatic,
            provider_key=req.provider_key,
            precondition_version=req.precondition_version,
        )
        return attempt_id

    def _write(
        self, adapter: Adapter, op_id: str, attempt_id: str, req: WriteRequest
    ) -> WriteResult:
        started = self.registry.now()
        result = adapter.write(req)
        self.registry.insert_attempt_result(
            attempt_id=attempt_id,
            operation_id=op_id,
            kind="write",
            automatic=False,
            provider_key=req.provider_key,
            precondition_version=req.precondition_version,
            started_at=started,
            status=result.status,
            provider_ref=result.provider_ref,
            version=result.version,
            error=result.error,
        )
        return result

    def _read(self, adapter: Adapter, req: ReadRequest) -> ReadResult | None:
        try:
            return adapter.read(req)
        except ReadUnavailable:
            return None

    def _observe(
        self,
        op_id: str,
        attempt_id: str,
        adapter: Adapter,
        provider_ref: str | None,
        target: Target,
        *,
        single: bool = False,
    ) -> Observation:
        """Up to three spaced reads inside the 5 s window (RF-14); every read is persisted."""
        reads = 1 if single else READS_PER_WINDOW
        spacing = READ_WINDOW_SECONDS / reads
        req = ReadRequest(action=Action.CALENDAR_CREATE, provider_ref=provider_ref, target=target)
        last: Observation = Observation(None, None, None, None, provider_ref)
        for i in range(reads):
            if i:
                self.clock.sleep(spacing)
            read = self._read(adapter, req)
            if read is None:
                continue
            evidence_id = new_id("ev_")
            self.registry.insert_observation(
                evidence_id=evidence_id,
                operation_id=op_id,
                attempt_id=attempt_id,
                found=read.found,
                observed_json=read.observed.model_dump_json() if read.observed else None,
                version=read.version,
                source=read.source.value,
                observed_at=read.observed_at,
            )
            judgement = judge(target, read)
            evidence = Evidence(
                evidence_id=evidence_id,
                source=read.source,
                observed_at=read.observed_at,
                version=read.version,
            )
            last = Observation(judgement, evidence, read.observed, read.version, provider_ref)
            if judgement.matches:
                break
        return last

    def _verdict(
        self,
        op_id: str,
        attempt_id: str,
        outcome: Outcome,
        reason: ReasonCode | None,
        obs: Observation | None,
    ):
        j = obs.judgement if obs else None
        self.registry.insert_verdict(
            operation_id=op_id,
            attempt_id=attempt_id,
            outcome=outcome.value,
            reason_code=reason.value if reason else None,
            evidence_id=obs.evidence.evidence_id if obs and obs.evidence else None,
            rule=j.rule if j else "no_observation",
            compared_fields=j.compared if j else (),
            mismatch=j.mismatch if j else None,
        )

    # ------------------------------------------------------------------ receipts ----------

    def _finish(self, cls, op, res, expected, ctx, extra, *, spoken_subject=None):
        with self._lock(op["operation_id"]):
            return self._finish_locked(
                cls, op, res, expected, ctx, extra, spoken_subject=spoken_subject
            )

    def _finish_locked(
        self,
        cls,
        op,
        res: Resolution,
        expected: Target,
        ctx: Context,
        extra: dict,
        *,
        spoken_subject=None,
    ):
        fired = self.faults.take_fired(ctx.run_id)
        latest = self.registry.latest_receipt(op["operation_id"])
        prior_fault = None
        if latest and (
            latest["outcome"] in (Outcome.PENDING, Outcome.UNKNOWN)
            or latest["attempt_id"] == res.attempt_id
        ):
            prior_fault = json.loads(latest["receipt_json"]).get("fault_injected")
        for kind in fired:
            self.registry.insert_fault(
                run_id=ctx.run_id, kind=kind.value, operation_id=op["operation_id"]
            )
        observed_at = res.evidence.observed_at if res.evidence else self.clock.now()
        receipt_id = new_id("rcpt_")
        receipt = cls(
            spoken="x",
            operation_id=op["operation_id"],
            intent_id=op["intent_id"],
            attempt_id=res.attempt_id,
            action=Action(op["action"]),
            outcome=res.outcome,
            expected=expected,
            observed=res.observed,
            evidence=res.evidence,
            reason_code=res.reason_code,
            allowed_claims=claims_for(res.outcome, Action(op["action"])),
            may_claim_success=may_claim_success(res.outcome),
            next_action=res.next_action,
            writes_applied=res.writes_applied,
            automatic_retries=res.automatic_retries,
            spoken_subject=spoken_subject,
            receipt_id=receipt_id,
            run_id=ctx.run_id,
            fault_injected=fired[0] if fired else prior_fault,
            observed_at=observed_at,
            **extra,
        )
        receipt = receipt.model_copy(update={"spoken": render_spoken(receipt)})
        self.registry.insert_receipt(
            receipt_id=receipt_id,
            operation_id=op["operation_id"],
            attempt_id=res.attempt_id,
            run_id=ctx.run_id,
            outcome=res.outcome.value,
            receipt_json=receipt.model_dump_json(),
        )
        return receipt

    def _rejection(
        self,
        cls,
        ctx: Context,
        action: Action,
        expected: Target,
        rej: Rejected,
        extra: dict,
        operation=None,
    ):
        op = operation or {
            "operation_id": new_id("op_"),
            "intent_id": "int_unresolved",
            "action": action.value,
        }
        res = Resolution(
            rej.outcome, rej.reason, rej.next_action, None, None, 0, 0, None, new_id("att_")
        )
        return self._finish(cls, op, res, expected, ctx, extra)

    def _mismatch_receipt(
        self, ctx: Context, action: Action, expected: Target, rej: Rejected, intent
    ):
        """Persist the rejection on a provisional operation: the real one keeps its state."""
        provisional = {
            "operation_id": new_id("op_"),
            "intent_id": intent["intent_id"],
            "action": action.value,
        }
        cls = {
            Action.CALENDAR_CREATE: CalendarCreateResult,
            Action.CALENDAR_RESCHEDULE: CalendarRescheduleResult,
            Action.PAYMENT_CHARGE: PaymentChargeResult,
        }[action]
        if isinstance(expected, CalendarTarget):
            extra: dict[str, Any] = {"event_id": expected.event_id}
            if action == Action.CALENDAR_RESCHEDULE:
                extra["previous"] = expected
        else:
            extra = {
                "payment_intent_id": None,
                "charges_applied": 0,
                "approval_id": None,
                "approval_request": None,
            }
        return self._rejection(cls, ctx, action, expected, rej, extra, operation=provisional)

    def _resume(self, op, ctx: Context, cls, extra: dict):
        """Resend of a known operation: return its current state; re-observe only if UNKNOWN."""
        latest = self.registry.latest_receipt(op["operation_id"])
        if latest is None:
            raise RuntimeError("operation without receipt cannot be resumed yet")
        data = json.loads(latest["receipt_json"])
        if data["outcome"] == Outcome.UNKNOWN:
            data = self.reconcile_operation(op, data, ctx)
        data.update({k: v for k, v in extra.items() if k not in data or data[k] is None})
        return cls.model_validate(data)

    def reconcile_operation(self, op, data: dict, ctx: Context) -> dict:
        with self._lock(op["operation_id"]):
            worker = self._workers.get(op["operation_id"])
            if worker is not None and worker.is_alive():
                return data
            latest = self.registry.latest_receipt(op["operation_id"])
            data = json.loads(latest["receipt_json"]) if latest else data
            if data["outcome"] not in (Outcome.UNKNOWN, Outcome.PENDING):
                return data
            if data.get("reason_code") == ReasonCode.RECONCILIATION_EXPIRED:
                return data
            self.faults.active_run = ctx.run_id
            data = self._reconcile_read(op, data, ctx)
            attempts = self.registry.attempts(op["operation_id"])
            first = next(
                (a["started_at"] for a in attempts if a["kind"] != "read"), op["created_at"]
            )
            if data["outcome"] in (Outcome.UNKNOWN, Outcome.PENDING) and (
                self.clock.now() - datetime.fromisoformat(first) >= timedelta(hours=24)
            ):
                res = Resolution(
                    Outcome.UNKNOWN,
                    ReasonCode.RECONCILIATION_EXPIRED,
                    NextAction.ASK_USER,
                    None,
                    None,
                    0,
                    data["automatic_retries"],
                    None,
                    data["attempt_id"],
                )
                cls, extra = self._class_and_extra(op, data, res)
                expected_cls = (
                    PaymentTarget if op["action"] == Action.PAYMENT_CHARGE else CalendarTarget
                )
                receipt = self._finish(
                    cls,
                    op,
                    res,
                    expected_cls.model_validate_json(op["expected_json"]),
                    ctx,
                    extra,
                    spoken_subject=data.get("spoken_subject"),
                )
                data = receipt.model_dump(mode="json")
            return data

    def _reconcile_read(self, op, data: dict, ctx: Context) -> dict:
        """Read-only resolution of UNKNOWN (RF-17b, in-process form): never resends."""
        adapter = self.payments if op["action"] == Action.PAYMENT_CHARGE else self.calendar
        expected_cls = PaymentTarget if op["action"] == Action.PAYMENT_CHARGE else CalendarTarget
        expected = expected_cls.model_validate_json(op["expected_json"])
        ref = next(
            (
                a["provider_ref"]
                for a in reversed(self.registry.attempts(op["operation_id"]))
                if a.get("provider_ref")
            ),
            None,
        )
        duplicates = 1
        if ref is None and op["action"] != Action.PAYMENT_CHARGE:
            ref = op["provider_key"]
        if ref is None:
            find = getattr(adapter, "find_by_intent", None)
            hits = find(op["provider_key"]) if find else []
            if not hits:
                return data  # still UNKNOWN; reconcile.py closes it at 24 h (RF-17b)
            ref, duplicates = hits[0], len(hits)
        attempt_id = new_id("att_")
        self.registry.insert_attempt(
            attempt_id=attempt_id,
            operation_id=op["operation_id"],
            kind="read",
            automatic=True,
            provider_key=op["provider_key"],
            precondition_version=None,
        )
        obs = self._observe(op["operation_id"], attempt_id, adapter, ref, expected)
        if obs.judgement is None:
            return data
        if obs.judgement.matches and duplicates == 1:
            res = Resolution(
                Outcome.VERIFIED,
                ReasonCode.WRITE_RESPONSE_LOST_RECOVERED,
                NextAction.NONE,
                obs.observed,
                obs.evidence,
                1,
                data["automatic_retries"],
                ref,
                attempt_id,
            )
        else:
            res = Resolution(
                Outcome.NOT_OBSERVED,
                ReasonCode.POSTCONDITION_MISMATCH,
                NextAction.ASK_USER,
                obs.observed,
                obs.evidence,
                0,
                data["automatic_retries"],
                ref,
                attempt_id,
            )
        self._verdict(op["operation_id"], attempt_id, res.outcome, res.reason_code, obs)
        cls, extra = self._class_and_extra(op, data, res)
        receipt = self._finish(
            cls, op, res, expected, ctx, extra, spoken_subject=data.get("spoken_subject")
        )
        return json.loads(receipt.model_dump_json())

    def _class_and_extra(self, op, data: dict, res: Resolution):
        action = Action(op["action"])
        if action == Action.CALENDAR_CREATE:
            return CalendarCreateResult, {"event_id": data["event_id"]}
        if action == Action.CALENDAR_RESCHEDULE:
            return CalendarRescheduleResult, {
                "event_id": data["event_id"],
                "previous": data["previous"],
            }
        return PaymentChargeResult, {
            "payment_intent_id": res.provider_ref
            if res.provider_ref and res.provider_ref.startswith("pi_")
            else data.get("payment_intent_id"),
            "charges_applied": res.writes_applied,
            "approval_id": data.get("approval_id"),
            "granted_by": data.get("granted_by"),
            "approval_request": None,
        }

    def _view(self, op, data: dict) -> OperationView:
        history: list[HistoryEntry] = []
        for a in self.registry.attempts(op["operation_id"]):
            history.append(
                HistoryEntry(
                    attempt_id=a["attempt_id"],
                    kind="replay"
                    if a["kind"] == "replay"
                    else ("read" if a["kind"] == "read" else "write"),
                    at=datetime.fromisoformat(a["started_at"]),
                    summary=f"{a['kind']}: {a.get('status') or 'started'}",
                )
            )
        for o in self.registry.observations(op["operation_id"]):
            history.append(
                HistoryEntry(
                    attempt_id=o["attempt_id"],
                    kind="read",
                    at=datetime.fromisoformat(o["observed_at"]),
                    summary="read back: found" if o["found"] else "read back: not found",
                )
            )
        for v in self.registry.verdicts(op["operation_id"]):
            history.append(
                HistoryEntry(
                    attempt_id=v["attempt_id"],
                    kind="verdict",
                    at=datetime.fromisoformat(v["created_at"]),
                    summary=f"{v['outcome']}"
                    + (f" ({v['reason_code']})" if v["reason_code"] else ""),
                )
            )
        history.sort(key=lambda h: h.at)
        base = {k: v for k, v in data.items() if k in Receipt.model_fields}
        return OperationView(
            **base,
            history=history,
            payment_intent_id=data.get("payment_intent_id"),
            charges_applied=data.get("charges_applied"),
            granted_by=data.get("granted_by"),
        )

    def _lock(self, key: str):
        with self._locks_guard:
            return self._locks.setdefault(key, RLock())

    def _run(self, job: Job, ctx: Context, *, recovery: bool = False):
        op_id = job.op["operation_id"]
        attempt = self._attempt(op_id, "replay" if recovery else "write", recovery, job.req)
        done = Event()
        result = {}

        def finish(res):
            return self._finish(
                job.cls,
                job.op,
                res,
                job.expected,
                ctx,
                job.extra_for(res),
                spoken_subject=job.spoken_subject,
            )

        def uncertain(outcome, reason=None):
            attempts = self.registry.attempts(op_id)
            current = attempts[-1]["attempt_id"] if attempts else attempt
            retries = int(any(a["kind"] == "replay" for a in attempts))
            return Resolution(
                outcome,
                reason,
                NextAction.CHECK_EXISTING_OPERATION,
                None,
                None,
                0,
                retries,
                None,
                current,
            )

        def cycle():
            try:
                res = self._cycle(job.op, job.adapter, job.req, ctx, attempt, int(recovery))
                with self._lock(op_id):
                    result["receipt"] = finish(res)
                    done.set()
            except Exception:
                logging.getLogger(__name__).exception("Background operation failed: %s", op_id)
                try:
                    with self._lock(op_id):
                        result["receipt"] = finish(
                            uncertain(Outcome.UNKNOWN, ReasonCode.READ_TIMEOUT)
                        )
                finally:
                    done.set()

        if self.pending_after is None:
            res = self._cycle(job.op, job.adapter, job.req, ctx, attempt, int(recovery))
            return finish(res)
        worker = Thread(target=copy_context().run, args=(cycle,), daemon=True)
        self._workers[op_id] = worker
        worker.start()

        def deadline():
            if not done.wait(self.background_timeout):
                with self._lock(op_id):
                    if not done.is_set():
                        finish(uncertain(Outcome.UNKNOWN, ReasonCode.READ_TIMEOUT))

        Thread(target=copy_context().run, args=(deadline,), daemon=True).start()
        deadline_at = self._pending_deadline.get() or time.monotonic() + self.pending_after
        # Budget includes intent/approval work and leaves time to persist/serialize PENDING.
        done.wait(max(0, deadline_at - time.monotonic() - 0.03))
        with self._lock(op_id):
            if done.is_set():
                if "receipt" not in result:
                    raise RegistryUnavailable("Cannot persist operation result")
                return result["receipt"]
            # Deadline may already have appended UNKNOWN; never regress it to PENDING.
            latest = self.registry.latest_receipt(op_id)
            if latest and latest["outcome"] == Outcome.UNKNOWN:
                return job.cls.model_validate_json(latest["receipt_json"])
            return finish(uncertain(Outcome.PENDING))

    def recover_pending(self):
        for op in self.registry.operations_with_outcomes(Outcome.PENDING):
            ctx = Context(user_id="demo", run_id=op["run_id"])
            self.faults.active_run = ctx.run_id
            data = json.loads(self.registry.latest_receipt(op["operation_id"])["receipt_json"])
            # A read can resolve an already-applied write without spending a replay.
            resolved = self.reconcile_operation(op, data, ctx)
            if resolved["outcome"] != Outcome.PENDING:
                continue
            attempts = self.registry.attempts(op["operation_id"])
            writes = [a for a in attempts if a["kind"] != "read"]
            adapter = self.payments if op["action"] == Action.PAYMENT_CHARGE else self.calendar
            expected_cls = (
                PaymentTarget if op["action"] == Action.PAYMENT_CHARGE else CalendarTarget
            )
            expected = expected_cls.model_validate_json(op["expected_json"])
            req = WriteRequest(
                action=Action(op["action"]),
                target=expected,
                provider_key=op["provider_key"],
                precondition_version=writes[0]["precondition_version"] if writes else None,
                first_sent_at=datetime.fromisoformat(
                    writes[0]["started_at"] if writes else op["created_at"]
                ),
            )
            can_replay = bool(writes) and not any(a["kind"] == "replay" for a in writes)
            if op["action"] == Action.CALENDAR_RESCHEDULE and req.precondition_version is None:
                can_replay = False
            if can_replay and adapter.replay_is_safe(req):
                cls, _ = self._class_and_extra(
                    op,
                    data,
                    Resolution(
                        Outcome.PENDING,
                        None,
                        NextAction.CHECK_EXISTING_OPERATION,
                        None,
                        None,
                        0,
                        0,
                        None,
                        data["attempt_id"],
                    ),
                )
                self._run(
                    Job(
                        cls,
                        op,
                        adapter,
                        req,
                        expected,
                        lambda res, op=op, data=data: self._class_and_extra(op, data, res)[1],
                        data.get("spoken_subject"),
                    ),
                    ctx,
                    recovery=True,
                )
            else:
                res = Resolution(
                    Outcome.UNKNOWN,
                    ReasonCode.REPLAY_WINDOW_EXPIRED,
                    NextAction.CHECK_EXISTING_OPERATION,
                    None,
                    None,
                    0,
                    data["automatic_retries"],
                    None,
                    data["attempt_id"],
                )
                cls, extra = self._class_and_extra(op, data, res)
                self._finish(cls, op, res, expected, ctx, extra)

    def wait_for_workers(self, timeout=16.0):
        for worker in list(self._workers.values()):
            worker.join(timeout)
