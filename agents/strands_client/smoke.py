"""Operator-driven Strands test. Consent/admin credentials never enter the model."""

import argparse
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from client import ReceiptAgent

UTTERANCES = [
    "Book the plumber tomorrow nine to ten and pay the sixty-dollar deposit to Ridge Plumbing.",
    "Yes, charge it.",
    "I'm running late. Move the plumber to ten.",
    "Try that again.",
    "What did you charge last night, and when is the plumber?",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--five-turns", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new evidence path")
    logging.disable(logging.INFO)
    turns = []
    with ReceiptAgent() as agent:

        def admin(path, payload):
            url = urlsplit(os.getenv("DONEWISE_ADMIN_URL", agent.url))
            response = httpx.post(
                urlunsplit((url.scheme, url.netloc, "/admin/" + path, "", "")),
                headers={"X-Demo-Admin-Token": os.environ["DEMO_ADMIN_TOKEN"]},
                json={"run_id": agent.run_id, **payload},
                timeout=20,
            )
            response.raise_for_status()
            return response.json()

        try:
            for index, text in enumerate(UTTERANCES if args.five_turns else UTTERANCES[-1:]):
                start = time.perf_counter()
                if text == UTTERANCES[-1]:
                    # The morning scene starts without history and cannot write.
                    with ReceiptAgent(read_only=True) as morning:
                        result = morning.turn(text)
                        agent.trace.extend(morning.trace)
                        assert [item["tool"] for item in morning.trace] == ["receipts_recap"]
                elif args.five_turns and index == 1:
                    admin("faults", {"kind": "drop_response_after_write", "uses": 1})
                    capability = admin("consent-token", {})["consent_token"]
                    result = agent.approve(capability)
                else:
                    if args.five_turns and index == 2:
                        admin("faults", {"kind": "ack_without_write", "uses": 2})
                    result = agent.turn(text)
                assert result["speech"] == result["receipt"]["spoken"]
                turns.append(
                    {"input": text, "elapsed_ms": (time.perf_counter() - start) * 1000, **result}
                )
                print(json.dumps({"turn": index + 1, "speech": result["speech"]}), flush=True)
        finally:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(
                    {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "run_id": agent.run_id,
                        "model": os.getenv("BEDROCK_MODEL_ID"),
                        "turns": turns,
                        "tools": agent.trace,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
