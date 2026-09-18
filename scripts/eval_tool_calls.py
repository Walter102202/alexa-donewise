"""Small eval of tool-calling behaviour against a running simulator (sandbox mode).

Usage: uv run --env-file .env python scripts/eval_tool_calls.py --runs 3 --sim http://127.0.0.1:8080
"""

import argparse
import asyncio
import json

import httpx

SCENARIOS = {
    # Expect one valid create on the first call and no clarification.
    "future_hour": ["Book the plumber tomorrow at 10 a.m. for one hour"],
    # Expect a visible question, zero writes, then one write after the answer.
    "past_hour": ["Schedule an appointment for today at 3 a.m.", "Tomorrow at 3 a.m. then"],
    # Expect the model to complete the format itself (offset) without asking.
    "bare_time": ["Put a dentist visit on Friday at 9 in the morning, one hour"],
}


async def run_turns(client, texts):
    sid = (await client.post("/session")).json()["session_id"]
    events = []

    async def collect():
        async with client.stream("GET", f"/session/{sid}/events") as stream:
            name = None
            async for line in stream.aiter_lines():
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    events.append((name, json.loads(line[6:])))

    task = asyncio.create_task(collect())
    per_turn = []
    for text in texts:
        before = len(events)
        await client.post(f"/session/{sid}/turn", json={"text": text})
        while (await client.get(f"/session/{sid}/state")).json()["busy"]:
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.3)
        per_turn.append(events[before:])
    task.cancel()
    return per_turn


def score(name, turns):
    first = turns[0]
    calls = [d["status"] for k, d in first if k == "status" and d["status"].startswith("calling")]
    receipts = [d for k, d in first if k == "receipt"]
    errors = [d for k, d in first if k == "error"]
    questions = [d for k, d in first if k == "assistant" and d["source"] == "model"]
    if name == "past_hour":
        later_writes = [d for turn in turns[1:] for k, d in turn if k == "receipt"]
        return {
            "valid_first_call": False,  # by construction the first call must be rejected
            "visible_clarification": bool(questions) and not receipts,
            "unsolicited_writes": len(receipts),
            "write_after_answer": len(later_writes) == 1,
        }
    return {
        "valid_first_call": bool(calls) and bool(receipts) and not errors,
        "visible_clarification": bool(questions),
        "unsolicited_writes": 0 if len(receipts) <= 1 else len(receipts) - 1,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--sim", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    async with httpx.AsyncClient(base_url=args.sim, timeout=120) as client:
        for name, texts in SCENARIOS.items():
            rows = [score(name, await run_turns(client, texts)) for _ in range(args.runs)]
            print(f"\n{name} (n={args.runs})")
            for key in rows[0]:
                values = [row[key] for row in rows]
                if isinstance(values[0], bool):
                    print(f"  {key:<24} {sum(values)}/{args.runs}")
                else:
                    print(f"  {key:<24} {sum(values)}")


asyncio.run(main())
