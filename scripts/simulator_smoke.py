"""Five live-model turns through the simulator backend and real MCP transport."""

import argparse
import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from donewise_server.app import build_app
from donewise_server.config import Settings as ServerSettings
from donewise_server.local import serving
from donewise_sim import agent
from donewise_sim.config import Settings
from donewise_sim.llm import make_llm
from donewise_sim.scripted import UTTERANCES
from donewise_sim.session import Session


async def run(args, url):
    settings = Settings(mcp_url=url + "/mcp", llm_provider=args.provider)
    if args.model:
        settings.bedrock_model_id = args.model
    session = Session(settings, make_llm(settings), ui_mode="voice")
    await session.start()
    turns = []
    try:
        for step, text in enumerate(UTTERANCES):
            if step == 1:
                if not session.pending_approval:
                    raise RuntimeError("First turn did not request payment approval; stopping")
                await session.arm("drop_response_after_write")
            if step == 2:
                await session.arm("ack_without_write", 2)
            session.turn_spoken = {}
            before = len(session.events)
            started = time.perf_counter()
            await asyncio.wait_for(agent.turn(session, text), timeout=120)
            events = session.events[before:]
            spoken = [e["data"] for e in events if e["event"] == "assistant"]
            receipts = [e["data"] for e in events if e["event"] == "receipt"]
            final = list(session.turn_spoken.values())
            expected = (
                {"VERIFIED", "NEEDS_APPROVAL"},
                {"VERIFIED"},
                {"NOT_OBSERVED"},
                {"VERIFIED"},
                {None},
            )[step]
            passed = expected <= {r.get("outcome") for r in final}
            if step in (0, 2, 3):
                calendars = [r for r in final if r.get("action", "").startswith("CALENDAR")]
                passed = (
                    passed
                    and bool(calendars)
                    and all(
                        datetime.fromisoformat(r["expected"]["start"])
                        .astimezone(ZoneInfo(settings.user_timezone))
                        .hour
                        == (9 if step == 0 else 10)
                        for r in calendars
                    )
                )
            if step == 2:
                failed_operation = calendars[-1]["operation_id"]
            if step == 3:
                passed = passed and calendars[-1]["operation_id"] == failed_operation
            turns.append(
                {
                    "turn": step + 1,
                    "input": text,
                    "receipts": receipts,
                    "spoken": spoken,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "errors": [e["data"] for e in events if e["event"] == "error"],
                    "passed": passed,
                }
            )
            print(
                json.dumps({"turn": step + 1, "spoken": spoken, "errors": turns[-1]["errors"]}),
                flush=True,
            )
            if not spoken or any(s["source"] != "spoken" for s in spoken):
                raise RuntimeError("Turn did not finish with receipt speech; stopping")
            if not passed:
                raise RuntimeError("Turn did not reach the required outcome; stopping")
    finally:
        evidence = {
            "observed_at": datetime.now(UTC).isoformat(),
            "run_id": session.run_id,
            "mode": settings.mode,
            "model_label": settings.model_label,
            "boundary": "Simulator backend and MCP; no browser/audio verification",
            "turns": turns,
            "messages": session.messages,
        }
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        await session.close()


def main():
    logging.disable(logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["bedrock", "anthropic"], required=True)
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.data_dir.exists():
        parser.error("Use new output/data paths; never overwrite prior evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with serving(build_app(ServerSettings(data_dir=args.data_dir))) as url:
        asyncio.run(run(args, url))


if __name__ == "__main__":
    main()
