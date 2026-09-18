"""Shared wire contracts. Validation is not a substitute for provider verification."""

from calendar import monthrange
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)


class Outcome(StrEnum):
    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    NEEDS_INPUT = "NEEDS_INPUT"
    NOT_OBSERVED = "NOT_OBSERVED"
    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"


class ReasonCode(StrEnum):
    POSTCONDITION_MISMATCH = "POSTCONDITION_MISMATCH"
    READ_TIMEOUT = "READ_TIMEOUT"
    WRITE_RESPONSE_LOST_RECOVERED = "WRITE_RESPONSE_LOST_RECOVERED"
    REPLAY_BUDGET_EXHAUSTED = "REPLAY_BUDGET_EXHAUSTED"
    REPLAY_WINDOW_EXPIRED = "REPLAY_WINDOW_EXPIRED"
    RECONCILIATION_EXPIRED = "RECONCILIATION_EXPIRED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    NO_APPROVAL = "NO_APPROVAL"
    APPROVAL_MISMATCH = "APPROVAL_MISMATCH"
    APPROVAL_USED = "APPROVAL_USED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    IDEMPOTENCY_PAYLOAD_MISMATCH = "IDEMPOTENCY_PAYLOAD_MISMATCH"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    UNAUTHORIZED = "UNAUTHORIZED"
    REGISTRY_UNAVAILABLE = "REGISTRY_UNAVAILABLE"


class Claim(StrEnum):
    EFFECT_VERIFIED = "EFFECT_VERIFIED"
    LATEST_READ_MATCHES_TARGET = "LATEST_READ_MATCHES_TARGET"
    LATEST_READ_DIFFERS_FROM_TARGET = "LATEST_READ_DIFFERS_FROM_TARGET"
    EFFECT_UNVERIFIED = "EFFECT_UNVERIFIED"
    CHARGED_ONCE = "CHARGED_ONCE"
    NOTHING_CHARGED = "NOTHING_CHARGED"
    OPERATION_IN_PROGRESS = "OPERATION_IN_PROGRESS"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class NextAction(StrEnum):
    NONE = "NONE"
    CHECK_EXISTING_OPERATION = "CHECK_EXISTING_OPERATION"
    ASK_USER = "ASK_USER"
    GRANT_APPROVAL = "GRANT_APPROVAL"


class Action(StrEnum):
    CALENDAR_CREATE = "CALENDAR_CREATE"
    CALENDAR_RESCHEDULE = "CALENDAR_RESCHEDULE"
    PAYMENT_CHARGE = "PAYMENT_CHARGE"


class EvidenceSource(StrEnum):
    GOOGLE_CALENDAR = "google_calendar"
    STRIPE_TEST = "stripe_test"
    FAKE_CALENDAR = "fake_calendar"
    FAKE_PAYMENTS = "fake_payments"


class GrantedBy(StrEnum):
    SESSION_UI = "session_ui"
    MCP_CLIENT = "mcp_client"
    ELICITATION = "elicitation"


class FaultKind(StrEnum):
    DROP_RESPONSE_AFTER_WRITE = "drop_response_after_write"
    ACK_WITHOUT_WRITE = "ack_without_write"
    READ_UNAVAILABLE = "read_unavailable"
    CONCURRENT_EDIT = "concurrent_edit"
    REGISTRY_DOWN = "registry_down"


IntentId = Annotated[str, Field(pattern=r"^int_[A-Za-z0-9_-]+$")]
OperationId = Annotated[str, Field(pattern=r"^op_[A-Za-z0-9_-]+$")]
AttemptId = Annotated[str, Field(pattern=r"^att_[A-Za-z0-9_-]+$")]
EvidenceId = Annotated[str, Field(pattern=r"^ev_[A-Za-z0-9_-]+$")]
ReceiptId = Annotated[str, Field(pattern=r"^rcpt_[A-Za-z0-9_-]+$")]
ApprovalId = Annotated[str, Field(pattern=r"^apr_[A-Za-z0-9_-]+$")]
RunId = Annotated[str, Field(pattern=r"^run_[A-Za-z0-9_-]+$")]
EventId = Annotated[str, Field(pattern=r"^evt_[A-Za-z0-9_-]+$")]
PaymentIntentId = Annotated[str, Field(pattern=r"^pi_[A-Za-z0-9_-]+$")]
IdPrefix = Literal["int_", "op_", "att_", "ev_", "rcpt_", "apr_", "run_", "evt_", "pi_"]


