"""Wire acceptance with the official SDK, real TCP and persisted fake oracles."""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import httpx2
import pytest
from donewise_harness.contracts import TOOL_SPECS, CalendarCreateResult
from donewise_server.app import build_app
from donewise_server.config import Settings
from donewise_server.local import serving
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "key,google", [("sk_live_example", True), ("", True), ("sk_test_x", False)]
)
def test_connected_configuration_fails_closed(key, google):
    with pytest.raises(ValueError):
        Settings(
            mode="connected",
            stripe_secret_key=key,
            google_service_account_json="sandbox.json" if google else "",
            google_calendar_id="sandbox" if google else "",
        )


@pytest.fixture
def live(tmp_path):
    app = build_app(
        Settings(data_dir=tmp_path, mcp_bearer_token="bearer", demo_admin_token="admin")
    )
    with serving(app) as url:
        yield app, url


def calendar_args(submission="calendar-1"):
    start = datetime.now(UTC) + timedelta(days=1)
    return {
        "submission_id": submission,
        "title": "Ridge Plumbing",
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "timezone": "America/Los_Angeles",
    }


@pytest.mark.anyio
async def test_official_client_contract_and_pending(live):
    app, url = live
    h = app.state.harness
    captured = []

    async def trace(response):
        if response.headers.get("mcp-session-id") and response.headers.get(
            "content-type", ""
        ).startswith("application/json"):
            await response.aread()
            if response.content:
                captured.append((response.headers.get("mcp-session-id"), response.json()))

    async with httpx2.AsyncClient(
        headers={
            "Authorization": "Bearer bearer",
            "Origin": "http://127.0.0.1:8080",
            "X-DoneWise-Run-Id": "run_wire",
            "X-Demo-Admin-Token": "admin",
        },
        event_hooks={"response": [trace]},
    ) as client:
        async with streamable_http_client(url + "/mcp", http_client=client) as streams:
            async with ClientSession(*streams) as session:
                init = await session.initialize()
                assert init.protocol_version == "2025-11-25"
                sid, wire = captured[0]
                assert sid and wire["result"]["protocolVersion"] == "2025-11-25"
                assert h.registry._one("SELECT * FROM protocol_sessions")["protocol_version"] == (
                    "2025-11-25"
                )
                tools = (await session.list_tools()).tools
                assert len(tools) == 6
                for tool in tools:
                    schema = json.loads(Path(f"docs/schemas/{tool.name}.input.json").read_text())
                    assert tool.input_schema == schema
                    spec = next(s for s in TOOL_SPECS if s.name == tool.name)
                    assert tool.description == spec.description and tool.output_schema
                result = await session.call_tool("calendar_create_verified", calendar_args())
                assert not result.is_error
                receipt = CalendarCreateResult.model_validate(result.structured_content)
                assert receipt.outcome == "VERIFIED"
                spoken, text_json = result.content[0].text.split("\n\n", 1)
                assert (
                    spoken == receipt.spoken and json.loads(text_json) == result.structured_content
                )
                resource = await session.read_resource(
                    f"receipts://operation/{receipt.operation_id}"
                )
                assert json.loads(resource.contents[0].text) == result.structured_content
                pay = {
                    "submission_id": "pay-1",
                    "amount_minor": 6000,
                    "currency": "USD",
                    "payee": "Ridge Plumbing",
                    "concept": "deposit",
                }
                needs = await session.call_tool("payment_charge_verified", pay)
                assert (
                    not needs.is_error and needs.structured_content["outcome"] == "NEEDS_APPROVAL"
                )
                request = needs.structured_content["approval_request"]["approval_request_id"]
                bad = await session.call_tool(
                    "approval_grant",
                    {"approval_request_id": request, "consent_token": "wrong-secret"},
                )
                assert bad.is_error and "UNAUTHORIZED" in bad.content[0].text
                assert "wrong-secret" not in bad.content[0].text
                missing = await session.call_tool(
                    "approval_grant", {"approval_request_id": request}
                )
                assert missing.is_error and "UNAUTHORIZED" in missing.content[0].text
                invalid = await session.call_tool(
                    "approval_grant",
                    {"approval_request_id": "invalid", "consent_token": "do-not-echo"},
                )
                assert invalid.is_error and "do-not-echo" not in invalid.content[0].text
                assert "approval_request_id" in invalid.content[0].text
                invalid = await session.call_tool(
                    "payment_charge_verified",
                    {
                        **pay,
                        "amount_minor": "secret-amount",
                        "currency": "secret-currency",
                        "secret-extra-key": "secret-value",
                    },
                )
                assert invalid.is_error
                assert "amount_minor" in invalid.content[0].text
                assert "currency" in invalid.content[0].text
                assert "secret" not in invalid.content[0].text
                token = (
                    await client.post(url + "/admin/consent-token", json={"run_id": "run_wire"})
                ).json()["consent_token"]
                grant = await session.call_tool(
                    "approval_grant", {"approval_request_id": request, "consent_token": token}
                )
                pay["approval_id"] = grant.structured_content["approval_id"]
                await client.post(
                    url + "/admin/faults",
                    json={"run_id": "run_wire", "kind": "drop_response_after_write"},
                )
                h.payments.delay_seconds = 0.65
                started = time.monotonic()
                pending = await session.call_tool("payment_charge_verified", pay)
                assert time.monotonic() - started < 0.5
                assert not pending.is_error and pending.structured_content["outcome"] == "PENDING"
                op_id = pending.structured_content["operation_id"]
                for _ in range(50):
                    status = await session.call_tool("operation_get", {"operation_id": op_id})
                    if status.structured_content["outcome"] != "PENDING":
                        break
                    await anyio.sleep(0.05)
                assert status.structured_content["outcome"] == "VERIFIED"
                assert status.structured_content["charges_applied"] == 1
                assert status.structured_content["fault_injected"] == "drop_response_after_write"
                assert len(json.loads(h.payments.path.read_text())["intents"]) == 1
                await client.post(
                    url + "/admin/faults", json={"run_id": "run_wire", "kind": "registry_down"}
                )
                before = h.calendar.write_calls
                bad = await session.call_tool("calendar_create_verified", calendar_args("down"))
                assert bad.is_error and h.calendar.write_calls == before
                headers = {"Mcp-Session-Id": sid, "Accept": "application/json, text/event-stream"}
                msg = {"jsonrpc": "2.0", "id": 99, "method": "tools/list", "params": {}}
                invalid = await client.post(
                    url + "/mcp",
                    json=msg,
                    headers={**headers, "MCP-Protocol-Version": "1999-01-01"},
                )
                assert invalid.status_code == 400
                # Missing protocol header takes the SDK's specified legacy default.
                assert (
                    await client.post(url + "/mcp", json=msg, headers=headers)
                ).status_code == 200
                assert (await client.delete(url + "/mcp", headers=headers)).status_code == 200
                assert (
                    await client.post(url + "/mcp", json=msg, headers=headers)
                ).status_code == 404


