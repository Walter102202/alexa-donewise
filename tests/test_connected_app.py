import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from donewise_adapters.google_calendar import GoogleCalendar
from donewise_harness.clock import FakeClock
from donewise_harness.contracts import (
    ApprovalGrantInput,
    CalendarCreateInput,
    CalendarRescheduleInput,
    FaultKind,
    PaymentChargeInput,
)
from donewise_harness.harness import Context
from donewise_server.app import build_app
from donewise_server.config import Settings
from google.oauth2.credentials import Credentials
from starlette.testclient import TestClient


@pytest.fixture
def connected(tmp_path, monkeypatch, respx_mock):
    monkeypatch.setattr(
        "donewise_adapters.google_calendar.service_account.Credentials.from_service_account_info",
        lambda *args, **kwargs: Credentials("token"),
    )
    app = build_app(
        Settings(
            mode="connected",
            data_dir=tmp_path,
            google_service_account_json="{}",
            google_calendar_id="test@example.com",
            stripe_secret_key="sk_test_example",
            demo_admin_token="admin",
            pending_after=5,
        ),
        clock=FakeClock(datetime.now(UTC)),
    )
    events, payments, sent = {}, {}, []

    def provider(request):
        sent.append(request)
        key = request.url.path.rsplit("/", 1)[-1]
        is_calendar = "/calendars/" in request.url.path
        store = events if is_calendar else payments
        if request.method == "GET":
            return httpx.Response(200, json=store[key]) if key in store else httpx.Response(404)
        if is_calendar:
            body = json.loads(request.content)
            if request.method == "POST":
                if body["id"] in events:
                    return httpx.Response(409)
                events[body["id"]] = body | {"etag": '"v1"', "status": "confirmed"}
                return httpx.Response(200, json=events[body["id"]])
            assert request.headers["if-match"] == events[key]["etag"]
            events[key] |= body | {"etag": '"v2"'}
            return httpx.Response(200, json=events[key])
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        key = "pi_" + request.headers["idempotency-key"]
        row = {
            "id": key,
            "livemode": False,
            "amount": int(form["amount"]),
            "currency": form["currency"],
            "status": "succeeded",
            "metadata": {k[9:-1]: v for k, v in form.items() if k.startswith("metadata[")},
        }
        if key in payments:
            assert payments[key] == row  # Provider idempotency, not adapter memory.
        payments[key] = row
        return httpx.Response(200, json=row)

    respx_mock.route().mock(side_effect=provider)
    with TestClient(app) as client:
        yield app.state.harness, client, events, payments, sent
    assert app.state.harness.calendar.client.is_closed
    assert app.state.harness.payments.client.is_closed
    assert not (tmp_path / "calendar.json").exists()
    assert not (tmp_path / "payments.json").exists()


