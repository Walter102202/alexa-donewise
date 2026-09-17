"""Approved external inputs, not prescribed measurements."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

NOW = datetime(2026, 9, 17, 2, 39, tzinfo=UTC)
START = datetime(2026, 9, 17, 16, tzinfo=UTC)
VERSION = "2026-09-17-v1"
PAYMENT = dict(amount_minor=6000, currency="USD", payee="Ridge Plumbing", concept="deposit")
CREATE = dict(
    title="Ridge Plumbing",
    start=START.isoformat(),
    end=(START + timedelta(hours=1)).isoformat(),
    timezone="America/Los_Angeles",
)
MOVE = dict(
    event_id="evt_seed",
    new_start=(START + timedelta(hours=1)).isoformat(),
    new_end=(START + timedelta(hours=2)).isoformat(),
    timezone="America/Los_Angeles",
)


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    action: str
    faults: tuple = ()
    followup: str | None = None
    protection: bool = False

    @property
    def inputs(self):
        args = dict(
            PAYMENT if self.action == "payment" else MOVE if self.action == "move" else CREATE
        )
        return {"submission_id": "submission-first", **args}


SCENARIOS = (
    Scenario("S01", "lost payment response", "payment", (("drop_response_after_write", 1),)),
    Scenario("S02", "acknowledgement without write once", "create", (("ack_without_write", 1),)),
    Scenario("S03", "acknowledgement without write twice", "move", (("ack_without_write", 2),)),
    Scenario("S04", "concurrent edit", "move", (("concurrent_edit", 1),), protection=True),
    Scenario(
        "S05",
        "read unavailable",
        "create",
        (("drop_response_after_write", 1), ("read_unavailable", 3)),
        "status",
    ),
    Scenario(
        "S06", "registry down before intent", "create", (("registry_down", 1),), protection=True
    ),
    Scenario("S07", "repeated submission", "payment", followup="resubmit"),
    Scenario("S08", "explicit retry of operation", "move", (("ack_without_write", 2),), "retry"),
    Scenario("S09", "reused approval", "payment", followup="reuse", protection=True),
    Scenario(
        "S10", "replay window expired", "payment", (("drop_response_after_write", 1),), "status"
    ),
)

TOOLS = {
    "create": "calendar_create_verified",
    "move": "calendar_reschedule_verified",
    "payment": "payment_charge_verified",
}


async def deterministic(world):
    scenario = world.scenario
    args = scenario.inputs
    if world.approval_id:
        args["approval_id"] = world.approval_id
    await world.arm()
    world.started = world.timer()
    world.turns += 1
    result = await world.call(TOOLS[scenario.action], args)
    if scenario.followup:
        world.turns += 1
        if scenario.followup == "status":
            await world.call(
                "operation_get", {"operation_id": result.get("operation_id", "op_none")}
            )
        else:
            if scenario.followup == "retry":
                args["retry_of_operation_id"] = result.get("operation_id", "op_none")
            if scenario.followup == "reuse":
                args["submission_id"] = "submission-other"
            await world.call(TOOLS[scenario.action], args)
