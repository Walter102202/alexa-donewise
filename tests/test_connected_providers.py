"""Opt-in real sandbox smoke test. Run: uv run --env-file .env pytest -m connected."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from donewise_adapters.google_calendar import GoogleCalendar, google_event_id
from donewise_adapters.stripe_test import StripeTest
from donewise_harness.contracts import Action, CalendarTarget, PaymentTarget
from donewise_harness.ports import ReadRequest, WriteRequest


@pytest.mark.connected
def test_real_sandbox_create_read_cleanup():
    names = ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_CALENDAR_ID", "STRIPE_SECRET_KEY")
    if not all(os.getenv(name) for name in names):
        pytest.skip("Requires Google sandbox credentials and Stripe test key")
    payments = StripeTest(os.environ[names[2]])  # Validate before any network or Google mutation.
    calendar = GoogleCalendar(
        os.environ[names[0]], os.environ[names[1]], run_id="run_smoke_" + uuid4().hex
    )
    key = "evt_" + uuid4().hex
    start = datetime.now(UTC) + timedelta(days=1)
    target = CalendarTarget(
        calendar_id=calendar.calendar_id,
        event_id=key,
        title="DoneWise smoke",
        start=start,
        end=start + timedelta(hours=1),
        timezone="UTC",
        status="confirmed",
    )
    req = WriteRequest(
        action=Action.CALENDAR_CREATE,
        target=target,
        provider_key=key,
        first_sent_at=start - timedelta(days=1),
        precondition_version=None,
    )
    try:
        assert calendar.write(req).status == "acked"
        read = ReadRequest(action=req.action, provider_ref=key)
        assert calendar.read(read).observed == target
        moved = target.model_copy(
            update={"start": start + timedelta(hours=1), "end": start + timedelta(hours=2)}
        )
        patch = req.model_copy(
            update={
                "action": Action.CALENDAR_RESCHEDULE,
                "target": moved,
                "precondition_version": calendar.read(read).version,
            }
        )
        assert calendar.write(patch).status == "acked"
        assert calendar.write(patch).status == "precondition_failed"
        assert calendar.read(read).observed == moved
        charge = req.model_copy(
            update={
                "action": Action.PAYMENT_CHARGE,
                "provider_key": "idem_" + uuid4().hex,
                "target": PaymentTarget(
                    amount_minor=100,
                    currency="USD",
                    payee="DoneWise smoke",
                    concept="sandbox",
                    status="succeeded",
                ),
            }
        )
        result = payments.write(charge)
        assert result.status == "acked"
        assert (
            payments.read(
                ReadRequest(action=charge.action, provider_ref=result.provider_ref)
            ).observed
            == charge.target
        )
    finally:
        try:
            response = calendar.request("DELETE", calendar.events_path + "/" + google_event_id(key))
            assert response.status_code in (204, 404, 410)
        finally:
            calendar.close()
            payments.close()
