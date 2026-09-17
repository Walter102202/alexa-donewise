# DoneWise simulator: live MCP, with an offline fixture fallback

Plain HTML/CSS/JS, no bundler. From the repository root run `uv sync`.
In **both** PowerShell terminals set matching local demo credentials:

```powershell
$env:DEMO_ADMIN_TOKEN = 'choose-a-local-admin-secret'
$env:MCP_BEARER_TOKEN = 'choose-a-local-mcp-secret'
```

Terminal 1: `uv run donewise-server`.
Terminal 2: `$env:LLM_PROVIDER = 'none'; uv run donewise-sim`.
Open `http://127.0.0.1:8080` and press Continue five times; only the inputs are scripted.
The page receives real receipts over SSE, and Audit shows the negotiated MCP version.
`Yes, charge it` or the Approve button uses backend consent without invoking the model.
The approval capability is never sent to the browser or the model.

Environment variables are read from the process; `.env.example` documents them but is not auto-loaded.
`MCP_URL` defaults to `http://127.0.0.1:8765/mcp`; `SIM_PORT` defaults to 8080.
`LLM_PROVIDER=bedrock` is the default: set `AWS_REGION`, `BEDROCK_MODEL_ID` and AWS credentials.
For `anthropic`, set `ANTHROPIC_API_KEY`; `ANTHROPIC_MODEL` defaults to `claude-sonnet-5`.
No live LLM/provider calls are needed for the scripted demo or tests. Missing admin config hides
the demo controls and disables approval. The application currently uses local Fake adapters only.

Sessions and SSE history live in memory. Reloading the page reuses the same session while the
simulator process lives. A dead MCP connection is reopened with the same run on a later request;
a failed write call is never automatically resent. SQLite receipts survive server restarts.
To start another demo, use a new browser tab/session; the old audit remains available.

Offline preview: `uv run python -m http.server 8000 --directory sim`, then open
`http://localhost:8000/static/`. The UI labels this **Fixture mode · server not connected**.
Serve over HTTP; opening the HTML directly from disk cannot load the fixture.
Voice input needs browser speech-recognition support and microphone permission; typed input works
without it. The microphone implementation is wired, but live microphone acceptance is untested.
