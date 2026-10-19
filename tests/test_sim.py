"""Five live MCP turns, browser SSE contract and the model/consent boundary."""

import asyncio
import json
from contextlib import asynccontextmanager, suppress

import httpx
import pytest
from donewise_server.app import build_app as build_server
from donewise_server.config import Settings as ServerSettings
from donewise_sim import agent as agent_module
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
        ServerSettings(
            data_dir=tmp_path,
            mcp_bearer_token="bearer",
            demo_admin_token="admin",
            # Wide budget so slow CI runners keep fast writes synchronous; the Fake payment
            # delay stays above it so the PENDING path is still exercised.
            pending_after=2.0,
            fake_payment_delay_seconds=3.0,
        )
    )
    with serving(app) as url:
        yield app, url


@asynccontextmanager
async def simulation(
    mcp, llm=None, *, ui_mode=None, admin_token="admin", user_timezone="America/Los_Angeles"
):
    server, url = mcp
    app = build_app(
        Settings(
            mcp_url=url + "/mcp",
            mcp_bearer_token="bearer",
            demo_admin_token=admin_token,
            llm_provider="none",
            user_timezone=user_timezone,
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
        assert metadata["model_label"] == "Model: off · scripted inputs"
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
        assert payments[-1]["granted_by"] == "session_ui"
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


class PastHourLLM:
    """Asks for a past hour, reads the rule, asks the user, then books what the user chose."""

    QUESTION = "8:00 a.m. today has already passed. Which time would you like instead?"

    def __init__(self):
        self.calls = 0
        self.feedback = ""

    async def reply(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            past = calendar_args("past") | {
                "start": "2020-09-18T08:00:00-07:00",
                "end": "2020-09-18T09:00:00-07:00",
            }
            return Reply("", [ToolCall("past", "calendar_create_verified", past)])
        if self.calls == 2:
            self.feedback = messages[-1]["content"][0]["content"]
            return Reply(self.QUESTION)
        if self.calls == 3:
            assert messages[-2]["content"][0]["text"] == self.QUESTION  # question kept in history
            return Reply("", [ToolCall("ok", "calendar_create_verified", calendar_args("ok"))])
        return Reply("Done, I booked it.")  # never spoken: the receipt is


@pytest.mark.anyio
async def test_rejected_write_shows_the_question_and_writes_only_after_the_answer(mcp):
    llm = PastHourLLM()
    async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, app):
        sid = metadata["session_id"]
        await act(client, sid, "/turn", {"text": "Schedule an appointment for today at 8 a.m."})
        assert "start must be between now and twelve calendar months from now" in llm.feedback
        assert "ask the user first" in llm.feedback and "2020-09-18" not in llm.feedback
        assert llm.calls == 2
        assert [e["data"] for e in events if e["event"] == "assistant"] == [
            {"text": PastHourLLM.QUESTION, "source": "model"}
        ]
        assert not [e for e in events if e["event"] == "receipt"]
        assert not mcp[0].state.harness.calendar.events()
        assert app.state.sessions[sid].messages[-1] == {
            "role": "assistant",
            "content": [{"type": "text", "text": PastHourLLM.QUESTION}],
        }

        await act(client, sid, "/turn", {"text": "Tomorrow at 8 a.m. then"})
        receipts = [e["data"]["result"] for e in events if e["event"] == "receipt"]
        assert len(receipts) == 1 and receipts[0]["outcome"] == "VERIFIED"
        speech = [e["data"] for e in events if e["event"] == "assistant"]
        assert speech[-1] == {"text": receipts[0]["spoken"], "source": "spoken"}
        assert "Done, I booked it." not in json.dumps(speech)


class OneCallLLM:
    """Calls one tool with fixed arguments (ids included), then answers in prose."""

    def __init__(self, tool, arguments):
        self.tool, self.arguments = tool, arguments
        self.seen_tools = None
        self.calls = 0

    async def reply(self, messages, tools):
        self.seen_tools = tools
        self.calls += 1
        if self.calls == 1:
            return Reply("", [ToolCall("one", self.tool, dict(self.arguments))])
        return Reply("Anything else?")


INVENTED = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"  # the kind of "UUID" a model repeats


@pytest.mark.anyio
async def test_model_tools_hide_backend_owned_ids(mcp):
    llm = OneCallLLM("calendar_create_verified", calendar_args("ignored") | {"title": "Plumber"})
    async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, app):
        await act(client, metadata["session_id"], "/turn", {"text": "Book the plumber"})
        assert llm.seen_tools
        for tool in llm.seen_tools:
            schema = tool["input_schema"]
            assert "submission_id" not in schema["properties"], tool["name"]
            assert "approval_id" not in schema["properties"], tool["name"]
            assert "submission_id" not in schema.get("required", []), tool["name"]
        # The server contract itself is untouched.
        server_tools = {
            t.name: t for t in await app.state.sessions[metadata["session_id"]].client.tools()
        }
        assert "submission_id" in server_tools["calendar_create_verified"].input_schema["required"]


@pytest.mark.anyio
async def test_same_invented_submission_id_in_two_sessions_creates_two_events(mcp):
    for title in ("Plumber", "Dentist"):
        args = calendar_args("x") | {"submission_id": INVENTED, "title": title}
        llm = OneCallLLM("calendar_create_verified", args)
        async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, app):
            await act(client, metadata["session_id"], "/turn", {"text": "Book " + title})
            receipts = [e["data"]["result"] for e in events if e["event"] == "receipt"]
            assert [r["outcome"] for r in receipts] == ["VERIFIED"], receipts
            assert receipts[0]["expected"]["title"] == title
    titles = sorted(row["title"] for row in mcp[0].state.harness.calendar.events().values())
    assert titles == ["Dentist", "Plumber"]


