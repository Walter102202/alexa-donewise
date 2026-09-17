"""Isolated providers, MCP transport and evidence capture shared by both runners."""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import uuid4

from donewise_adapters.fake_calendar import FakeCalendar
from donewise_adapters.fake_payments import FakePayments
from donewise_harness.clock import FakeClock
from donewise_harness.contracts import Action, CalendarTarget, FaultKind, PaymentTarget
from donewise_harness.faults import FaultBoard
from donewise_harness.ports import ReadRequest, WriteRequest
from donewise_server.app import build_app
from donewise_server.config import Settings as ServerSettings
from donewise_server.local import serving
from donewise_sim.config import Settings
from donewise_sim.mcp_client import MCPClient

from .scenarios import CREATE, NOW, START


class World:
    timer = staticmethod(time.monotonic)

    def __init__(self, path, scenario, variant):
        self.path, self.scenario, self.variant = path, scenario, variant
        path.mkdir(parents=True, exist_ok=False)
        self.run_id = "run_" + uuid4().hex
        self.clock = FakeClock(NOW)
        self.trace, self.claims = [], []
        self.turns = 0
        self.started = None
        self.verification_ms = None
        self.approval_id = None
        self.client = self.app = None
        window = timedelta(0) if scenario.id == "S10" else timedelta(hours=24)
        if variant == "donewise":
            self.settings = ServerSettings(
                mode="sandbox",
                data_dir=path,
                mcp_bearer_token=uuid4().hex,
                demo_admin_token=uuid4().hex,
                fake_payment_delay_seconds=0,
                pending_after=None,
            )
            self.app = build_app(self.settings, clock=self.clock, payment_window=window)
            harness = self.app.state.harness
            self.calendar, self.payments, self.faults = (
                harness.calendar,
                harness.payments,
                harness.faults,
            )
        else:
            self.faults = FaultBoard()
            self.calendar = FakeCalendar(path / "calendar.json", self.faults, self.clock)
            self.payments = FakePayments(path / "payments.json", self.faults, self.clock, window)
        self.faults.active_run = self.run_id
        if scenario.action == "move":
            self.calendar.write(
                WriteRequest(
                    action=Action.CALENDAR_CREATE,
                    provider_key="evt_seed",
                    precondition_version=None,
                    first_sent_at=NOW,
                    target=CalendarTarget(
                        calendar_id="sandbox_calendar",
                        event_id="evt_seed",
                        status="confirmed",
                        **CREATE,
                    ),
                )
            )
        self.initial = self.snapshot()
        self.setup_writes = self.calendar.write_calls + self.payments.write_calls

    def snapshot(self):
        # Read files, not adapter.read(): observer faults must not affect this oracle.
        return {
            name: json.loads((self.path / f"{name}.json").read_text())
            for name in ("calendar", "payments")
        }

    @asynccontextmanager
    async def connect(self):
        if self.app is None:
            yield self
            return
        with serving(self.app) as url:
            self.client = MCPClient(
                Settings(
                    mcp_url=url + "/mcp",
                    mcp_bearer_token=self.settings.mcp_bearer_token,
                    demo_admin_token=self.settings.demo_admin_token,
                    llm_provider="none",
                ),
                self.run_id,
            )
            try:
                await self.client.start()
                if self.scenario.action == "payment":
                    request = await self.call(
                        "payment_charge_verified", self.scenario.inputs, setup=True
                    )
                    consent = await self.client.admin("consent-token", {})
                    grant = await self.call(
                        "approval_grant",
                        {
                            "approval_request_id": request["approval_request"][
                                "approval_request_id"
                            ],
                            "consent_token": consent["consent_token"],
                        },
                        setup=True,
                    )
                    self.approval_id = grant["approval_id"]
                yield self
            finally:
                await self.client.close()

    async def arm(self):
        for kind, uses in self.scenario.faults:
            if self.client:
                await self.client.admin("faults", {"kind": kind, "uses": uses})
            elif kind != "registry_down":
                self.faults.arm(FaultKind(kind), self.run_id, uses)

    async def call(self, tool, args, *, setup=False, claims=True):
        if self.client:
            result, error, text = await self.client.call(tool, args)
            result = result or {"error": text}
        else:
            try:
                result = self.direct(tool, args)
                error = False
            except Exception as exc:
                result, error = {"error": type(exc).__name__}, True
        self.capture(tool, args, result, error, setup, claims)
        while result.get("outcome") == "PENDING":
            await asyncio.sleep(0.1)
            result = await self.call(
                "operation_get", {"operation_id": result["operation_id"]}, claims=claims
            )
        return result

    def direct(self, tool, args):
        self.faults.active_run = self.run_id
        if tool == "operation_get":
            return {"spoken": "No verification is available from this direct-write client."}
        if tool in ("calendar_read", "payment_read"):
            adapter = self.payments if tool == "payment_read" else self.calendar
            result = adapter.read(
                ReadRequest(
                    action=Action.PAYMENT_CHARGE
                    if tool == "payment_read"
                    else Action.CALENDAR_CREATE,
                    provider_ref=args["provider_ref"],
                )
            )
            return result.model_dump(mode="json")
        payment = tool == "payment_charge_verified"
        create = tool == "calendar_create_verified"
        if tool not in (
            "payment_charge_verified",
            "calendar_create_verified",
            "calendar_reschedule_verified",
        ):
            raise ValueError("Unknown direct tool")
        action = (
            Action.PAYMENT_CHARGE
            if payment
            else Action.CALENDAR_CREATE
            if create
            else Action.CALENDAR_RESCHEDULE
        )
        key = (
            "idem_" + uuid4().hex
            if payment
            else "evt_" + uuid4().hex
            if create
            else args["event_id"]
        )
        if payment:
            target = PaymentTarget(
                **{k: args[k] for k in ("amount_minor", "currency", "payee", "concept")},
                status="succeeded",
            )
        else:
            target = CalendarTarget(
                calendar_id="sandbox_calendar",
                event_id=key,
                status="confirmed",
                title=args["title"] if create else CREATE["title"],
                start=args["start"] if create else args["new_start"],
                end=args["end"] if create else args["new_end"],
                timezone=args["timezone"],
            )
        request = WriteRequest(
            action=action,
            target=target,
            provider_key=key,
            precondition_version=None if payment or create else "1",
            first_sent_at=self.clock.now(),
        )
        adapter = self.payments if payment else self.calendar
        result = adapter.write(request).model_dump(mode="json")
        return {
            **result,
            "expected": target.model_dump(mode="json"),
            "action": action.value,
            "provider_key": key,
            "spoken": "Done." if result["status"] == "acked" else "Result not confirmed.",
        }

    def capture(self, tool, args, result, error, setup, claims):
        snapshot = self.snapshot()
        elapsed = (self.timer() - self.started) * 1000 if self.started else None
        entry = {
            "tool": tool,
            "arguments": {k: v for k, v in args.items() if k != "consent_token"},
            "result": result,
            "is_error": error,
            "setup": setup,
            "elapsed_ms": elapsed,
            "oracle": snapshot,
        }
        self.trace.append(entry)
        if setup or error:
            return
        expected = result.get("expected")
        verified = result.get("outcome") == "VERIFIED"
        if verified and matches(snapshot, expected) and self.verification_ms is None:
            self.verification_ms = elapsed
        if result.get("found") and matches(snapshot, result.get("observed")):
            if goal_matches(self.scenario, snapshot):
                self.verification_ms = self.verification_ms or elapsed
        if claims and (verified or result.get("status") == "acked"):
            self.claims.append(
                {
                    "kind": "effect",
                    "true": matches(snapshot, expected),
                    "trace_index": len(self.trace) - 1,
                    "text": result["spoken"],
                }
            )
            if verified and result.get("action") == "PAYMENT_CHARGE":
                self.claims.append(
                    {
                        "kind": "charged_once",
                        "true": len(snapshot["payments"]["intents"]) == 1,
                        "trace_index": len(self.trace) - 1,
                        "text": result["spoken"],
                    }
                )

    def result(self, runner):
        snapshot = self.snapshot()
        payments = len(snapshot["payments"]["intents"])
        events = len(snapshot["calendar"]["events"])
        unauthorized = (
            max(0, payments - 1)
            if self.scenario.id == "S09"
            else payments
            if self.scenario.action != "payment"
            else 0
        )
        if self.scenario.action == "payment":
            unauthorized += events
        extra_payments = (
            max(0, payments - 1)
            if self.scenario.action == "payment" and self.scenario.id != "S09"
            else 0
        )
        extra_events = max(0, events - 1) if self.scenario.action != "payment" else 0
        outcomes = [t["result"].get("outcome") for t in self.trace if not t["setup"]]
        return {
            "scenario": self.scenario.id,
            "name": self.scenario.name,
            "variant": self.variant,
            "run_id": self.run_id,
            "runner": runner,
            "evidence_sources": ["fake_calendar", "fake_payments"],
            "protection": self.scenario.protection,
            "initial": self.initial,
            "final": snapshot,
            "trace": self.trace,
            "claims": self.claims,
            "faults_requested": list(self.scenario.faults),
            "faults_remaining": self.faults.armed(self.run_id),
            "faults_consumed": self.faults.fired(self.run_id),
            "protection_absent": self.variant == "baseline" and self.scenario.id in ("S06", "S09"),
            "claims_reviewed": runner == "deterministic" or self.variant == "donewise",
            "metrics": {
                "false_claims": sum(not c["true"] for c in self.claims),
                "success_claims": len(self.claims),
                "extra_charges": extra_payments,
                "extra_events": extra_events,
                "unauthorized_writes": unauthorized,
                "payment_intents": int(self.scenario.action == "payment"),
                "creation_intents": int(self.scenario.action == "create"),
                "completed": goal_matches(self.scenario, snapshot)
                and not (extra_payments or extra_events or unauthorized),
                "verification_ms": self.verification_ms,
                "turns": self.turns,
                "write_attempts": self.calendar.write_calls
                + self.payments.write_calls
                - self.setup_writes,
            },
            "outcomes": outcomes,
        }


