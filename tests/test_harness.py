"""Acceptance cases T06–T12 (PRD §8) against the Fake adapters."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from donewise_adapters.fake_calendar import FakeCalendar
from donewise_adapters.fake_payments import FakePayments
from donewise_harness.clock import FakeClock
from donewise_harness.contracts import (
    ApprovalGrantInput,
    CalendarCreateInput,
    CalendarRescheduleInput,
    Claim,
    FaultKind,
    NextAction,
    Outcome,
    PaymentChargeInput,
    ReasonCode,
)
from donewise_harness.faults import FaultBoard
from donewise_harness.harness import Context, Harness
from donewise_harness.registry import Registry, RegistryUnavailable
from pydantic import ValidationError

NOW = datetime(2026, 9, 17, 2, 39, tzinfo=UTC)  # 7:39 PM Los Angeles
START = datetime(2026, 9, 17, 16, 0, tzinfo=UTC)  # 9 AM Los Angeles
CTX = Context(user_id="clara", run_id="run_test")
TOKEN = "consent-secret"


class World:
    """One process: registry, adapters and harness sharing files under tmp_path."""

    def __init__(self, tmp_path: Path, clock: FakeClock, window: timedelta = timedelta(hours=24)):
        self.tmp = tmp_path
        self.clock = clock
        self.faults = FaultBoard()
        self.registry = Registry(tmp_path / "registry.sqlite", clock=clock)
        self.calendar = FakeCalendar(tmp_path / "calendar.json", faults=self.faults, clock=clock)
        self.payments = FakePayments(
            tmp_path / "payments.json", faults=self.faults, clock=clock, idempotency_window=window
        )
        self.harness = Harness(
            registry=self.registry,
            calendar=self.calendar,
            payments=self.payments,
            faults=self.faults,
            clock=clock,
            consent_token_for=lambda _: TOKEN,
        )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def world(tmp_path: Path, clock: FakeClock) -> World:
    return World(tmp_path, clock)


def create_input(submission_id: str = "sub-create", **overrides) -> CalendarCreateInput:
    data = {
        "submission_id": submission_id,
        "title": "Ridge Plumbing",
        "start": START,
        "end": START + timedelta(hours=1),
        "timezone": "America/Los_Angeles",
    }
    data.update(overrides)
    return CalendarCreateInput.model_validate(data, context={"now": NOW})


def move_input(
    event_id: str, submission_id: str = "sub-move", **overrides
) -> CalendarRescheduleInput:
    data = {
        "submission_id": submission_id,
        "event_id": event_id,
        "new_start": START + timedelta(hours=1),
        "new_end": START + timedelta(hours=2),
        "timezone": "America/Los_Angeles",
    }
    data.update(overrides)
    return CalendarRescheduleInput.model_validate(data, context={"now": NOW})


def charge_input(submission_id: str = "sub-pay", **overrides) -> PaymentChargeInput:
    data = {
        "submission_id": submission_id,
        "amount_minor": 6000,
        "currency": "USD",
        "payee": "Ridge Plumbing",
        "concept": "deposit",
    }
    data.update(overrides)
    return PaymentChargeInput.model_validate(data)


def approve(world: World, receipt) -> str:
    grant = world.harness.approval_grant(
        ApprovalGrantInput(
            approval_request_id=receipt.approval_request.approval_request_id,
            consent_token=TOKEN,
        ),
        CTX,
    )
    return grant.approval_id


# T06 — happy path


def test_t06_create_verified_after_matching_read_back(world: World):
    receipt = world.harness.calendar_create(create_input(), CTX)

    assert receipt.outcome == Outcome.VERIFIED
    assert receipt.may_claim_success is True
    assert receipt.writes_applied == 1
    assert receipt.observed == receipt.expected
    assert receipt.evidence is not None and receipt.evidence.source == "fake_calendar"
    assert receipt.receipt_id is not None
    assert receipt.spoken == "It's on your calendar: Ridge Plumbing, tomorrow 9 to 10 AM."
    # Independent oracle: the sandbox file, not the verifier.
    assert world.calendar.events()[receipt.event_id]["title"] == "Ridge Plumbing"
    assert world.registry.latest_receipt(receipt.operation_id)["receipt_id"] == receipt.receipt_id


def test_t06_payment_verified_once_with_approval(world: World):
    first = world.harness.payment_charge(charge_input(), CTX)
    assert first.outcome == Outcome.NEEDS_APPROVAL
    approval_id = approve(world, first)

    receipt = world.harness.payment_charge(charge_input(approval_id=approval_id), CTX)

    assert receipt.outcome == Outcome.VERIFIED
    assert receipt.charges_applied == 1
    assert Claim.CHARGED_ONCE in receipt.allowed_claims
    assert receipt.payment_intent_id is not None
    assert len(world.payments.intents()) == 1
    assert receipt.spoken.startswith(
        "Done: a $60 test charge is recorded for Ridge Plumbing's deposit"
    )


# T07 — favourable ack without write


def test_t07_ack_without_write_is_not_observed(world: World):
    world.faults.arm(FaultKind.ACK_WITHOUT_WRITE, CTX.run_id, uses=2)

    receipt = world.harness.calendar_create(create_input(), CTX)

    assert receipt.outcome == Outcome.NOT_OBSERVED
    assert receipt.may_claim_success is False
    assert receipt.writes_applied == 0
    assert receipt.automatic_retries == 1
    assert receipt.reason_code == ReasonCode.REPLAY_BUDGET_EXHAUSTED
    assert receipt.fault_injected == FaultKind.ACK_WITHOUT_WRITE
    assert receipt.event_id not in world.calendar.events()
    # Three spaced reads inside the 5 s window, recorded per attempt.
    attempts = world.registry.attempts(receipt.operation_id)
    assert len(attempts) == 2
    for attempt in attempts:
        reads = world.registry.observations(receipt.operation_id, attempt["attempt_id"])
        assert len(reads) == 3
        first, last = reads[0]["observed_at"], reads[-1]["observed_at"]
        assert (
            0 < (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() <= 5
        )


def test_rf16_single_ack_fault_recovers_by_automatic_replay(world: World):
    world.faults.arm(FaultKind.ACK_WITHOUT_WRITE, CTX.run_id)

    receipt = world.harness.calendar_create(create_input(), CTX)

    assert receipt.outcome == Outcome.VERIFIED
    assert receipt.automatic_retries == 1
    assert receipt.writes_applied == 1
    assert receipt.fault_injected == FaultKind.ACK_WITHOUT_WRITE


# T08 — write applied, response lost


def test_t08_calendar_response_lost_recovered_by_replay(world: World):
    world.faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, CTX.run_id)

    receipt = world.harness.calendar_create(create_input(), CTX)

    assert receipt.outcome == Outcome.VERIFIED
    assert receipt.reason_code == ReasonCode.WRITE_RESPONSE_LOST_RECOVERED
    assert receipt.writes_applied == 1
    assert receipt.automatic_retries == 1
    assert len(world.calendar.events()) == 1
    assert world.calendar.write_calls == 2  # original + one replay with the same id


def test_t08_payment_response_lost_recovered_charged_once(world: World):
    first = world.harness.payment_charge(charge_input(), CTX)
    approval_id = approve(world, first)
    world.faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, CTX.run_id)

    receipt = world.harness.payment_charge(charge_input(approval_id=approval_id), CTX)

    assert receipt.outcome == Outcome.VERIFIED
    assert receipt.reason_code == ReasonCode.WRITE_RESPONSE_LOST_RECOVERED
    assert receipt.charges_applied == 1
    assert len(world.payments.intents()) == 1
    assert receipt.spoken.endswith("You don't need to try again.")


def test_t08_payment_outside_window_never_resends(tmp_path: Path, clock: FakeClock):
    world = World(tmp_path, clock, window=timedelta(0))
    first = world.harness.payment_charge(charge_input(), CTX)
    approval_id = approve(world, first)
    world.faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, CTX.run_id)

    receipt = world.harness.payment_charge(charge_input(approval_id=approval_id), CTX)

    assert receipt.outcome == Outcome.UNKNOWN
    assert receipt.reason_code == ReasonCode.REPLAY_WINDOW_EXPIRED
    assert receipt.next_action == NextAction.CHECK_EXISTING_OPERATION
    assert receipt.automatic_retries == 0
    assert world.payments.write_calls == 1
    assert len(world.payments.intents()) == 1  # the charge happened; we just cannot prove it yet


# T09 — uncertain write, read unavailable


def test_t09_unknown_then_resolved_by_later_observation(world: World):
    world.faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, CTX.run_id)
    world.faults.arm(FaultKind.READ_UNAVAILABLE, CTX.run_id, uses=3)

    receipt = world.harness.calendar_create(create_input(), CTX)

    assert receipt.outcome == Outcome.UNKNOWN
    assert receipt.reason_code == ReasonCode.READ_TIMEOUT
    assert receipt.may_claim_success is False
    assert receipt.observed is None
    assert receipt.next_action == NextAction.CHECK_EXISTING_OPERATION

    later = world.harness.operation_get(receipt.operation_id, CTX)

    assert later.outcome == Outcome.VERIFIED
    assert later.writes_applied == 1
    assert len(world.calendar.events()) == 1
    # Append-only: the UNKNOWN verdict is still there.
    outcomes = [v["outcome"] for v in world.registry.verdicts(receipt.operation_id)]
    assert outcomes[0] == "UNKNOWN" and outcomes[-1] == "VERIFIED"


# T10 — wrong target, zone or date


def test_t10_invalid_zone_and_past_start_are_rejected_by_validation():
    with pytest.raises(ValidationError):
        create_input(timezone="America/Nowhere")
    with pytest.raises(ValidationError):
        create_input(start=NOW - timedelta(days=1), end=NOW)


def test_t10_unknown_event_needs_input_and_writes_nothing(world: World):
    receipt = world.harness.calendar_reschedule(move_input("evt_missing"), CTX)

    assert receipt.outcome == Outcome.NEEDS_INPUT
    assert receipt.reason_code == ReasonCode.AMBIGUOUS_TARGET
    assert receipt.writes_applied == 0
    assert world.calendar.write_calls == 0


def test_t10_verdict_rejects_ack_with_wrong_time(world: World):
    created = world.harness.calendar_create(create_input(), CTX)
    world.calendar.corrupt_next_write(minutes=30)  # provider applies a different time

    receipt = world.harness.calendar_reschedule(move_input(created.event_id), CTX)

    assert receipt.outcome == Outcome.NOT_OBSERVED
    assert receipt.may_claim_success is False
    assert receipt.observed is not None and receipt.observed.start != receipt.expected.start


# T11 — double submission and process restart


def test_t11_same_submission_resumes_same_intent_without_double_effect(world: World):
    first = world.harness.calendar_create(create_input(), CTX)
    second = world.harness.calendar_create(create_input(), CTX)

    assert second.operation_id == first.operation_id
    assert second.intent_id == first.intent_id
    assert second.outcome == Outcome.VERIFIED
    assert world.calendar.write_calls == 1
    assert len(world.calendar.events()) == 1


def test_t11_retry_of_verified_move_returns_receipt_without_another_write(world: World):
    created = world.harness.calendar_create(create_input(), CTX)
    moved = world.harness.calendar_reschedule(move_input(created.event_id), CTX)
    retried = world.harness.calendar_reschedule(
        move_input(created.event_id, retry_of_operation_id=moved.operation_id), CTX
    )
    assert retried == moved
    assert world.calendar.write_calls == 2  # create + move, never a third write
    assert len(world.registry.attempts(moved.operation_id)) == 1


def test_t11_same_intent_with_different_payload_is_rejected(world: World):
    world.harness.calendar_create(create_input(), CTX)

    receipt = world.harness.calendar_create(create_input(title="Dentist"), CTX)

    assert receipt.outcome == Outcome.REJECTED
    assert receipt.reason_code == ReasonCode.IDEMPOTENCY_PAYLOAD_MISMATCH
    assert world.calendar.write_calls == 1


def test_t11_resubmitted_payment_returns_state_not_approval_used(world: World):
    first = world.harness.payment_charge(charge_input(), CTX)
    approval_id = approve(world, first)
    paid = world.harness.payment_charge(charge_input(approval_id=approval_id), CTX)

    again = world.harness.payment_charge(charge_input(approval_id=approval_id), CTX)

    assert again.operation_id == paid.operation_id
    assert again.outcome == Outcome.VERIFIED
    assert again.reason_code != ReasonCode.APPROVAL_USED
    assert len(world.payments.intents()) == 1

    other = world.harness.payment_charge(
        charge_input(submission_id="sub-pay-2", approval_id=approval_id), CTX
    )
    assert other.outcome == Outcome.REJECTED
    assert other.reason_code == ReasonCode.APPROVAL_USED
    assert len(world.payments.intents()) == 1


def test_t11_two_workers_claim_same_operation_one_wins(world: World):
    assert world.registry.claim("op_shared", worker_id="w1") is True
    assert world.registry.claim("op_shared", worker_id="w2") is False


def test_t11_process_restart_resumes_without_second_write(tmp_path: Path, clock: FakeClock):
    before = World(tmp_path, clock)
    first = before.harness.calendar_create(create_input(), CTX)

    after = World(tmp_path, clock)  # new process: same files, fresh objects
    second = after.harness.calendar_create(create_input(), CTX)

    assert second.operation_id == first.operation_id
    assert second.outcome == Outcome.VERIFIED
    assert after.calendar.write_calls == 0
    assert len(after.calendar.events()) == 1


# T12 — concurrent edit


def test_t12_concurrent_edit_respects_precondition_and_asks(world: World):
    created = world.harness.calendar_create(create_input(), CTX)
    world.faults.arm(FaultKind.CONCURRENT_EDIT, CTX.run_id)

    receipt = world.harness.calendar_reschedule(move_input(created.event_id), CTX)

    assert receipt.outcome == Outcome.NOT_OBSERVED
    assert receipt.reason_code == ReasonCode.VERSION_CONFLICT
    assert receipt.next_action == NextAction.ASK_USER
    assert receipt.writes_applied == 0
    assert receipt.observed is not None
    assert receipt.observed.start != receipt.expected.start  # the other edit survived
    assert receipt.spoken.startswith("Your calendar changed since I last looked.")


# Registry down (RF-29, part of T16 exercised early)


def test_registry_down_before_intent_executes_nothing(world: World):
    world.faults.arm(FaultKind.REGISTRY_DOWN, CTX.run_id)

    with pytest.raises(RegistryUnavailable):
        world.harness.calendar_create(create_input(), CTX)
    assert world.calendar.write_calls == 0


# Codex review of week 1 (17-sep): three sequences that were not covered


def test_t11_rejected_payload_does_not_replace_verified_state(world: World):
    first = world.harness.calendar_create(create_input(), CTX)
    rejected = world.harness.calendar_create(create_input(title="Dentist"), CTX)
    again = world.harness.calendar_create(create_input(), CTX)

    assert rejected.outcome == Outcome.REJECTED
    assert rejected.operation_id != first.operation_id
    assert again.outcome == Outcome.VERIFIED and again.operation_id == first.operation_id
    view = world.harness.operation_get(first.operation_id, CTX)
    assert view.outcome == Outcome.VERIFIED and view.expected.title == "Ridge Plumbing"


def test_t08_payment_outside_window_reconciles_by_durable_identity(tmp_path, clock):
    world = World(tmp_path, clock, window=timedelta(0))
    approval_id = approve(world, world.harness.payment_charge(charge_input(), CTX))
    world.faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, CTX.run_id)
    unknown = world.harness.payment_charge(charge_input(approval_id=approval_id), CTX)
    assert unknown.outcome == Outcome.UNKNOWN

    view = world.harness.operation_get(unknown.operation_id, CTX)

    assert view.outcome == Outcome.VERIFIED
    assert view.reason_code == ReasonCode.WRITE_RESPONSE_LOST_RECOVERED
    assert view.charges_applied == 1 and view.payment_intent_id is not None
    assert world.payments.write_calls == 1  # never a second request
    assert len(world.payments.intents()) == 1


def test_t08_reschedule_response_lost_is_recovered_not_a_conflict(world: World):
    created = world.harness.calendar_create(create_input(), CTX)
    world.faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, CTX.run_id)

    receipt = world.harness.calendar_reschedule(move_input(created.event_id), CTX)

    assert receipt.outcome == Outcome.VERIFIED
    assert receipt.reason_code == ReasonCode.WRITE_RESPONSE_LOST_RECOVERED
    assert receipt.writes_applied == 1 and receipt.automatic_retries == 1
    assert receipt.observed == receipt.expected
    assert (
        receipt.spoken == "Ridge Plumbing is now at 10 to 11 AM. I read it back from your calendar."
    )
