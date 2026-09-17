"""Only inputs are scripted. All outcomes and speech arrive over MCP."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

UTTERANCES = [
    "Book the plumber tomorrow nine to ten and pay the sixty-dollar deposit to Ridge Plumbing.",
    "Yes, charge it.",
    "I'm running late. Move the plumber to ten.",
    "Try that again.",
    "Recap tomorrow. And what did you charge?",
]


async def next_step(session):
    if session.step >= len(UTTERANCES):
        raise RuntimeError("Script complete; start a new session to run again")
    step = session.step
    await session.emit("user", {"text": UTTERANCES[step]})
    if not session.script_args:
        zone = ZoneInfo("America/Los_Angeles")
        tomorrow = datetime.now(zone).date() + timedelta(days=1)
        start = datetime.combine(tomorrow, time(9), zone).astimezone(UTC)
        session.script_args = {
            "create": {
                "submission_id": str(uuid4()),
                "title": "Ridge Plumbing",
                "start": start.isoformat(),
                "end": (start + timedelta(hours=1)).isoformat(),
                "timezone": "America/Los_Angeles",
            },
            "pay": {
                "submission_id": str(uuid4()),
                "amount_minor": 6000,
                "currency": "USD",
                "payee": "Ridge Plumbing",
                "concept": "deposit",
            },
            "move": {
                "submission_id": str(uuid4()),
                "event_query": "the plumber",
                "new_start": (start + timedelta(hours=1)).isoformat(),
                "new_end": (start + timedelta(hours=2)).isoformat(),
                "timezone": "America/Los_Angeles",
            },
        }
    args = session.script_args
    if step == 0:
        await session.execute("calendar_create_verified", args["create"])
        await session.execute("payment_charge_verified", args["pay"])
    elif step == 1:
        await session.arm("drop_response_after_write")
        await session.approve()
    elif step == 2:
        await session.arm("ack_without_write", 2)
        result = await session.execute("calendar_reschedule_verified", args["move"])
        args["retry"] = {**args["move"], "retry_of_operation_id": result["operation_id"]}
    elif step == 3:
        await session.execute("calendar_reschedule_verified", args["retry"])
    else:
        await session.execute("receipts_recap", {"run_id": session.run_id})
    session.step += 1
    await session.speak_receipts()
