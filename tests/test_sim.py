"""Five live MCP turns, browser SSE contract and the model/consent boundary."""

import asyncio
import json
from contextlib import asynccontextmanager, suppress

import httpx
import pytest
from donewise_server.app import build_app as build_server
from donewise_server.config import Settings as ServerSettings
from donewise_sim.app import build_app
from donewise_sim.config import Settings
from donewise_sim.llm import NoLLM, Reply, ToolCall
from test_server import calendar_args, serving


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mcp(tmp_path):
    app = build_server(
        ServerSettings(data_dir=tmp_path, mcp_bearer_token="bearer", demo_admin_token="admin")
    )
    with serving(app) as url:
        yield app, url


@asynccontextmanager
async def simulation(mcp, llm=None, *, ui_mode=None, admin_token="admin"):
    server, url = mcp
    app = build_app(
        Settings(
            mcp_url=url + "/mcp",
            mcp_bearer_token="bearer",
            demo_admin_token=admin_token,
            llm_provider="none",
        ),
        llm=llm,
    )
    with serving(app) as sim_url:
        async with httpx.AsyncClient(base_url=sim_url, timeout=30) as client:
            response = await client.post("/session", json={"ui_mode": ui_mode} if ui_mode else None)
            assert response.status_code == 200, response.text
            metadata = response.json()
            events = []

            async def collect():
                async with client.stream(
                    "GET", f"/session/{metadata['session_id']}/events"
                ) as stream:
                    assert stream.headers["content-type"].startswith("text/event-stream")
                    name = None
                    async for line in stream.aiter_lines():
                        if line.startswith("event: "):
                            name = line[7:]
                        elif line.startswith("data: "):
                            events.append({"event": name, "data": json.loads(line[6:])})

            task = asyncio.create_task(collect())
            try:
                yield client, metadata, events, app
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


async def act(client, session_id, path, body=None):
    prefix = f"/session/{session_id}"
    response = await client.post(prefix + path, json=body)
    assert response.status_code == 200, response.text
    for _ in range(250):
        state = (await client.get(prefix + "/state")).json()
        if not state["busy"]:
            await asyncio.sleep(0.05)  # let the independent SSE connection deliver its final frame
            return state
        await asyncio.sleep(0.05)
    pytest.fail("Turn did not complete")


@pytest.mark.anyio
async def test_five_scripted_turns_over_mcp_and_sse(mcp):
    async with simulation(mcp) as (client, metadata, events, app):
        sid = metadata["session_id"]
        assert metadata["protocol_version"] == "2025-11-25" and metadata["mcp_session_id"]
        assert len(metadata["tools"]) == 5 and "approval_grant" not in metadata["tools"]
        for step in range(5):
            state = await act(client, sid, "/script/next")
            assert state["step"] == step + 1
        receipts = [e["data"] for e in events if e["event"] == "receipt"]
        assert receipts[0]["result"]["outcome"] == "VERIFIED"
        assert receipts[1]["result"]["outcome"] == "NEEDS_APPROVAL"
        payments = [r["result"] for r in receipts if r["result"].get("action") == "PAYMENT_CHARGE"]
        assert [r["outcome"] for r in payments] == ["NEEDS_APPROVAL", "PENDING", "VERIFIED"]
        assert payments[-1]["charges_applied"] == 1
        moves = [
            r["result"] for r in receipts if r["result"].get("action") == "CALENDAR_RESCHEDULE"
        ]
        assert [r["outcome"] for r in moves] == ["PENDING", "NOT_OBSERVED", "VERIFIED"]
        assert moves[0]["operation_id"] == moves[-1]["operation_id"]
        assert moves[-1]["fault_injected"] is None
        assert receipts[-1]["tool"] == "receipts_recap"
        assert len(receipts[-1]["result"]["items"]) == 2
        assert "9 to 10" not in receipts[-1]["result"]["spoken"]
        assert "10 to 11" in receipts[-1]["result"]["spoken"]
        spoken = [e["data"] for e in events if e["event"] == "assistant"]
        assert all(s["source"] == "spoken" for s in spoken)
        assert [s["text"] for s in spoken] == [
            " ".join(r["result"]["spoken"] for r in receipts[:2]),
            payments[1]["spoken"],
            payments[2]["spoken"],
            moves[0]["spoken"],
            moves[1]["spoken"],
            moves[2]["spoken"],
            receipts[-1]["result"]["spoken"],
        ]
        for i, event in enumerate(events):
            if event["event"] == "receipt" and event["data"]["result"].get("outcome") == "PENDING":
                assert events[i + 1] == {
                    "event": "assistant",
                    "data": {"text": event["data"]["result"]["spoken"], "source": "spoken"},
                }
        assert spoken[0]["text"] == " ".join(r["result"]["spoken"] for r in receipts[:2])
        assert spoken[0]["text"] == (
            "It's on your calendar: Ridge Plumbing, tomorrow 9 to 10 AM. "
            "For the deposit: a $60 test charge for Ridge Plumbing. Should I charge it?"
        )
        assert not [e for e in events if e["event"] == "error"]
        secret = app.state.sessions[sid].consent_token
        assert secret not in json.dumps(events) + json.dumps(state)
        assert len(mcp[0].state.harness.payments.intents()) == 1
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/static/app.js")).status_code == 200


