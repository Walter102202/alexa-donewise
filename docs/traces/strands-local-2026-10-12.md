# Strands local connected acceptance — 12 October 2026 (Chile)

Strands 1.60.0, MCP client 2.1.1, server MCP 2.2.0, Nova Pro on Bedrock in us-east-1.
Private bearer; `user_id=demo`; run `run_33a9a54f92e84b778bd16ab8c46cc111`.
Separate dependency environment; the first startup needed `tzdata` on Windows.

```powershell
uv run --no-project --python data/strands-venv/Scripts/python.exe --env-file .env python agents/strands_client/smoke.py --five-turns --output data/strands-local-2026-10-12-v2.json
uv run --no-project --python data/strands-venv/Scripts/python.exe --env-file .env python agents/strands_client/smoke.py --output data/strands-next-session-2026-10-12.json
```

MCP_URL was the task-owned connected server at `http://127.0.0.1:18765/mcp`.
Five of five returned speeches exactly equalled their receipt's `spoken`:
NEEDS_APPROVAL → VERIFIED payment → NOT_OBSERVED move → VERIFIED same-operation
retry → saved recap. Final calendar time was 10:00 America/Santiago. Payment
`pi_3UPv7dFik9VWGlFf0JCml95y` was a USD 60 test charge.

A fresh agent/MCP session, without conversation history, returned the saved recap
in **2160 ms** locally. Its tool trace contains **one `receipts_recap` call**, no
calendar/payment writes. This is one observation, not a cloud latency percentile.
The terminal returned the saved observation time, both items and zero pending or
unverified operations. Raw private traces remain in the command output paths.

AgentCore, Lightsail and Alexa acceptance remain separate gates.