@pytest.mark.anyio
async def test_invented_approval_id_does_not_skip_consent(mcp):
    args = {
        "submission_id": INVENTED,
        "amount_minor": 6000,
        "currency": "USD",
        "payee": "Ridge Plumbing",
        "concept": "deposit",
        "approval_id": "apr_made_up_by_the_model",
    }
    llm = OneCallLLM("payment_charge_verified", args)
    async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, app):
        sid = metadata["session_id"]
        state = await act(client, sid, "/turn", {"text": "Pay the deposit"})
        receipts = [e["data"]["result"] for e in events if e["event"] == "receipt"]
        assert [r["outcome"] for r in receipts] == ["NEEDS_APPROVAL"], receipts
        assert state["pending_approval"]
        await act(client, sid, "/turn", {"text": "yes"})
        receipts = [e["data"]["result"] for e in events if e["event"] == "receipt"]
        assert receipts[-1]["outcome"] == "VERIFIED"
        assert len(mcp[0].state.harness.payments.intents()) == 1


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
            prompts.append(kwargs["system"])
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
    texts = [" ".join(block["text"] for block in system) for system in prompts]
    assert "2026-10-01 23:59:00 -0700 America/Los_Angeles" in texts[0]
    assert "2026-10-02 00:01:00 -0700 America/Los_Angeles" in texts[1]
    # Static block first and identical across requests; the clock lives in the last block.
    assert prompts[0][0]["text"] == prompts[1][0]["text"]
    assert "Today is" in prompts[0][-1]["text"] and "Today is" not in prompts[0][0]["text"]
    if provider == "anthropic":
        assert prompts[0][0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in prompts[0][-1]
    else:
        assert all(set(block) == {"text"} for block in prompts[0])
    model.prompt_factory = lambda: "Evaluation baseline: direct writes and optional reads."
    await model.reply([], [])
    assert [b["text"] for b in prompts[2]] == [
        "Evaluation baseline: direct writes and optional reads."
    ]
    assert "cache_control" not in prompts[2][0]


@pytest.mark.anyio
@pytest.mark.parametrize("stop_reason", ["tool_use", "max_tokens", "guardrail_intervened"])
async def test_bedrock_tool_results_metrics_and_incomplete_response(monkeypatch, stop_reason):
    from types import SimpleNamespace

    import boto3
    from donewise_sim.llm import BedrockLLM

    requests = []

    def converse(**request):
        requests.append(request)
        return {
            "stopReason": stop_reason,
            "usage": {"inputTokens": 12, "outputTokens": 5},
            "output": {
                "message": {
                    "content": [
                        {"toolUse": {"toolUseId": "recap", "name": "receipts_recap", "input": {}}}
                    ]
                }
            },
        }

    monkeypatch.setattr(
        boto3, "client", lambda *a, **k: SimpleNamespace(converse=converse, close=lambda: None)
    )
    model = BedrockLLM(Settings(bedrock_model_id="us.amazon.nova-pro-v1:0"))
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "old",
                    "content": "invalid input",
                    "is_error": True,
                }
            ],
        }
    ]
    if stop_reason != "tool_use":
        with pytest.raises(RuntimeError, match="no tools executed"):
            await model.reply(messages, [])
    else:
        reply = await model.reply(messages, [])
        assert reply.tool_calls[0].name == "receipts_recap"
        assert reply.metadata["usage"]["inputTokens"] == 12
        assert reply.metadata["latency_ms"] >= 0
    assert requests[0]["messages"][0]["content"][0]["toolResult"]["status"] == "error"
    assert "additionalModelRequestFields" not in requests[0]
    assert "toolConfig" not in requests[0]


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


