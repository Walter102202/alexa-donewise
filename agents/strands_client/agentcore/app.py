"""AgentCore hosts the Strands MCP client; persistent receipts stay on the server."""

import json
import time

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from client import ReceiptAgent

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context):
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 2000:
        raise ValueError("prompt must contain 1 to 2000 characters")
    started = time.perf_counter()
    with ReceiptAgent(read_only=True) as agent:
        result = agent.turn(prompt)
        print(
            json.dumps(
                {
                    "event": "donewise_receipt",
                    "run_id": agent.run_id,
                    "tools": agent.trace,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                    "receipt_id": result["receipt"].get("receipt_id"),
                }
            ),
            flush=True,
        )
        return result


if __name__ == "__main__":
    app.run()
