# DoneWise MCP server

Run `uv sync`, then `uv run donewise-server` (127.0.0.1:8765).
Streamable HTTP uses SSE (`json_response=False`) so a tool can send `elicitation/create`
before its final result. The official client and simulator support this; the real Alexa+
bridge still needs connected acceptance. Health: `GET /healthz`.
Six tools publish the canonical input schemas and structured output schemas.
`DONEWISE_MODE=sandbox` uses persisted FakeCalendar and FakePayments only.
`connected` uses Google Calendar and Stripe test REST adapters through the local fault proxy.
It requires Google credentials/calendar ID and an `sk_test_` key; live keys abort startup.
Set `MCP_BEARER_TOKEN` to require bearer auth on every MCP request.
Set `DEMO_ADMIN_TOKEN` for admin routes; absent means 404.
Admin requests require `X-Demo-Admin-Token` (separate from the MCP bearer).
POST `/admin/consent-token`, `/admin/faults`, `/admin/reset`; GET `/admin/faults?run_id=…`.
`DONEWISE_DATA_DIR=./data`; `HOST=127.0.0.1`; `PORT=8765`.
`ALLOWED_ORIGINS` is comma-separated; defaults allow localhost ports.
`FAKE_PAYMENT_DELAY_SECONDS=0.65` demonstrates real PENDING; set 0 for fast Fakes.
`DONEWISE_PENDING_AFTER=0.45` is the default response budget in seconds. Set it to `off`
for the Alexa+ bridge: the tool waits for verification and creates no intermediate PENDING
receipt. Verification can take 3–7 seconds, or about 10 seconds with replay, exceeding the
bridge's 6.5-second turn budget. The bridge then says “still working” and queries the same
operation on the next turn; it must not create a new payment. `operation_get` and startup
reconciliation of UNKNOWN remain enabled. Without an explicit run header, the run ID comes
from the MCP session. Keep that session when polling. Negative/nonfinite budgets are invalid.
Polling uses `operation_get`; receipts also have read-only `receipts://` resources.
SQLite is append-only; reset removes only the run's Fake objects, never its audit trail.
Run one server process per data directory; the locks are in-process.
The local Windows HTTP host uses SelectorEventLoop: Python 3.12 Proactor socket shutdown
can raise WinError 10054 on SSE disconnect before notifying Uvicorn, preventing shutdown.
Run `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` to verify.

Clients advertising form elicitation (including legacy empty elicitation capability) receive
one strict boolean `approve` prompt inside `payment_charge_verified` when no approval ID
was supplied. Only `accept` with boolean `true` grants the bound request; decline, cancel,
false or malformed content persist REJECTED/NO_APPROVAL without a provider write. Waiting
is capped at 120 seconds; timeout returns the normal NEEDS_APPROVAL receipt and ignores late
consent. Repeating an already charged submission returns its receipt without another prompt.
This trusts the MCP client's elicitation handler to obtain human consent.

Approval provenance is persisted and returned as optional `granted_by` in payment receipts
and `operation_get`: `elicitation`, `mcp_client`, or `session_ui`. Old receipts may omit it.
The simulator backend labels its existing token-based requests with
`X-DoneWise-Channel: session-ui`; this label is provenance, not authentication. Token checks
remain mandatory on `approval_grant`. Clients without form elicitation retain that flow.
The simulator does not advertise elicitation or expose its consent token to the model.
Inspector: `npx @modelcontextprotocol/inspector@1.0.2 --cli http://127.0.0.1:8765/mcp --transport http --method tools/list`.
See `docs/traces/inspector-handshake.md` for captured evidence and client setup.
