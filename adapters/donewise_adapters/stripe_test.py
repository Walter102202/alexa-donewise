"""Stripe PaymentIntent REST adapter, strictly restricted to test keys."""

import re
from datetime import timedelta
from urllib.parse import quote

from donewise_harness.contracts import Action, EvidenceSource, PaymentTarget
from donewise_harness.errors import ReadUnavailable

from .provider_http import ProviderHTTP


class StripeTest(ProviderHTTP):
    source = EvidenceSource.STRIPE_TEST

    def __init__(self, secret_key, *, base_url="https://api.stripe.com", **kwargs):
        if not secret_key.startswith("sk_test_"):
            raise ValueError("Stripe requires a sk_test_ key; real money is forbidden")
        super().__init__(base_url, **kwargs)
        self._secret_key = secret_key

    def headers(self):
        return {"Authorization": f"Bearer {self._secret_key}"}

    def write(self, req):
        try:
            target = req.target
            if req.action != Action.PAYMENT_CHARGE or not isinstance(target, PaymentTarget):
                raise ValueError("Not a payment")
            response = self.request(
                "POST",
                "/v1/payment_intents",
                headers={"Idempotency-Key": req.provider_key},
                data={
                    "amount": target.amount_minor,
                    "currency": target.currency.lower(),
                    "payment_method": "pm_card_visa",
                    "payment_method_types[]": "card",
                    "confirm": "true",
                    "metadata[intent_id]": req.provider_key,
                    "metadata[run_id]": self.run_id or "",
                    "metadata[payee]": target.payee,
                    "metadata[concept]": target.concept,
                    "description": target.concept,
                },
            )
            if not response.is_success:
                return self.result("error", error=f"Stripe HTTP {response.status_code}")
            row = response.json()
            if not row["id"].startswith("pi_") or row.get("livemode") is not False:
                raise ValueError("Invalid test PaymentIntent")
            return self.result("acked", row["id"])
        except Exception as exc:
            return self.write_exception(exc)

    def read(self, req):
        if not req.provider_ref:
            raise ReadUnavailable("Payment read requires provider_ref")
        row = self.read_json(
            "/v1/payment_intents/" + quote(req.provider_ref, safe=""), missing_ok=True
        )
        if row is None:
            return self.observation(None)
        try:
            if row["id"] != req.provider_ref or row.get("livemode") is not False:
                raise ValueError("Invalid test PaymentIntent")
            target = PaymentTarget(
                amount_minor=row["amount"],
                currency=row["currency"].upper(),
                payee=row["metadata"]["payee"],
                concept=row["metadata"]["concept"],
                status=row["status"],
            )
            return self.observation(target)
        except (ValueError, KeyError, TypeError):
            raise ReadUnavailable("Invalid PaymentIntent response") from None

    def replay_is_safe(self, req):
        return req.action == Action.PAYMENT_CHARGE and (
            req.first_sent_at is not None
            and timedelta(0) <= self.clock.now() - req.first_sent_at < timedelta(hours=23)
        )

    def find_by_intent(self, intent_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", intent_id):
            raise ValueError("Invalid intent identity")
        params = {"query": f"metadata['intent_id']:'{intent_id}'"}
        hits = []
        while True:
            page = self.read_json("/v1/payment_intents/search", params=params)
            for row in page["data"]:
                if row.get("livemode") is not False:
                    raise ReadUnavailable("Unexpected live PaymentIntent")
                if row["metadata"].get("intent_id") == intent_id:
                    hits.append(row["id"])
            if not page.get("has_more"):
                return hits
            if not page.get("next_page"):
                raise ReadUnavailable("Incomplete Stripe search pagination")
            params["page"] = page["next_page"]