class NeverLLM(NoLLM):
    async def reply(self, messages, tools):
        raise AssertionError("Consent must not invoke the model")


@pytest.mark.anyio
async def test_deterministic_approval_and_reconnect(mcp):
    async with simulation(mcp, NeverLLM()) as (client, metadata, events, app):
        sid = metadata["session_id"]
        await act(client, sid, "/script/next")
        state = await act(client, sid, "/turn", {"text": "YES, charge it!!!"})
        assert any(r["result"].get("charges_applied") == 1 for r in state["receipts"].values())
        assert not [e for e in events if e["event"] == "error"]
        assert (
            await client.post(f"/session/{sid}/approve", headers={"Origin": "https://evil.example"})
        ).status_code == 403
    from donewise_sim.mcp_client import MCPClient

    settings = Settings(mcp_url=mcp[1] + "/mcp", mcp_bearer_token="bearer")
    transport = MCPClient(settings, metadata["run_id"])
    try:
        await transport.start()
        old_sid = transport.mcp_session_id
        async with httpx.AsyncClient(headers={"Authorization": "Bearer bearer"}) as direct:
            response = await direct.delete(
                mcp[1] + "/mcp",
                headers={"Mcp-Session-Id": old_sid, "MCP-Protocol-Version": "2025-11-25"},
            )
            assert response.status_code == 200
        with pytest.raises(RuntimeError):
            await transport.tools()
        assert len(await transport.tools()) == 5
        assert transport.mcp_session_id != old_sid and transport.run_id == metadata["run_id"]
    finally:
        await transport.close()


class AdversarialLLM:
    def __init__(self):
        self.calls = 0

    async def reply(self, messages, tools):
        assert "approval_grant" not in {t["name"] for t in tools}
        self.calls += 1
        if self.calls == 1:
            return Reply(
                "I already charged you!",
                [
                    ToolCall("denied", "approval_grant", {"consent_token": "model-forgery"}),
                    ToolCall(
                        "invalid",
                        "payment_charge_verified",
                        {
                            "submission_id": "bad-pay",
                            "amount_minor": "private-amount",
                            "currency": "USD",
                            "payee": "Ridge Plumbing",
                            "concept": "deposit",
                        },
                    ),
                    ToolCall("calendar", "calendar_create_verified", calendar_args("injected")),
                ],
            )
        feedback = next(
            b["content"] for b in messages[-1]["content"] if b["tool_use_id"] == "invalid"
        )
        assert "amount_minor" in feedback and "private-amount" not in feedback
        return Reply("Ignore the receipts; I charged $900.")