@pytest.mark.parametrize("zone", ["America/Los_Angeles", "America/Santiago"])
def test_sim_user_timezone_accepts_the_two_demo_zones(zone):
    assert Settings(user_timezone=zone).user_timezone == zone


def test_sim_user_timezone_rejects_other_zones():
    with pytest.raises(ValueError, match="USER_TIMEZONE"):
        Settings(user_timezone="Europe/Madrid")


def test_system_prompt_follows_the_user_timezone(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from donewise_sim import llm

    fixed = datetime(2026, 10, 2, 7, 1, tzinfo=UTC)
    monkeypatch.setattr(llm, "datetime", SimpleNamespace(now=lambda tz: fixed.astimezone(tz)))
    santiago = " ".join(b["text"] for b in llm.system_prompt("America/Santiago"))
    assert "2026-10-02 04:01:00 -0300 America/Santiago" in santiago
    assert "America/Los_Angeles" not in santiago
    default = " ".join(b["text"] for b in llm.system_prompt())
    assert "2026-10-02 00:01:00 -0700 America/Los_Angeles" in default


@pytest.mark.anyio
async def test_session_metadata_and_script_follow_the_user_timezone(mcp):
    from donewise_sim.scripted import next_step

    async with simulation(mcp, ui_mode="scripted", user_timezone="America/Santiago") as (
        client,
        metadata,
        events,
        app,
    ):
        assert metadata["timezone"] == "America/Santiago"
        session = app.state.sessions[metadata["session_id"]]
        await next_step(session)
        assert session.script_args["create"]["timezone"] == "America/Santiago"
        assert session.script_args["move"]["timezone"] == "America/Santiago"
        assert session.script_args["create"]["start"].endswith("+00:00")


@pytest.mark.anyio
async def test_timezone_toggle_restarts_the_session_and_reaches_the_recap(mcp):
    async with simulation(mcp, ui_mode="scripted") as (client, metadata, events, app):
        assert metadata["timezone"] == "America/Los_Angeles"
        prefix = f"/session/{metadata['session_id']}"
        changed = await client.post(
            prefix + "/mode", json={"ui_mode": "scripted", "timezone": "America/Santiago"}
        )
        assert changed.status_code == 200, changed.text
        new = changed.json()
        assert new["timezone"] == "America/Santiago" and new["run_id"] != metadata["run_id"]
        session = app.state.sessions[new["session_id"]]
        assert session.timezone == "America/Santiago"
        assert session.client.timezone == "America/Santiago"
        recap = await session.execute("receipts_recap", {})
        assert recap["timezone"] == "America/Santiago"
        # Mode changes keep the selected timezone; an unknown zone is rejected before any session.
        kept = await client.post(f"/session/{new['session_id']}/mode", json={"ui_mode": "scripted"})
        assert kept.json()["timezone"] == "America/Santiago"
        bad = await client.post("/session", json={"ui_mode": "scripted", "timezone": "UTC"})
        assert bad.status_code == 422


@pytest.mark.anyio
async def test_scripted_step_can_be_retried_after_approve_fails_once(mcp, monkeypatch):
    from donewise_sim.session import Session

    original = Session.approve
    calls = {"n": 0}

    async def flaky(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated lost response during approval")
        return await original(self)

    monkeypatch.setattr(Session, "approve", flaky)
    async with simulation(mcp) as (client, metadata, events, app):
        sid = metadata["session_id"]
        assert (await act(client, sid, "/script/next"))["step"] == 1
        state = await act(client, sid, "/script/next")  # arms the fault, approve fails
        assert state["step"] == 1
        assert state["fault_state"]["armed"] == {"drop_response_after_write": 1}
        state = await act(client, sid, "/script/next")  # retry: must not re-arm
        assert state["step"] == 2
        assert state["fault_state"]["armed"] == {}
        assert state["fault_state"]["fired"] == ["drop_response_after_write"]
        payments = [
            e["data"]["result"]
            for e in events
            if e["event"] == "receipt" and e["data"]["result"].get("action") == "PAYMENT_CHARGE"
        ]
        assert payments[-1]["outcome"] == "VERIFIED" and payments[-1]["charges_applied"] == 1
        assert len([e for e in events if e["event"] == "error"]) == 1


@pytest.mark.anyio
async def test_expired_approval_clears_pending_and_says_so(mcp):
    from datetime import timedelta

    from donewise_harness.clock import SystemClock

    class Shifted(SystemClock):
        def now(self):
            return super().now() + timedelta(minutes=6)

    async with simulation(mcp) as (client, metadata, events, app):
        sid = metadata["session_id"]
        assert (await act(client, sid, "/script/next"))["step"] == 1
        mcp[0].state.harness.clock = Shifted()
        state = await act(client, sid, "/script/next")
        assert state["step"] == 1
        assert (await client.post(f"/session/{sid}/approve")).status_code == 409
        errors = [e["data"]["message"] for e in events if e["event"] == "error"]
        assert errors and "expired" in errors[-1].lower()
        assert len(mcp[0].state.harness.payments.intents()) == 0


@pytest.mark.anyio
async def test_voice_affirmation_without_admin_is_rejected_up_front(mcp):
    args = {
        "submission_id": "pay-no-admin",
        "amount_minor": 6000,
        "currency": "USD",
        "payee": "Ridge Plumbing",
        "concept": "deposit",
    }
    llm = OneCallLLM("payment_charge_verified", args)
    async with simulation(mcp, llm, ui_mode="voice", admin_token="") as (
        client,
        metadata,
        events,
        _,
    ):
        sid = metadata["session_id"]
        assert not metadata["admin_enabled"]
        state = await act(client, sid, "/turn", {"text": "Pay the deposit"})
        assert state["pending_approval"]
        for path, body in (("/turn", {"text": "yes"}), ("/approve", None)):
            response = await client.post(f"/session/{sid}{path}", json=body)
            assert response.status_code == 409, response.text
            assert "approval" in response.json()["detail"].lower()
        assert not [e for e in events if e["event"] == "error"]
        assert len(mcp[0].state.harness.payments.intents()) == 0


@pytest.mark.anyio
async def test_mode_change_retires_the_previous_session(mcp):
    async with simulation(mcp) as (client, metadata, events, app):
        sid = metadata["session_id"]
        assert (await act(client, sid, "/script/next"))["step"] == 1
        old_state = (await client.get(f"/session/{sid}/state")).json()
        changed = await client.post(f"/session/{sid}/mode", json={"ui_mode": "scripted"})
        assert changed.status_code == 200
        old = app.state.sessions[sid]
        assert old.closed
        # Reads still work for the SSE replay and the audit; new actions are refused.
        prefix = f"/session/{sid}"
        assert (await client.get(prefix + "/state")).json()["receipts"] == old_state["receipts"]
        assert (await client.post(prefix + "/script/next")).status_code == 409
        assert (await client.post(prefix + "/mode", json={"ui_mode": "voice"})).status_code == 409


PENDING_NOW = {"request": {}, "arguments": {}, "turns_since": 0}
PENDING_LATER = {"request": {}, "arguments": {}, "turns_since": 1}


@pytest.mark.parametrize(
    ("text", "pending", "expected"),
    [
        ("Yes, charge it.", PENDING_NOW, "yes"),
        ("Yes, please charge it.", PENDING_LATER, "yes"),
        ("Yeah go ahead", PENDING_LATER, "yes"),
        ("Sure, do it", PENDING_LATER, "yes"),
        ("please approve it", PENDING_LATER, "yes"),
        ("ok", PENDING_NOW, "yes"),
        ("Okay.", PENDING_NOW, "yes"),
        ("sure", PENDING_NOW, "yes"),
        ("ok", PENDING_LATER, None),
        ("sure", PENDING_LATER, None),
        ("yeah", PENDING_LATER, None),
        ("No, cancel that.", PENDING_NOW, "no"),
        ("don't charge it", PENDING_LATER, "no"),
        ("nope", PENDING_NOW, "no"),
        ("never mind", PENDING_LATER, "no"),
        ("no, don't", PENDING_NOW, "no"),
        ("yes but make it fifty", PENDING_NOW, None),
        ("yes, $50", PENDING_NOW, None),
        ("how much is it?", PENDING_NOW, None),
        ("I know, move it to ten", PENDING_NOW, None),
        ("yes", None, None),
        ("no", None, None),
        # Questions, negations and compound requests are not affirmations (review C1).
        ("can you confirm the amount", PENDING_NOW, None),
        ("how do I approve it", PENDING_NOW, None),
        ("should I do it", PENDING_NOW, None),
        ("did you charge it yesterday", PENDING_NOW, None),
        ("I didn't say yes", PENDING_NOW, None),
        ("I never said yes", PENDING_NOW, None),
        ("I can't approve that", PENDING_NOW, None),
        ("don’t charge it", PENDING_NOW, "no"),
        ("yes make it seventy", PENDING_NOW, None),
        ("yes charge it and move the plumber to ten", PENDING_NOW, None),
        ("Yes, charge it, thanks.", PENDING_LATER, "yes"),
    ],
)
def test_classify_consent_phrases(text, pending, expected):
    assert agent_module.classify_consent(text, pending) == expected


PAY_ARGS = {
    "submission_id": "pay-voice-consent",
    "amount_minor": 6000,
    "currency": "USD",
    "payee": "Ridge Plumbing",
    "concept": "deposit",
}


@pytest.mark.anyio
async def test_voice_decline_clears_pending_and_charges_nothing(mcp):
    llm = OneCallLLM("payment_charge_verified", PAY_ARGS)
    async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, _):
        sid = metadata["session_id"]
        state = await act(client, sid, "/turn", {"text": "Pay the deposit"})
        assert state["pending_approval"]
        state = await act(client, sid, "/turn", {"text": "No, cancel that."})
        assert state["pending_approval"] is None
        said = [e["data"] for e in events if e["event"] == "assistant"]
        assert said[-1] == {"text": agent_module.DECLINED, "source": "session"}
        assert "charged" not in agent_module.DECLINED  # a decline claims no result
        # A later bare "ok" is an ordinary model turn: nothing pending, nothing charged.
        await act(client, sid, "/turn", {"text": "ok"})
        assert len(mcp[0].state.harness.payments.intents()) == 0
        assert not [e for e in events if e["event"] == "error"]


@pytest.mark.anyio
async def test_weak_affirmation_counts_only_right_after_the_question(mcp):
    llm = OneCallLLM("payment_charge_verified", PAY_ARGS)
    async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, _):
        sid = metadata["session_id"]
        await act(client, sid, "/turn", {"text": "Pay the deposit"})
        state = await act(client, sid, "/turn", {"text": "how much is it?"})
        assert state["pending_approval"]  # the question keeps the approval open
        await act(client, sid, "/turn", {"text": "ok"})
        assert len(mcp[0].state.harness.payments.intents()) == 0  # weak word, too late
        state = await act(client, sid, "/turn", {"text": "Yes, charge it."})
        assert state["pending_approval"] is None
        assert len(mcp[0].state.harness.payments.intents()) == 1