def new_id(prefix: IdPrefix) -> str:
    if prefix not in ("int_", "op_", "att_", "ev_", "rcpt_", "apr_", "run_", "evt_", "pi_"):
        raise ValueError("Unsupported identity prefix")
    return prefix + uuid4().hex


@lru_cache(maxsize=128)
def timezone_for(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown IANA timezone") from None


def valid_timezone(name: str) -> str:
    timezone_for(name)
    return name


UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda dt: dt.astimezone(UTC))]
Timezone = Annotated[str, AfterValidator(valid_timezone)]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
PositiveAmount = Annotated[int, Field(gt=0, strict=True)]
Count = Annotated[int, Field(ge=0, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarTarget(Contract):
    calendar_id: Text
    event_id: EventId
    title: Text
    start: UtcDatetime
    end: UtcDatetime
    timezone: Timezone
    status: Literal["confirmed", "cancelled"]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class PaymentTarget(Contract):
    amount_minor: PositiveAmount
    currency: Currency
    payee: Text
    concept: Text
    status: Literal[
        "requires_payment_method",
        "requires_confirmation",
        "requires_action",
        "processing",
        "requires_capture",
        "canceled",
        "succeeded",
    ]


Target = CalendarTarget | PaymentTarget


class Evidence(Contract):
    evidence_id: EvidenceId
    source: EvidenceSource
    observed_at: UtcDatetime
    version: str | None


class ApprovalBinding(Contract):
    intent_id: IntentId
    amount_minor: PositiveAmount
    currency: Currency
    payee: Text


class ApprovalRequest(ApprovalBinding):
    approval_request_id: ApprovalId
    concept: Text
    expires_at: UtcDatetime


def may_claim_success(outcome: Outcome) -> bool:
    return outcome == Outcome.VERIFIED


def claims_for(outcome: Outcome, action: Action) -> list[Claim]:
    if outcome == Outcome.VERIFIED:
        return [Claim.EFFECT_VERIFIED, Claim.LATEST_READ_MATCHES_TARGET] + (
            [Claim.CHARGED_ONCE] if action == Action.PAYMENT_CHARGE else []
        )
    if outcome == Outcome.REJECTED:
        return [Claim.NOTHING_CHARGED] if action == Action.PAYMENT_CHARGE else []
    return {
        Outcome.PENDING: [Claim.OPERATION_IN_PROGRESS],
        Outcome.NEEDS_APPROVAL: [Claim.APPROVAL_REQUIRED, Claim.NOTHING_CHARGED],
        Outcome.NEEDS_INPUT: [],
        Outcome.NOT_OBSERVED: [Claim.EFFECT_UNVERIFIED, Claim.LATEST_READ_DIFFERS_FROM_TARGET],
        Outcome.UNKNOWN: [Claim.EFFECT_UNVERIFIED],
    }[outcome]


class ToolResult(Contract):
    spoken: str
    structured_version: Literal["1.0"] = "1.0"


class Receipt(ToolResult):
    schema_version: Literal["1.0"] = "1.0"
    operation_id: OperationId
    intent_id: IntentId
    attempt_id: AttemptId
    action: Action
    outcome: Outcome
    expected: Target
    observed: Target | None
    evidence: Evidence | None
    reason_code: ReasonCode | None
    allowed_claims: list[Claim]
    may_claim_success: bool
    next_action: NextAction
    writes_applied: Count
    # Replays in this execution cycle; a manual retry starts a new cycle.
    # Resetting this counter does not renew the operation-wide replay budget (RF-15).
    automatic_retries: Annotated[int, Field(ge=0, le=1, strict=True)]
    spoken: Text
    spoken_subject: Text | None = None
    receipt_id: ReceiptId | None
    run_id: RunId
    fault_injected: FaultKind | None
    observed_at: UtcDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.may_claim_success != may_claim_success(self.outcome):
            raise ValueError("may_claim_success contradicts policy")
        if self.allowed_claims != claims_for(self.outcome, self.action):
            raise ValueError("allowed_claims contradict policy (including order/duplicates)")
        if self.outcome in (Outcome.NEEDS_APPROVAL, Outcome.REJECTED) and self.writes_applied:
            raise ValueError("This outcome requires zero writes")
        target_type = PaymentTarget if self.action == Action.PAYMENT_CHARGE else CalendarTarget
        if not isinstance(self.expected, target_type) or (
            self.observed is not None and not isinstance(self.observed, target_type)
        ):
            raise ValueError("Target type must match action")
        if self.evidence is not None:
            sources = (
                (EvidenceSource.STRIPE_TEST, EvidenceSource.FAKE_PAYMENTS)
                if self.action == Action.PAYMENT_CHARGE
                else (EvidenceSource.GOOGLE_CALENDAR, EvidenceSource.FAKE_CALENDAR)
            )
            if self.evidence.source not in sources or self.evidence.observed_at != self.observed_at:
                raise ValueError("Evidence source/time must match receipt")
        if self.observed is not None and self.evidence is None:
            raise ValueError("Observed state requires evidence")
        if self.outcome == Outcome.VERIFIED and (
            self.observed != self.expected
            or self.evidence is None
            or self.receipt_id is None
            or self.expected.status not in ("confirmed", "succeeded")
        ):
            raise ValueError("VERIFIED requires matching observation, evidence and durable receipt")
        return self


class CalendarCreateResult(Receipt):
    action: Literal[Action.CALENDAR_CREATE] = Action.CALENDAR_CREATE
    expected: CalendarTarget
    observed: CalendarTarget | None
    event_id: EventId

    @model_validator(mode="after")
    def same_event(self) -> Self:
        if self.event_id != self.expected.event_id:
            raise ValueError("event_id must match target")
        return self


class CalendarRescheduleResult(Receipt):
    action: Literal[Action.CALENDAR_RESCHEDULE] = Action.CALENDAR_RESCHEDULE
    expected: CalendarTarget
    observed: CalendarTarget | None
    event_id: EventId
    previous: CalendarTarget

    @model_validator(mode="after")
    def same_event(self) -> Self:
        if (
            self.event_id != self.expected.event_id
            or self.event_id != self.previous.event_id
            or self.previous.calendar_id != self.expected.calendar_id
        ):
            raise ValueError("previous and expected must identify the same event")
        return self


class PaymentChargeResult(Receipt):
    action: Literal[Action.PAYMENT_CHARGE] = Action.PAYMENT_CHARGE
    expected: PaymentTarget
    observed: PaymentTarget | None
    payment_intent_id: PaymentIntentId | None
    charges_applied: Count
    approval_id: ApprovalId | None
    approval_request: ApprovalRequest | None
    granted_by: GrantedBy | None = None

    @model_validator(mode="after")
    def payment_consistency(self) -> Self:
        if self.charges_applied != self.writes_applied:
            raise ValueError("Payment writes and charges must agree")
        if self.outcome == Outcome.VERIFIED and (
            self.charges_applied != 1
            or self.payment_intent_id is None
            or self.approval_id is None
            or self.expected.status != "succeeded"
        ):
            raise ValueError("Verified payment requires one approved, identified, succeeded charge")
        if self.outcome == Outcome.NEEDS_APPROVAL and self.approval_request is None:
            raise ValueError("NEEDS_APPROVAL requires an approval request")
        if self.approval_request is not None:
            request = self.approval_request
            if request.intent_id != self.intent_id or any(
                getattr(request, key) != getattr(self.expected, key)
                for key in ("amount_minor", "currency", "payee", "concept")
            ):
                raise ValueError("Approval request must bind this intent and payment")
        return self


class HistoryEntry(Contract):
    attempt_id: AttemptId
    kind: Literal["write", "read", "replay", "verdict"]
    at: UtcDatetime
    summary: Text


class OperationView(Receipt):
    history: list[HistoryEntry]
    # Preserve payment-specific presentation when operation_get resolves a pending charge.
    payment_intent_id: PaymentIntentId | None = None
    charges_applied: Count | None = None
    granted_by: GrantedBy | None = None

    @model_validator(mode="after")
    def payment_observation(self) -> Self:
        if self.action == Action.PAYMENT_CHARGE and self.outcome == Outcome.VERIFIED:
            if (
                self.payment_intent_id is None
                or self.charges_applied != 1
                or self.writes_applied != 1
            ):
                raise ValueError("Verified payment view requires one identified charge")
        return self


class ApprovalGrantResult(ToolResult):
    spoken: str = ""
    approval_id: ApprovalId
    expires_at: UtcDatetime
    bound_to: ApprovalBinding
    granted_by: GrantedBy


class RecapItem(Contract):
    operation_id: OperationId
    action: Action
    outcome: Outcome
    observed_at: UtcDatetime
    summary: Text


class RecapResult(ToolResult):
    run_id: RunId | None
    items: list[RecapItem]
    generated_at: UtcDatetime
    timezone: Timezone = "America/Los_Angeles"


START_DESCRIPTION = (
    "RFC 3339 date-time with an explicit UTC offset in the user's timezone, for example "
    "2026-09-19T10:00:00-07:00. Must be later than the current time and within the next "
    "twelve months; never a bare date or a naive time."
)
END_DESCRIPTION = "RFC 3339 date-time with an explicit UTC offset; must be later than the start."
TIMEZONE_DESCRIPTION = "IANA timezone the user is scheduling in, for example America/Los_Angeles."
# Contract rules that may be quoted back to a model. Any other validator message stays private.
PUBLIC_RULES = frozenset(
    {
        "Unsupported identity prefix",
        "Unknown IANA timezone",
        "end must be after start",
        "start must be between now and twelve calendar months from now",
        "Exactly one of event_id and event_query is required",
    }
)
SUBMISSION_DESCRIPTION = (
    "New UUID for each user intent. Reuse the same value only when resending the identical "
    "request; a different intent always gets a new submission_id."
)
TITLE_DESCRIPTION = (
    "Short event title as the user would see it on the calendar, for example Plumber."
)
NOTES_DESCRIPTION = "Optional free-text notes stored with the event; omit when the user gave none."
EVENT_ID_DESCRIPTION = (
    "DoneWise event id from an earlier receipt, always evt_... (not a Google id). Give exactly "
    "one of event_id or event_query."
)
EVENT_QUERY_DESCRIPTION = (
    "Words from the event title to locate it, for example Plumber, when the event_id is unknown. "
    "Give exactly one of event_id or event_query."
)
RETRY_DESCRIPTION = (
    "Only when the user explicitly asks to retry an operation whose receipt was NOT_OBSERVED: "
    "the operation_id from that receipt. Never set it on your own initiative."
)
AMOUNT_DESCRIPTION = (
    "Amount in minor units of the currency as an integer greater than 0, for example 6000 for "
    "USD 60.00."
)
CURRENCY_DESCRIPTION = "ISO 4217 code in uppercase, for example USD."
PAYEE_DESCRIPTION = (
    "Name of the person or business the user wants to pay, as the user said it, for example "
    "Ridge Plumbing. It is recorded on the charge and read back in the receipt."
)
CONCEPT_DESCRIPTION = "What the payment is for, in a few words, for example deposit."
APPROVAL_DESCRIPTION = (
    "approval_id from the session backend after the user approved this exact charge. Omit on the "
    "first call; the receipt then says NEEDS_APPROVAL and the backend collects consent."
)
OPERATION_ID_DESCRIPTION = "operation_id from a receipt (op_...), used to read its current status."
RUN_ID_DESCRIPTION = (
    "Omit; the server derives the run from the session. Only set when given explicitly."
)


def check_window(start: datetime, end: datetime, info: ValidationInfo) -> None:
    if end <= start:
        raise ValueError("end must be after start")
    now = (info.context or {}).get("now", datetime.now(UTC))
    limit = now.replace(year=now.year + 1, day=min(now.day, monthrange(now.year + 1, now.month)[1]))
    if not now <= start <= limit:
        raise ValueError("start must be between now and twelve calendar months from now")


class CalendarCreateInput(Contract):
    submission_id: Annotated[Text, Field(description=SUBMISSION_DESCRIPTION)]
    title: Annotated[Text, Field(description=TITLE_DESCRIPTION)]
    start: Annotated[UtcDatetime, Field(description=START_DESCRIPTION)]
    end: Annotated[UtcDatetime, Field(description=END_DESCRIPTION)]
    timezone: Annotated[Timezone, Field(description=TIMEZONE_DESCRIPTION)]
    notes: Annotated[str | None, Field(description=NOTES_DESCRIPTION)] = None

    @model_validator(mode="after")
    def schedule(self, info: ValidationInfo) -> Self:
        check_window(self.start, self.end, info)
        return self


class CalendarRescheduleInput(Contract):
    submission_id: Annotated[Text, Field(description=SUBMISSION_DESCRIPTION)]
    event_id: Annotated[EventId | None, Field(description=EVENT_ID_DESCRIPTION)] = None
    event_query: Annotated[Text | None, Field(description=EVENT_QUERY_DESCRIPTION)] = None
    new_start: Annotated[UtcDatetime, Field(description=START_DESCRIPTION)]
    new_end: Annotated[UtcDatetime, Field(description=END_DESCRIPTION)]
    timezone: Annotated[Timezone, Field(description=TIMEZONE_DESCRIPTION)]
    retry_of_operation_id: Annotated[OperationId | None, Field(description=RETRY_DESCRIPTION)] = (
        None
    )

    @model_validator(mode="after")
    def schedule(self, info: ValidationInfo) -> Self:
        if (self.event_id is None) == (self.event_query is None):
            raise ValueError("Exactly one of event_id and event_query is required")
        check_window(self.new_start, self.new_end, info)
        return self


class PaymentChargeInput(Contract):
    submission_id: Annotated[Text, Field(description=SUBMISSION_DESCRIPTION)]
    amount_minor: Annotated[PositiveAmount, Field(description=AMOUNT_DESCRIPTION)]
    currency: Annotated[Currency, Field(description=CURRENCY_DESCRIPTION)]
    payee: Annotated[Text, Field(description=PAYEE_DESCRIPTION)]
    concept: Annotated[Text, Field(description=CONCEPT_DESCRIPTION)]
    approval_id: Annotated[ApprovalId | None, Field(description=APPROVAL_DESCRIPTION)] = None
    retry_of_operation_id: Annotated[OperationId | None, Field(description=RETRY_DESCRIPTION)] = (
        None
    )


class OperationGetInput(Contract):
    operation_id: Annotated[OperationId, Field(description=OPERATION_ID_DESCRIPTION)]


class ApprovalGrantInput(Contract):
    approval_request_id: Annotated[
        ApprovalId, Field(description="approval_request_id from the NEEDS_APPROVAL receipt.")
    ]
    consent_token: Annotated[
        Text,
        Field(
            repr=False, description="Consent capability held by the trusted UI, never by a model."
        ),
    ]


class ReceiptsRecapInput(Contract):
    run_id: Annotated[RunId | None, Field(description=RUN_ID_DESCRIPTION)] = None


class ToolSpec(Contract):
    name: str
    description: str
    input_model: type[Contract]
    output_model: type[ToolResult]


_GUIDANCE = (
    " Read spoken; for operation receipts read may_claim_success and only claim success when true."
    " Never retry a write on your own. Use operation_get when"
    " next_action = CHECK_EXISTING_OPERATION."
)
TOOL_SPECS = [
    ToolSpec(name=name, description=description + _GUIDANCE, input_model=inp, output_model=out)
    for name, description, inp, out in [
        (
            "calendar_create_verified",
            "Create a calendar event and verify it by reading it back.",
            CalendarCreateInput,
            CalendarCreateResult,
        ),
        (
            "calendar_reschedule_verified",
            "Move one calendar event to an absolute time and verify it.",
            CalendarRescheduleInput,
            CalendarRescheduleResult,
        ),
        (
            "payment_charge_verified",
            "Record one approved test charge and verify it by reading back.",
            PaymentChargeInput,
            PaymentChargeResult,
        ),
        (
            "operation_get",
            "Read an existing operation and its history; never initiate a write.",
            OperationGetInput,
            OperationView,
        ),
        (
            "approval_grant",
            "Grant consent bound to one payment using an out-of-model session token.",
            ApprovalGrantInput,
            ApprovalGrantResult,
        ),
        (
            "receipts_recap",
            "Summarize stored receipts with observation times; no provider reads/writes.",
            ReceiptsRecapInput,
            RecapResult,
        ),
    ]
]
