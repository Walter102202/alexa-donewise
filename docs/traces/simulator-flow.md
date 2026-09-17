# Simulator acceptance — real MCP, local Fakes

Both entry points were started: `uv run donewise-server` on port 8765 and
`uv run donewise-sim` on port 8080, with matching demo admin/bearer configuration and
`LLM_PROVIDER=none`. Browser acceptance used the actual FastAPI UI and SSE, not fixture results.

Final observed run: `run_90df43743b4e4fb7ab5b33990d92b682`.
Audit showed MCP **2025-11-25**.

| Input | Observed result |
| --- | --- |
| Book and pay | VERIFIED calendar 9–10; NEEDS_APPROVAL for $60; exact concatenated receipt speech |
| Yes, charge it | PENDING, then VERIFIED; one PaymentIntent `pi_e3869a6f59f44fd9aa11af83c9676b8d`; charges applied 1 |
| Move the plumber to ten | PENDING, then NOT_OBSERVED; latest read still 9–10; two ACK-without-write attempts |
| Try that again | Same move operation VERIFIED at 10–11; one write; prior fault label cleared |
| Recap | Two results: latest verified plumber time 10–11 and one $60 deposit; no new writes |

The browser also restored a session after reload without repeating a charge. Operation receipts
retained their history and identifiers. The UI's Before field uses an earlier receipt for the same
operation when `operation_get` does not include `previous`; received structuredContent is unchanged.
The static-only preview at port 8090 also rendered the fixture with the explicit
"Fixture mode · server not connected" banner; its temporary HTTP server was used only for that check.

`tests/test_sim.py` independently exercises all five turns over TCP/SSE, exact receipt speech,
deterministic affirmation with no model call, denial of a model-proposed approval, suppression of
model-written tool outcomes, and consent-token non-disclosure. Server/core tests cover restart replay
windows, late completion after UNKNOWN, per-run fault contexts and reset, auth, schema equality,
and session deletion. No Google, Stripe, Bedrock or Anthropic live acceptance is claimed.

The extra real PENDING on the third turn is documented in `docs/friction-log.md`; a fixed count of
seven fixture receipts is intentionally not used as a live-server invariant.

Final Windows checks: `uv sync` succeeded; `uv run pytest -q` reported **115 passed in 19.14s**;
`uv run ruff check .` and `node --check sim/static/app.js` succeeded. Reading the persisted Fake JSON
independently confirmed one calendar event at 10 AM Los Angeles and exactly one $60 charge for this
run. The final browser console had no errors. The live acceptance data directory is
`%TEMP%/donewise-step2-ui-final`; the temporary static-only preview server has been stopped.

Review this work in two blocks: server/core/Fake concurrency and recovery first, then
simulator/client/agent/UI. The implementation and acceptance tests exceed the standing scope alerts
because these are two requested deliveries, spanning real TCP lifecycle, thread recovery and
consent/LLM/SSE boundaries. Test server startup and the week-one world are reused; no second MCP
fixture server was added. `uv.lock` and `initialize.json` are generated artifacts.
The optional fault proxy is deferred until real-adapter integration (step 1).

## Step 3A — voice controls (17 September 2026)

Validated against the real local MCP server with Fake adapters and `LLM_PROVIDER=none`.
Chrome 153 on Windows used `http://localhost:8082`; 8080 was already occupied and left alone.
MCP ran on 8767, data in `%TEMP%/donewise-step3-acceptance`.

- The five scripted turns completed. Run `run_08302e7ff4b644b5aa890aca4f486d5f` persisted one
  $60 charge, `pi_23cdb8475e5f48e98da1e615e83fc9ff`, and the event ended at 10–11 AM.
  The fault panel showed one lost response and two consumed false acknowledgements. The payment
  JSON independently contained exactly one charge; no live provider was contacted.
- Changing to Free voice created a separate run, hid the whole chapter bar and displayed the live
  voice label plus the explicit model-off limitation. Manual drop armed once, released the controls,
  and survived reload with one use remaining. Text input reached NoLLM without executing a write.
- With a browser recognition double, the transcript was visible before submission, no POST occurred
  before `onend`, and exactly one occurred after it. `not-allowed`, `no-speech` and `aborted` sent none.
  With a synthesis double, the mic was disabled while speech was pending and enabled after ending.
  These are UI wiring checks, **not real microphone capture or acoustic echo acceptance**.
- At 390 px the page had no horizontal overflow. The only recorded console resource error was the
  existing missing favicon (404); no application exception was observed.

Verification: `uv run pytest -q` **120 passed in 29.71 s**; `uv run ruff check .`,
`uv run ruff format --check .`, `node --check sim/static/app.js` passed (format was normalized after
pytest, no semantic change). Two new simulator tests protect fault endpoint disablement and real
TCP/SSE armed/consumed state, concurrent-arm exclusion, busy-mode rejection and run isolation.

Still pending: human Chrome microphone/TTS rehearsal and the five-turn voice story with a real LLM.
No claim of acoustic acceptance or connected Google/Stripe/LLM execution is made.