@pytest.mark.anyio
async def test_http_security_and_run_reset(live, tmp_path):
    app, url = live
    async with httpx2.AsyncClient() as client:
        for auth in (None, "Bearer wrong"):
            response = await client.post(
                url + "/mcp", headers={"Authorization": auth} if auth else {}
            )
            assert response.status_code == 401
        bad_origin = await client.post(
            url + "/mcp",
            json={},
            headers={"Authorization": "Bearer bearer", "Origin": "https://evil.example"},
        )
        assert bad_origin.status_code == 403
        assert (await client.get(url + "/healthz")).json()["registry"] == "ok"
        assert (
            await client.post(url + "/admin/reset", json={"run_id": "run_a"})
        ).status_code == 401
        assert (await client.get(url + "/admin/faults?run_id=run_a")).status_code == 401
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer bearer"}) as client:
        async with streamable_http_client(url + "/mcp", http_client=client) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                receipt = await session.call_tool("calendar_create_verified", calendar_args())
                sid = app.state.harness.registry._one("SELECT * FROM protocol_sessions")[
                    "session_id"
                ]
                run_id = "run_" + sid.replace("-", "")
                assert receipt.structured_content["run_id"] == run_id
                reset = await client.post(
                    url + "/admin/reset",
                    json={"run_id": run_id},
                    headers={"X-Demo-Admin-Token": "admin"},
                )
                assert reset.status_code == 200 and not app.state.harness.calendar.events()
                assert app.state.harness.registry.latest_receipts_for_run(run_id)
    no_admin = build_app(Settings(data_dir=tmp_path / "disabled", demo_admin_token=""))
    with serving(no_admin) as other:
        async with httpx2.AsyncClient() as client:
            assert (await client.post(other + "/admin/reset", json={})).status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("budget,expected", [("off", "VERIFIED"), ("0.45", "PENDING")])
async def test_pending_budget_over_mcp(tmp_path, monkeypatch, budget, expected):
    monkeypatch.setenv("DONEWISE_PENDING_AFTER", budget)
    app = build_app(
        Settings(data_dir=tmp_path, demo_admin_token="admin", fake_payment_delay_seconds=0.8)
    )
    h = app.state.harness
    with serving(app) as url:
        async with streamable_http_client(url + "/mcp") as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                pay = {
                    "submission_id": "sync",
                    "amount_minor": 100,
                    "currency": "USD",
                    "payee": "Ridge Plumbing",
                    "concept": "deposit",
                }
                needs = (await session.call_tool("payment_charge_verified", pay)).structured_content
                grant = await session.call_tool(
                    "approval_grant",
                    {
                        "approval_request_id": needs["approval_request"]["approval_request_id"],
                        "consent_token": h.consent_token_for(needs["run_id"]),
                    },
                )
                result = await session.call_tool(
                    "payment_charge_verified",
                    pay | {"approval_id": grant.structured_content["approval_id"]},
                )
                assert result.structured_content["outcome"] == expected
                await anyio.to_thread.run_sync(h.wait_for_workers)
                op_id = result.structured_content["operation_id"]
                polled = await session.call_tool("operation_get", {"operation_id": op_id})
                assert polled.structured_content["outcome"] == "VERIFIED"
                pending = h.registry._one(
                    "SELECT * FROM receipts WHERE operation_id = ? AND outcome = 'PENDING'", op_id
                )
                assert (pending is None) == (budget == "off")


@pytest.mark.parametrize("budget", ["-1", "nan", "inf", "invalid"])
def test_invalid_pending_budget(monkeypatch, budget):
    monkeypatch.setenv("DONEWISE_PENDING_AFTER", budget)
    with pytest.raises(ValueError):
        Settings()
