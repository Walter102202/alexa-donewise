# DoneWise simulator: live MCP, with an offline fixture fallback

Plain HTML/CSS/JS, no bundler. From the repository root run `uv sync`.
In **both** PowerShell terminals set matching local demo credentials:

```powershell
$env:DEMO_ADMIN_TOKEN = 'choose-a-local-admin-secret'
$env:MCP_BEARER_TOKEN = 'choose-a-local-mcp-secret'
```

Terminal 1: `uv run donewise-server`.
Terminal 2: `$env:LLM_PROVIDER = 'none'; uv run donewise-sim`.
Open `http://localhost:8080` and press Continue five times; only the inputs are scripted.
The page receives real receipts over SSE, and Audit shows the negotiated MCP version.
`Yes, charge it` or the Approve button uses backend consent without invoking the model.
The approval capability is never sent to the browser or the model.

Environment variables are read from the process; `.env.example` documents them but is not auto-loaded.
`MCP_URL` defaults to `http://127.0.0.1:8765/mcp`; `SIM_PORT` defaults to 8080.
`LLM_PROVIDER=bedrock` is the default: set `AWS_REGION`, `BEDROCK_MODEL_ID` and AWS credentials.
For `anthropic`, set `ANTHROPIC_API_KEY`; `ANTHROPIC_MODEL` defaults to `claude-sonnet-5`.
`USER_TIMEZONE` is `America/Los_Angeles` by default or `America/Santiago`; set the same value for the server.
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
without it. Live microphone acceptance still requires a human rehearsal; synthetic recognition events
do not prove acoustic capture or the absence of speaker echo.

## Voice rehearsal checklist

1. Use Chrome and keep `http://localhost:8080` as the rehearsal origin. Grant microphone permission
   for that origin. If port 8080 is occupied, set `SIM_PORT` and use the same alternative origin
   throughout; permissions do not transfer between origins. Do not stop another running server.
2. With `LLM_PROVIDER=none`, Scripted is the default. Continue runs the five-turn story and arms
   its own faults. The fault panel is read-only in this mode. Typed or spoken approval still works;
   other free input requires a new Free voice session.
3. Select Free voice to start a fresh run. Previous records remain stored but are not copied into
   this conversation. The chapter bar disappears and `live voice session` stays visible. With no LLM,
   `Language model off · input check only` is also shown: input does not execute the story. Full voice
   rehearsal requires a configured LLM and separate acceptance; step 3 checks use no provider keys.
4. For the later LLM rehearsal, say the five short inputs from `donewise_sim/scripted.py`. Before
   turn 1 arm nothing; before turn 2 (`Yes, charge it`) arm **Drop the response after the charge**;
   before turn 3 arm **Acknowledge without writing, twice**; before turns 4 and 5 arm nothing.
   Wait for pending uses to reach zero before another fault. Armed and consumed states are distinct.
   After a lost arm response, refresh fault state instead of submitting another arm request.
5. Wait for TTS to finish before pressing Speak. Only one recognition session runs at a time. The
   final transcript appears in the text field before sending once on recognition end. Permission
   denial, no speech and cancellation send nothing. If recognition fails, type the phrase and Send;
   if sending fails, the text remains for inspection and is never automatically resent.
6. Reload restores the mode and fault state only while the simulator session remains alive. Switching
   modes starts a new session; record scripted fallback as a separate, labelled take. Finish the
   current turn before switching or arming. Sessions are in memory, not a new persistence service.

Record browser/version, actual microphone/TTS outcome and untested items in
`docs/traces/simulator-flow.md`. A synthetic UI check is not a completed voice rehearsal.
