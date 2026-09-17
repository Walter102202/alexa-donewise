"""Small synchronous HTTP boundary shared by the provider adapters; no automatic retries."""

import time
from collections.abc import Callable

import httpx
from donewise_harness.clock import SystemClock
from donewise_harness.errors import ReadUnavailable
from donewise_harness.ports import ReadResult, WriteResult


class ProviderHTTP:
    def __init__(self, base_url, *, client=None, clock=None, run_id=None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=10, trust_env=False)
        self._owns_client = client is None
        self.clock = clock or SystemClock()
        self._run_id: str | Callable | None = run_id
        self.latencies: list[tuple[str, float]] = []

    @property
    def run_id(self):
        return self._run_id() if callable(self._run_id) else self._run_id

    def close(self):
        if self._owns_client:
            self.client.close()

    def headers(self):
        return {}

    def request(self, method, path, **kwargs):
        start = time.monotonic()
        try:
            headers = self.headers() | kwargs.pop("headers", {})
            return self.client.request(method, self.base_url + path, headers=headers, **kwargs)
        finally:
            self.latencies.append((method, time.monotonic() - start))

    def read_json(self, path, *, missing_ok=False, **kwargs):
        try:
            response = self.request("GET", path, headers={"Cache-Control": "no-cache"}, **kwargs)
            if missing_ok and response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            # Never expose provider bodies, credentials, or raw request URLs in receipts.
            raise ReadUnavailable(f"Provider read failed ({type(exc).__name__})") from None

    def observation(self, target, version=None):
        return ReadResult(
            found=target is not None,
            observed=target,
            version=version,
            observed_at=self.clock.now(),
            source=self.source,
        )

    @staticmethod
    def result(status, ref=None, version=None, error=None):
        return WriteResult(status=status, provider_ref=ref, version=version, error=error)

    def write_exception(self, exc):
        # Connect/pool failures precede transmission. Read/write failures may follow a mutation.
        lost = isinstance(
            exc,
            (
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.ReadError,
                httpx.WriteError,
                httpx.RemoteProtocolError,
            ),
        )
        return self.result("response_lost" if lost else "error", error=type(exc).__name__)