@pytest.mark.anyio
async def test_granted_approval_is_consumed_even_if_the_charge_call_fails(mcp, monkeypatch):
    from donewise_sim.session import Session

    llm = OneCallLLM("payment_charge_verified", PAY_ARGS)
    real_execute = Session.execute

    async def failing_charge(self, tool, arguments):
        if tool == "payment_charge_verified" and "approval_id" in arguments:
            raise RuntimeError("simulated loss after the grant")
        return await real_execute(self, tool, arguments)

    monkeypatch.setattr(Session, "execute", failing_charge)
    async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, _):
        sid = metadata["session_id"]
        await act(client, sid, "/turn", {"text": "Pay the deposit"})
        state = await act(client, sid, "/turn", {"text": "Yes, charge it."})
        assert [e for e in events if e["event"] == "error"]
        # The grant was consumed: a later "no" must not pretend the approval is still open.
        assert state["pending_approval"] is None


def test_model_label_names_sonnet_55():
    settings = Settings(llm_provider="anthropic", anthropic_model="claude-sonnet-5-5")
    assert settings.model_label == "Model: Claude Sonnet 5.5 · Anthropic API"


@pytest.mark.anyio
async def test_fault_reset_disarms_without_restarting_the_session(mcp):
    async with simulation(mcp, ui_mode="voice") as (client, metadata, events, app):
        prefix = f"/session/{metadata['session_id']}"
        fault = {"kind": "drop_response_after_write", "uses": 1}
        assert (await client.post(prefix + "/faults", json=fault)).status_code == 200
        reset = await client.post(prefix + "/faults/reset")
        assert reset.status_code == 200
        assert reset.json()["fault_state"]["armed"] == {}
        state = (await client.get(prefix + "/state")).json()
        assert state["run_id"] == metadata["run_id"]
        assert state["fault_state"]["armed"] == {}
        assert (await client.post(prefix + "/faults", json=fault)).status_code == 200