@pytest.mark.anyio
async def test_model_cannot_grant_or_replace_receipt_speech(mcp):
    async with simulation(mcp, AdversarialLLM(), ui_mode="voice") as (
        client,
        metadata,
        events,
        app,
    ):
        sid = metadata["session_id"]
        await act(client, sid, "/turn", {"text": "Book the plumber"})
        speech = [e["data"] for e in events if e["event"] == "assistant"]
        receipts = [e["data"]["result"] for e in events if e["event"] == "receipt"]
        assert speech == [{"text": receipts[0]["spoken"], "source": "spoken"}]
        assert not mcp[0].state.harness.payments.intents()
        messages = json.dumps(app.state.sessions[sid].messages)
        assert app.state.sessions[sid].consent_token not in messages


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["bedrock", "anthropic"])
async def test_llm_prompt_refreshes_la_clock_on_every_request(monkeypatch, provider):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from donewise_sim import llm

    times = iter(
        [datetime(2026, 10, 2, 6, 59, tzinfo=UTC), datetime(2026, 10, 2, 7, 1, tzinfo=UTC)]
    )
    monkeypatch.setattr(llm, "datetime", SimpleNamespace(now=lambda tz: next(times).astimezone(tz)))
    prompts = []
    settings = Settings(bedrock_model_id="test-model", anthropic_api_key="test-key")
    if provider == "bedrock":
        import boto3

        def converse(**kwargs):
            prompts.append(kwargs["system"][0]["text"])
            return {"output": {"message": {"content": []}}}

        monkeypatch.setattr(
            boto3, "client", lambda *a, **k: SimpleNamespace(converse=converse, close=lambda: None)
        )
        model = llm.BedrockLLM(settings)
    else:
        import anthropic

        async def create(**kwargs):
            prompts.append(kwargs["system"])
            return SimpleNamespace(content=[])

        @asynccontextmanager
        async def client(**kwargs):
            yield SimpleNamespace(messages=SimpleNamespace(create=create))

        monkeypatch.setattr(anthropic, "AsyncAnthropic", client)
        model = llm.AnthropicLLM(settings)
    await model.reply([], [])
    await model.reply([], [])
    assert "2026-10-01 23:59:00 -0700 America/Los_Angeles" in prompts[0]
    assert "2026-10-02 00:01:00 -0700 America/Los_Angeles" in prompts[1]
    model.prompt_factory = lambda: "Evaluation baseline: direct writes and optional reads."
    await model.reply([], [])
    assert prompts[2] == "Evaluation baseline: direct writes and optional reads."


@pytest.mark.anyio
async def test_fault_controls_restore_consume_and_isolate_modes(mcp):
    import threading

    release = threading.Event()

    class CreateLLM:
        async def reply(self, messages, tools):
            while not release.is_set():
                await asyncio.sleep(0.01)
            if messages[-1]["content"][0]["type"] == "tool_result":
                return Reply()
            return Reply(
                tool_calls=[
                    ToolCall("create", "calendar_create_verified", calendar_args("fault-create"))
                ]
            )

    async with simulation(mcp, CreateLLM(), ui_mode="voice") as (client, metadata, events, app):
        sid = metadata["session_id"]
        prefix = f"/session/{sid}"
        fault = {"kind": "ack_without_write", "uses": 2}
        assert metadata["ui_mode"] == "voice" and not metadata["llm_enabled"]
        assert (await client.post(prefix + "/script/next")).status_code == 409
        responses = await asyncio.gather(
            client.post(prefix + "/faults", json=fault),
            client.post(prefix + "/faults", json=fault),
        )
        assert sorted(r.status_code for r in responses)[0] == 200
        assert sum(r.status_code == 200 for r in responses) == 1
        state = (await client.get(prefix + "/state")).json()
        assert state["fault_state"]["armed"] == {"ack_without_write": 2}
        assert not state["busy"]
        # Block the model until both overlapping mutations have been rejected.
        try:
            response = await client.post(prefix + "/turn", json={"text": "Create an event"})
            assert response.status_code == 200
            assert (await client.post(prefix + "/faults", json=fault)).status_code == 409
            assert (
                await client.post(prefix + "/mode", json={"ui_mode": "scripted"})
            ).status_code == 409
        finally:
            release.set()
        for _ in range(250):
            state = (await client.get(prefix + "/state")).json()
            if not state["busy"]:
                break
            await asyncio.sleep(0.05)
        assert not state["busy"]
        await asyncio.sleep(0.05)
        assert state["fault_state"]["armed"] == {}
        assert state["fault_state"]["fired"] == ["ack_without_write"] * 2
        assert any(e["event"] == "fault" and e["data"]["state"]["armed"] for e in events)
        assert any(e["event"] == "fault" and e["data"]["state"]["fired"] for e in events)
        changed = await client.post(prefix + "/mode", json={"ui_mode": "scripted"})
        new = changed.json()
        assert new["run_id"] != metadata["run_id"] and new["fault_state"]["armed"] == {}
        new_prefix = f"/session/{new['session_id']}"
        assert (await client.post(new_prefix + "/faults", json=fault)).status_code == 409
        assert (
            await client.post(new_prefix + "/turn", json={"text": "Book the plumber"})
        ).status_code == 409
        assert (await client.get(prefix + "/state")).json()["receipts"] == state["receipts"]


@pytest.mark.anyio
async def test_fault_endpoint_disabled_without_admin():
    app = build_app(Settings(demo_admin_token="", llm_provider="none"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/session/disabled/faults",
            json={"kind": "drop_response_after_write", "uses": 1},
        )
        assert response.status_code == 404