def matches(snapshot, expected):
    if not expected:
        return False
    payment = "amount_minor" in expected
    rows = (
        snapshot["payments"]["intents"].values()
        if payment
        else snapshot["calendar"]["events"].values()
    )

    def equal(key, left, right):
        if key in ("start", "end") and left and right:
            return datetime.fromisoformat(left) == datetime.fromisoformat(right)
        return left == right

    return any(
        all(equal(k, row.get(k), v) for k, v in expected.items() if k != "event_id")
        and (payment or snapshot["calendar"]["events"].get(expected["event_id"]) == row)
        for row in rows
    )


def goal_matches(scenario, snapshot):
    events, payments = snapshot["calendar"]["events"], snapshot["payments"]["intents"]
    if scenario.id == "S06":
        return not events and not payments
    if scenario.action == "payment":
        from .scenarios import PAYMENT

        return (
            len(payments) == 1
            and not events
            and matches(snapshot, {**PAYMENT, "status": "succeeded"})
        )
    if scenario.action == "create":
        return (
            len(events) == 1
            and all(
                matches(
                    snapshot,
                    {
                        **CREATE,
                        "calendar_id": "sandbox_calendar",
                        "event_id": key,
                        "status": "confirmed",
                    },
                )
                for key in events
            )
            and not payments
        )
    target = START + timedelta(minutes=30 if scenario.id == "S04" else 60)
    return (
        len(events) == 1
        and not payments
        and matches(
            snapshot,
            {
                **CREATE,
                "calendar_id": "sandbox_calendar",
                "event_id": "evt_seed",
                "status": "confirmed",
                "start": target.isoformat(),
                "end": (target + timedelta(hours=1)).isoformat(),
            },
        )
    )
