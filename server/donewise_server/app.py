"""Stateful Streamable HTTP server for the DoneWise sandbox."""

import hmac
import json
import logging
from contextlib import asynccontextmanager

import anyio
import uvicorn
from donewise_adapters.fake_calendar import FakeCalendar
from donewise_adapters.fake_payments import FakePayments
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

        async def capture(message):
            nonlocal session_id, is_json
            if message["type"] == "http.response.start":
                response_headers = Headers(raw=message["headers"])
                session_id = response_headers.get("mcp-session-id")
                is_json = "application/json" in response_headers.get("content-type", "")
            elif message["type"] == "http.response.body" and session_id and is_json:
                body.extend(message.get("body", b""))
                if not message.get("more_body"):
                    try:
                        result = json.loads(body).get("result", {})
                        version = result.get("protocolVersion")
                    except (ValueError, AttributeError):
                        version = None
                    if version:
                        await anyio.to_thread.run_sync(
                            self.registry.record_protocol, session_id, version
                        )
            await send(message)

        await self.app(scope, receive, capture)


def build_app(settings: Settings) -> Starlette:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    registry = Registry(settings.data_dir / "registry.sqlite")
    faults = FaultBoard()
    if settings.mode == "connected":
        logger.warning("Connected configuration validated; using Fake adapters until step 1")
    harness = Harness(
        registry=registry,
        calendar=FakeCalendar(settings.data_dir / "calendar.json", faults=faults),
        payments=FakePayments(
            settings.data_dir / "payments.json",
            faults=faults,
            delay_seconds=settings.fake_payment_delay_seconds,
        ),
        faults=faults,
        consent_token_for=settings.consent_token_for,
        pending_after=settings.pending_after,
    )
    reconciler = Reconciler(registry, harness)
    server = MCPServer("DoneWise", tools=make_tools(harness))
    register_resources(server, registry)
    register_admin(server, settings, harness)
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
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
        await anyio.to_thread.run_sync(harness.recover_pending)
        await anyio.to_thread.run_sync(reconciler.run_once)
        async with sdk_lifespan(app):
            async with anyio.create_task_group() as group:
                group.start_soon(reconcile_loop)
                try:
                    yield
                finally:
                    group.cancel_scope.cancel()
        await anyio.to_thread.run_sync(harness.wait_for_workers)

    app.router.lifespan_context = lifespan
    app.add_middleware(BearerMiddleware, token=settings.mcp_bearer_token, registry=registry)
    app.state.harness = harness
    app.state.mcp_server = server
    app.state.settings = settings
    return app


def main():
    settings = Settings()
    uvicorn.run(build_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
