"""RF-42 local HTTP transport proxy. Faults never modify upstream requests.

This in-process proxy avoids an unauthenticated listening port. It wraps a real HTTP
transport, consumes the harness's context-local run, and passes through all unaffected
requests. concurrent_edit simulates a 412, without editing any real provider event.
"""

import json
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
from donewise_harness.contracts import FaultKind


class FaultProxy(httpx.BaseTransport):
    def __init__(self, faults, upstream=None):
        self.faults = faults
        self.upstream = upstream or httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        is_write = request.method in ("POST", "PATCH")
        if request.method == "GET" and self.faults.consume_active(FaultKind.READ_UNAVAILABLE):
            return httpx.Response(503, json={"error": "Injected read unavailable"}, request=request)
        if request.method == "PATCH" and self.faults.consume_active(FaultKind.CONCURRENT_EDIT):
            return httpx.Response(412, json={"error": "Injected version conflict"}, request=request)
        if is_write and self.faults.consume_active(FaultKind.ACK_WITHOUT_WRITE):
            if request.url.path == "/v1/payment_intents":
                data = parse_qs(request.content.decode())
                body = {
                    "id": "pi_injected_" + uuid4().hex,
                    "livemode": False,
                    "amount": int(data["amount"][0]),
                    "currency": data["currency"][0],
                    "status": "succeeded",
                }
            else:
                body = json.loads(request.content)
                body |= {
                    "id": body.get("id", request.url.path.rsplit("/", 1)[-1]),
                    "etag": '"injected"',
                    "status": "confirmed",
                }
            return httpx.Response(200, json=body, request=request)
        drop = is_write and self.faults.consume_active(FaultKind.DROP_RESPONSE_AFTER_WRITE)
        response = self.upstream.handle_request(request)
        if drop:
            # Wait for the actual upstream response so the mutation really had a chance to land.
            try:
                response.read()
            finally:
                response.close()
            raise httpx.ReadError("Injected response loss after upstream write", request=request)
        return response

    def close(self):
        self.upstream.close()
