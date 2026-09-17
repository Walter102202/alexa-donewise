# Local MCP evidence — step 2

The production entry point `uv run donewise-server` started on `127.0.0.1:8765`.
The isolated data directory for this check was `%TEMP%/donewise-step2-inspector`.
No real adapters, credentials or charges were used.

Executed successfully (exit 0):

```powershell
npx --yes @modelcontextprotocol/inspector@1.0.2 --cli http://127.0.0.1:8765/mcp --transport http --method tools/list
```

Inspector returned the six tools, all with input/output schemas:
`calendar_create_verified`, `calendar_reschedule_verified`, `payment_charge_verified`,
`operation_get`, `approval_grant`, `receipts_recap`.
This was the Inspector CLI, not a claimed visual Inspector/Desktop acceptance run.

[`initialize.json`](initialize.json) is the actual initialize request/response captured separately
with the official Python `ClientSession` against that same running server. The response negotiates
`2025-11-25`. SQLite `protocol_sessions` also records actual negotiations. Session IDs and bearer
headers are intentionally not included in this public trace. `tests/test_server.py` exercises the
same handshake, tools, authentication, receipts, PENDING and session deletion over real TCP.

For visual Inspector, run `npx @modelcontextprotocol/inspector@1.0.2`, choose Streamable HTTP,
enter `http://127.0.0.1:8765/mcp`, connect, then list tools. When bearer auth is configured, add
`Authorization: Bearer <token>` in the request headers. Add `X-DoneWise-Run-Id: run_inspector` to
associate admin consent and faults with that run. Add the Inspector UI origin to `ALLOWED_ORIGINS`
if using a non-localhost UI.

Claude Desktop can use a local stdio-to-HTTP bridge in its `mcpServers` configuration:

```json
{"mcpServers":{"donewise":{"command":"npx","args":["-y","mcp-remote",
"http://127.0.0.1:8765/mcp"]}}}
```

The example assumes the local bearer is unset. For authenticated operation configure the bridge's
Authorization header outside the model. Desktop and the bridge have not been exercised in this run;
the directly tested interoperable clients are Inspector CLI and Python ClientSession.

Inspector command reference: [official CLI README](https://github.com/modelcontextprotocol/inspector/blob/main/clients/cli/README.md).
