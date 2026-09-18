from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from donewise_adapters.stripe_test import StripeTest
from donewise_harness.clock import FakeClock
from donewise_harness.contracts import Action, PaymentTarget
from donewise_harness.errors import ReadUnavailable
from donewise_harness.ports import ReadRequest, WriteRequest


@pytest.fixture
def payment_req():
    return WriteRequest(
        action=Action.PAYMENT_CHARGE,
        provider_key="idem_abc",
        first_sent_at=datetime.now(UTC),
        precondition_version=None,
        target=PaymentTarget(
            amount_minor=100,
            currency="USD",
            payee="Ridge Plumbing",
            concept="deposit",
            status="succeeded",
        ),
    )


def payment(**changes):
    return {
        "id": "pi_test",
        "livemode": False,
        "amount": 100,
        "currency": "usd",
        "status": "succeeded",
        "metadata": {"intent_id": "idem_abc", "payee": "Ridge Plumbing", "concept": "deposit"},
        **changes,
    }


@pytest.mark.parametrize("key", ["sk_test_example", "rkcs_test_example"])
def test_payment_replay_read_and_search(payment_req, respx_mock, key):
    adapter = StripeTest(key, run_id="run_a")
    post = respx_mock.post("https://api.stripe.com/v1/payment_intents").respond(200, json=payment())
    assert adapter.write(payment_req).provider_ref == "pi_test"
    assert adapter.write(payment_req).status == "acked"
    assert post.calls[0].request.content == post.calls[1].request.content
    assert post.calls.last.request.headers["idempotency-key"] == "idem_abc"
    assert post.calls.last.request.headers["authorization"] == f"Bearer {key}"
    payload = parse_qs(post.calls.last.request.content.decode())
    assert payload["metadata[run_id]"] == ["run_a"] and payload["amount"] == ["100"]
    respx_mock.get("https://api.stripe.com/v1/payment_intents/pi_test").respond(200, json=payment())
    assert (
        adapter.read(ReadRequest(action=payment_req.action, provider_ref="pi_test")).observed
        == payment_req.target
    )
    search = respx_mock.get("https://api.stripe.com/v1/payment_intents/search").mock(
        side_effect=[
            httpx.Response(200, json={"data": [payment()], "has_more": True, "next_page": "two"}),
            httpx.Response(200, json={"data": [payment(id="pi_two")], "has_more": False}),
        ]
    )
    assert adapter.find_by_intent("idem_abc") == ["pi_test", "pi_two"]
    assert search.calls.last.request.url.params["page"] == "two"
    post.respond(400, json={"error": {"type": "idempotency_error"}})
    assert adapter.write(payment_req).status == "error"
    adapter.close()


@pytest.mark.parametrize(
    "key", ["sk_live_example", "rkcs_live_example", "pk_test_example", "rk_test_example", ""]
)
def test_test_keys_only(key):
    with pytest.raises(ValueError, match="sk_test_"):
        StripeTest(key)


@pytest.mark.parametrize("hours,safe", [(22.99, True), (23, False), (24, False), (-1, False)])
def test_replay_window(payment_req, hours, safe):
    adapter = StripeTest(
        "sk_test_x", clock=FakeClock(payment_req.first_sent_at + timedelta(hours=hours))
    )
    assert adapter.replay_is_safe(payment_req) is safe
    assert not adapter.replay_is_safe(payment_req.model_copy(update={"first_sent_at": None}))
    adapter.close()


def test_transport_and_read_failures(payment_req, respx_mock):
    adapter = StripeTest("sk_test_x")
    respx_mock.post("https://api.stripe.com/v1/payment_intents").mock(
        side_effect=httpx.ReadTimeout("lost")
    )
    assert adapter.write(payment_req).status == "response_lost"
    get = respx_mock.get("https://api.stripe.com/v1/payment_intents/pi_test").respond(503)
    req = ReadRequest(action=payment_req.action, provider_ref="pi_test")
    with pytest.raises(ReadUnavailable):
        adapter.read(req)
    get.respond(404)
    assert not adapter.read(req).found
    get.respond(200, json=payment(livemode=True))
    with pytest.raises(ReadUnavailable):
        adapter.read(req)
    adapter.close()
