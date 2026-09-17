# DoneWise MCP server

Run `uv sync`, then `uv run donewise-server` (127.0.0.1:8765).
Streamable HTTP uses `json_response=True` (JSON tool responses, not SSE); verify Alexa+ bridge support. Health: `GET /healthz`.
Six tools publish the canonical input schemas and structured output schemas.
`DONEWISE_MODE=sandbox` uses persisted FakeCalendar and FakePayments only.
`connected` validates Google credentials and an `sk_test_` key, but still uses Fakes.
Set `MCP_BEARER_TOKEN` to require bearer auth on every MCP request.
Set `DEMO_ADMIN_TOKEN` for admin routes; absent means 404.
Admin requests require `X-Demo-Admin-Token` (separate from the MCP bearer).
POST `/admin/consent-token`, `/admin/faults`, `/admin/reset`; GET `/admin/faults?run_id=…`.
`DONEWISE_DATA_DIR=./data`; `HOST=127.0.0.1`; `PORT=8765`.
`ALLOWED_ORIGINS` is comma-separated; defaults allow localhost ports.
`FAKE_PAYMENT_DELAY_SECONDS=0.65` demonstrates real PENDING; set 0 for fast Fakes.
Polling uses `operation_get`; receipts also have read-only `receipts://` resources.
SQLite is append-only; reset removes only the run's Fake objects, never its audit trail.
Run one server process per data directory; the locks are in-process.
Run `uv run pytest` and `uv run ruff check .` to verify.
Inspector: `npx @modelcontextprotocol/inspector@1.0.2 --cli http://127.0.0.1:8765/mcp --transport http --method tools/list`.
See `docs/traces/inspector-handshake.md` for captured evidence and client setup.