@pytest.mark.parametrize(
    "fault,outcome",
    [
        (None, "VERIFIED"),
        (FaultKind.DROP_RESPONSE_AFTER_WRITE, "VERIFIED"),
        (FaultKind.ACK_WITHOUT_WRITE, "NOT_OBSERVED"),
        (FaultKind.READ_UNAVAILABLE, "UNKNOWN"),
    ],
)
def test_connected_calendar_flow(connected, fault, outcome):
    h, client, events, _, sent = connected
    ctx = Context(user_id="demo", run_id="run_a")
    if fault:
        response = client.post(
            "/admin/faults",
            headers={"X-Demo-Admin-Token": "admin"},
            json={
                "kind": fault,
                "run_id": ctx.run_id,
                "uses": {"ack_without_write": 2, "read_unavailable": 3}.get(fault, 1),
            },
        )
        assert response.status_code == 200
    start = datetime.now(UTC) + timedelta(days=1)
    receipt = h.calendar_create(
        CalendarCreateInput(
            submission_id="one",
            title="Plumber",
            start=start,
            end=start + timedelta(hours=1),
            timezone="UTC",
        ),
        ctx,
    )
    assert receipt.outcome == outcome
    assert receipt.may_claim_success == (outcome == "VERIFIED")
    assert receipt.fault_injected == fault
    assert len(events) == (0 if fault == FaultKind.ACK_WITHOUT_WRITE else 1)
    if outcome == "VERIFIED":
        assert receipt.evidence.source == "google_calendar"
        assert receipt.observed.calendar_id == "test@example.com"
        assert next(iter(events.values()))["extendedProperties"]["private"]["run_id"] == "run_a"
        updated = h.calendar_reschedule(
            CalendarRescheduleInput(
                submission_id="move-ok",
                event_id=receipt.event_id,
                new_start=start + timedelta(hours=1),
                new_end=start + timedelta(hours=2),
                timezone="UTC",
            ),
            ctx,
        )
        assert updated.outcome == "VERIFIED" and updated.evidence.version == '"v2"'
        patches_before = sum(r.method == "PATCH" for r in sent)
        h.faults.arm(FaultKind.CONCURRENT_EDIT, ctx.run_id)
        moved = h.calendar_reschedule(
            CalendarRescheduleInput(
                submission_id="move",
                event_id=receipt.event_id,
                new_start=start + timedelta(hours=2),
                new_end=start + timedelta(hours=3),
                timezone="UTC",
            ),
            ctx,
        )
        assert moved.outcome == "NOT_OBSERVED" and moved.reason_code == "VERSION_CONFLICT"
        assert sum(r.method == "PATCH" for r in sent) == patches_before
    assert (
        client.post(
            "/admin/reset", headers={"X-Demo-Admin-Token": "admin"}, json={"run_id": ctx.run_id}
        ).status_code
        == 409
    )


def test_connected_payment_lost_response_replays_same_charge(connected):
    h, _, _, payments, sent = connected
    ctx = Context(user_id="demo", run_id="run_payment")
    inp = PaymentChargeInput(
        submission_id="pay",
        amount_minor=100,
        currency="USD",
        payee="Ridge Plumbing",
        concept="deposit",
    )
    needs = h.payment_charge(inp, ctx)
    approval = h.approval_grant(
        ApprovalGrantInput(
            approval_request_id=needs.approval_request.approval_request_id,
            consent_token=h.consent_token_for(ctx.run_id),
        ),
        ctx,
    )
    h.faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, ctx.run_id)
    result = h.payment_charge(inp.model_copy(update={"approval_id": approval.approval_id}), ctx)
    assert result.outcome == "VERIFIED" and result.evidence.source == "stripe_test"
    assert result.automatic_retries == 1 and len(payments) == 1
    posts = [r for r in sent if r.method == "POST"]
    assert len(posts) == 2 and posts[0].content == posts[1].content
    assert next(iter(payments.values()))["metadata"]["run_id"] == ctx.run_id


@pytest.mark.parametrize("mode", ["sandbox", "connected"])
def test_build_revalidates_key_before_any_state(tmp_path, mode):
    settings = Settings(
        mode=mode,
        data_dir=tmp_path / "new",
        google_service_account_json="{}",
        google_calendar_id="test",
        stripe_secret_key="sk_test_x",
    )
    settings.stripe_secret_key = "sk_live_mutated"
    with pytest.raises(ValueError, match="sk_test_"):
        build_app(settings)
    assert not settings.data_dir.exists()


@pytest.mark.parametrize("from_file", [False, True])
def test_service_account_refresh_over_httpx(tmp_path, respx_mock, from_file):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    raw = json.dumps(
        {
            "client_email": "demo@example.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
            "private_key": key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
        }
    )
    path = tmp_path / "account.json"
    path.write_text(raw)
    token = respx_mock.post("https://oauth2.googleapis.com/token").respond(
        200, json={"access_token": "refreshed", "expires_in": 3600, "token_type": "Bearer"}
    )
    adapter = GoogleCalendar(str(path) if from_file else raw, "test")
    try:
        assert adapter.headers()["authorization"] == "Bearer refreshed"
        assert adapter.headers()["authorization"] == "Bearer refreshed"
        assert token.call_count == 1
        assert b"assertion=" in token.calls.last.request.content
    finally:
        adapter.close()
