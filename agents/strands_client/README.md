# Strands receipt client

Uses Amazon Nova Pro through Bedrock and the native Strands Streamable HTTP MCP
client. The model chooses tools; Python returns `{"speech": receipt["spoken"],
"receipt": receipt}`. Model prose never supplies returned speech. Approval is a
trusted operator method, excluded from model tools. Writes cannot be retried
automatically, and pending operations are polled by the client without new writes.

Install separately from the server: Strands 1.60.0 requires `mcp<2.2`, while the
server requires `mcp>=2.2`. HTTP interoperability was verified locally.

```powershell
uv venv data/strands-venv --python 3.12
uv pip install --python data/strands-venv/Scripts/python.exe -r agents/strands_client/requirements.txt
$env:MCP_URL = 'http://127.0.0.1:8765/mcp'
$env:DONEWISE_RUN_ID = '<the previous run_id from the simulator>'
$env:DONEWISE_USER_ID = 'demo'
$env:BEDROCK_MODEL_ID = 'us.amazon.nova-pro-v1:0'
uv run --no-project --python data/strands-venv/Scripts/python.exe --env-file .env python agents/strands_client/smoke.py --output data/next-session.json
```

`MCP_BEARER_TOKEN` is mandatory; remote URLs require HTTPS. The server is a
single-user demo and authenticates the configured bearer as `demo`; other
`DONEWISE_USER_ID` values fail closed. A run ID is not authentication. Use a
separate server and data directory for another user.

The optional `--five-turns` smoke uses a fresh run ID and creates one calendar event
and an explicitly approved USD 60 test payment. It also needs the local server's
`DEMO_ADMIN_TOKEN` to arm faults and obtain consent outside the model. Never expose
`/admin` publicly. Against Lightsail, run this operator smoke through an SSH tunnel
or on the instance; the deployed AgentCore agent never receives this admin token.

[Local evidence](../../docs/traces/strands-local-2026-10-12.md) distinguishes
five-turn connected acceptance from remote/cloud validation.
