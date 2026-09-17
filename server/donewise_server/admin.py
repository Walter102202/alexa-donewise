"""Admin capability is separate from the MCP/model surface."""

import hmac
import json

import anyio
from donewise_harness.contracts import FaultKind, RunId
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse


class RunInput(BaseModel):
    run_id: RunId


class FaultInput(RunInput):
    kind: FaultKind
    uses: int = Field(default=1, ge=1, strict=True)


def register_admin(server, settings, harness):
    def denied(request):
        if not settings.demo_admin_token:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if not hmac.compare_digest(
            request.headers.get("x-demo-admin-token", "").encode(),
            settings.demo_admin_token.encode(),
        ):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

    @server.custom_route("/healthz", methods=["GET"])
    async def health(request: Request):
        await anyio.to_thread.run_sync(harness.registry._one, "SELECT 1")
        return JSONResponse(
            {
                "mode": settings.mode,
                "protocol_versions": list(HANDSHAKE_PROTOCOL_VERSIONS),
                "registry": "ok",
            }
        )

    @server.custom_route("/admin/consent-token", methods=["POST"])
    async def consent(request: Request):
        if response := denied(request):
            return response
        try:
            data = RunInput.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError):
            return JSONResponse({"error": "Invalid run_id"}, status_code=400)
        return JSONResponse({"consent_token": settings.consent_token_for(data.run_id)})

    @server.custom_route("/admin/faults", methods=["POST", "GET"])
    async def faults(request: Request):
        if response := denied(request):
            return response
        try:
            if request.method == "POST":
                data = FaultInput.model_validate(await request.json())
                harness.faults.arm(data.kind, data.run_id, data.uses)
            else:
                data = RunInput.model_validate(dict(request.query_params))
        except (ValidationError, json.JSONDecodeError):
            return JSONResponse({"error": "Invalid fault request"}, status_code=400)
        return JSONResponse(
            {"armed": harness.faults.armed(data.run_id), "fired": harness.faults.fired(data.run_id)}
        )

    @server.custom_route("/admin/reset", methods=["POST"])
    async def reset(request: Request):
        if response := denied(request):
            return response
        if settings.mode == "connected":
            return JSONResponse(
                {"error": "Reset is sandbox-only; connected provider evidence is retained"},
                status_code=409,
            )
        try:
            data = RunInput.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError):
            return JSONResponse({"error": "Invalid run_id"}, status_code=400)
        # Do not delete an oracle underneath a still-running verification.
        active = any(
            worker.is_alive() and harness.registry.operation(op_id)["run_id"] == data.run_id
            for op_id, worker in list(harness._workers.items())
        )
        if active:
            return JSONResponse({"error": "Run still has active operations"}, status_code=409)
        await anyio.to_thread.run_sync(harness.calendar.reset_run, data.run_id)
        await anyio.to_thread.run_sync(harness.payments.reset_run, data.run_id)
        return JSONResponse({"run_id": data.run_id, "reset": True})
