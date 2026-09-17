"""Crash recovery, expiry and concurrency risks not covered by wire happy paths."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from donewise_harness.clock import FakeClock
from donewise_harness.contracts import FaultKind, Outcome
from donewise_harness.harness import Context
from donewise_harness.reconcile import Reconciler
from test_harness import (  # noqa: F401 -- shared week-one world fixtures
    CTX,
    NOW,
    World,
    approve,
    charge_input,
    create_input,
)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path, FakeClock(NOW))


def test_unknown_expiry_and_no_further_reads(world):
    h = world.harness
    world.faults.arm(FaultKind.READ_UNAVAILABLE, CTX.run_id, uses=30)
    receipt = h.calendar_create(create_input(), CTX)
    assert receipt.outcome == Outcome.UNKNOWN
    world.clock.advance(timedelta(hours=24).total_seconds())
    Reconciler(world.registry, h).run_once()
    expired = h.operation_get(receipt.operation_id, CTX)
    assert expired.reason_code == "RECONCILIATION_EXPIRED" and expired.next_action == "ASK_USER"
    before = world.calendar.read_calls
    Reconciler(world.registry, h).run_once()
    assert world.calendar.read_calls == before and world.calendar.write_calls == 1


@pytest.mark.parametrize("recoverable", [True, False])
def test_startup_pending_replay_window(world, recoverable):
    h = world.harness
    needed = h.payment_charge(charge_input(), CTX)
    approval = approve(world, needed)
    # Simulate process death after persisting the attempt but before writing.
    original = h._write
    h._write = lambda *args: (_ for _ in ()).throw(RuntimeError("process stopped"))
    with pytest.raises(RuntimeError):
        h.payment_charge(charge_input(approval_id=approval), CTX)
    h._write = original
    data = needed.model_dump(mode="json")
    data.update(
        outcome="PENDING",
        approval_request=None,
        approval_id=approval,
        next_action="CHECK_EXISTING_OPERATION",
        attempt_id=world.registry.attempts(needed.operation_id)[0]["attempt_id"],
    )
    # Persist the interrupted attempt with policy-consistent pending claims.
    from donewise_harness.contracts import claims_for

    data["allowed_claims"] = claims_for(Outcome.PENDING, needed.action)
    world.registry.insert_receipt(
        receipt_id="rcpt_crash",
        operation_id=needed.operation_id,
        attempt_id=data["attempt_id"],
        run_id=CTX.run_id,
        outcome="PENDING",
        receipt_json=json.dumps(data),
    )
    if not recoverable:
        world.clock.advance(timedelta(hours=23, minutes=1).total_seconds())
    restarted = World(world.tmp, world.clock)
    restarted.harness.recover_pending()
    status = restarted.harness.operation_get(needed.operation_id, CTX)
    if recoverable:
        assert status.outcome == "VERIFIED" and status.charges_applied == 1
        assert len(restarted.payments.intents()) == 1
        assert [a["kind"] for a in restarted.registry.attempts(needed.operation_id)] == [
            "write",
            "replay",
        ]
    else:
        assert status.outcome == "UNKNOWN" and status.reason_code == "REPLAY_WINDOW_EXPIRED"
        assert restarted.payments.write_calls == 0


def test_pending_deadline_late_finish_and_submission_deduplication(world):
    h = world.harness
    h.pending_after, h.background_timeout = 0.01, 0.04
    entered, release = threading.Event(), threading.Event()
    write = world.calendar.write

    def blocked(req):
        entered.set()
        assert release.wait(3)
        return write(req)

    world.calendar.write = blocked
    try:
        pending = h.calendar_create(create_input(), CTX)
        assert entered.is_set() and pending.outcome == "PENDING"
        duplicate = h.calendar_create(create_input(), CTX)
        assert duplicate.operation_id == pending.operation_id
        # Event-driven wait for the timeout receipt, with a bounded polling interval.
        for _ in range(100):
            row = world.registry.latest_receipt(pending.operation_id)
            if row["outcome"] == "UNKNOWN":
                break
            threading.Event().wait(0.01)
        assert row["outcome"] == "UNKNOWN"
    finally:
        release.set()
        h.wait_for_workers()
    final = h.operation_get(pending.operation_id, CTX)
    assert final.outcome == "VERIFIED" and world.calendar.write_calls == 1
    history = world.registry._all("SELECT outcome FROM receipts ORDER BY rowid")
    assert [r["outcome"] for r in history] == ["PENDING", "UNKNOWN", "VERIFIED"]


def test_parallel_runs_keep_faults_and_reset_separate(world):
    h = world.harness
    h.pending_after = 0.01
    a, b = Context("demo", "run_a"), Context("demo", "run_b")
    world.faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, a.run_id)
    with ThreadPoolExecutor(2) as pool:
        one = pool.submit(h.calendar_create, create_input("a"), a)
        two = pool.submit(h.calendar_create, create_input("b"), b)
        ra, rb = one.result(), two.result()
    h.wait_for_workers()
    ra, rb = h.operation_get(ra.operation_id, a), h.operation_get(rb.operation_id, b)
    assert ra.fault_injected == "drop_response_after_write" and rb.fault_injected is None
    assert ra.outcome == rb.outcome == "VERIFIED"
    assert {r["run_id"] for r in world.calendar.events().values()} == {a.run_id, b.run_id}
    assert len(world.calendar.search("the plumber")) == 1  # active run is b, not both demos
    world.calendar.reset_run(a.run_id)
    assert {r["run_id"] for r in world.calendar.events().values()} == {b.run_id}
    assert world.registry.latest_receipt(ra.operation_id) is not None
