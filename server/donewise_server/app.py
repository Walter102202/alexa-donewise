"""Stateful Streamable HTTP server for the DoneWise sandbox."""

import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import timedelta

import anyio
import uvicorn
from donewise_adapters.fake_calendar import FakeCalendar
from donewise_adapters.fake_payments import FakePayments
from donewise_adapters.fault_proxy import FaultProxy
from donewise_adapters.google_calendar import GoogleCalendar
from donewise_adapters.stripe_test import StripeTest
from donewise_harness.faults import FaultBoard
from donewise_harness.harness import Harness
from donewise_harness.reconcile import Reconciler
from donewise_harness.registry import Registry
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from .admin import register_admin
from .config import Settings
from .local import HTTP_LOOP
from .resources import register_resources
from .tools import make_tools

logger = logging.getLogger(__name__)


class BearerMiddleware:
    def __init__(self, app, token: str, registry: Registry):
        self.app, self.token, self.registry = app, token, registry

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].rstrip("/") != "/mcp":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if self.token and not hmac.compare_digest(
            headers.get("authorization", "").encode(), ("Bearer " + self.token).encode()
        ):
            response = JSONResponse(
                {"error": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            return await response(scope, receive, send)
        session_id = None
        body = bytearray()
        is_json = False
        is_sse = False

        async def record(payload):
            try:
                version = json.loads(payload).get("result", {}).get("protocolVersion")
            except (ValueError, AttributeError):
                return
            if version:
                await anyio.to_thread.run_sync(self.registry.record_protocol, session_id, version)

        async def capture(message):
            nonlocal session_id, is_json, is_sse
            if message["type"] == "http.response.start":
                response_headers = Headers(raw=message["headers"])
                session_id = response_headers.get("mcp-session-id")
                is_json = "application/json" in response_headers.get("content-type", "")
                is_sse = "text/event-stream" in response_headers.get("content-type", "")
            elif message["type"] == "http.response.body" and session_id and (is_json or is_sse):
                body.extend(message.get("body", b""))
                if is_sse:
                    while b"\n" in body:
                        line, _, rest = body.partition(b"\n")
                        body[:] = rest
                        if line.startswith(b"data:"):
                            await record(line[5:].strip())
                elif not message.get("more_body"):
                    await record(body)
            await send(message)

        await self.app(scope, receive, capture)


def build_app(settings: Settings, *, clock=None, payment_window=timedelta(hours=24)) -> Starlette:
    # Settings is mutable: revalidate immediately before constructing any provider or state.
    settings.__post_init__()
    faults = FaultBoard()
    if settings.mode == "connected":
        payments = StripeTest(
            settings.stripe_secret_key,
            clock=clock,
            run_id=lambda: faults.active_run,
            transport=FaultProxy(faults),
        )
        try:
            calendar = GoogleCalendar(
                settings.google_service_account_json,
                settings.google_calendar_id,
                clock=clock,
                run_id=lambda: faults.active_run,
                transport=FaultProxy(faults),
            )
        except Exception:
            payments.close()
            raise
    else:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        calendar = FakeCalendar(settings.data_dir / "calendar.json", faults=faults, clock=clock)
        payments = FakePayments(
            settings.data_dir / "payments.json",
            faults=faults,
            delay_seconds=settings.fake_payment_delay_seconds,
            clock=clock,
            idempotency_window=payment_window,
        )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    registry = Registry(settings.data_dir / "registry.sqlite", clock=clock)
    harness = Harness(
        registry=registry,
        calendar=calendar,
        payments=payments,
        calendar_id=settings.google_calendar_id
        if settings.mode == "connected"
        else "sandbox_calendar",
        faults=faults,
        consent_token_for=settings.consent_token_for,
        pending_after=settings.pending_after,
        clock=clock,
    )
    reconciler = Reconciler(registry, harness)
    server = MCPServer("DoneWise", tools=make_tools(harness))
    register_resources(server, registry)
    register_admin(server, settings, harness)
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=False,
        host=settings.host,
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(
                dict.fromkeys(
                    [
                        "127.0.0.1:*",
                        "localhost:*",
                        settings.host,
                        f"{settings.host}:*",
                    ]
                )
            ),
            allowed_origins=settings.allowed_origins,
        ),
    )
    sdk_lifespan = app.router.lifespan_context

    async def reconcile_loop():
        while True:
            await anyio.sleep(30)
            try:
                await anyio.to_thread.run_sync(reconciler.run_once)
            except Exception:
                logger.exception("Reconciliation pass failed; will retry")

    @asynccontextmanager
    async def lifespan(app):
        try:
            await anyio.to_thread.run_sync(harness.recover_pending)
            await anyio.to_thread.run_sync(reconciler.run_once)
            async with sdk_lifespan(app):
                async with anyio.create_task_group() as group:
                    group.start_soon(reconcile_loop)
                    try:
                        yield
                    finally:
                        group.cancel_scope.cancel()
        finally:
            await anyio.to_thread.run_sync(harness.wait_for_workers)
            if settings.mode == "connected":
                calendar.close()
                payments.close()

    app.router.lifespan_context = lifespan
    app.add_middleware(BearerMiddleware, token=settings.mcp_bearer_token, registry=registry)
    app.state.harness = harness
    app.state.mcp_server = server
    app.state.settings = settings
    return app


def main():
    settings = Settings()
    uvicorn.run(build_app(settings), host=settings.host, port=settings.port, loop=HTTP_LOOP)


if __name__ == "__main__":
    main()
