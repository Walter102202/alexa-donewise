# Connected simulator acceptance — 12 October 2026 (Chile)

Command (new data paths preserve earlier attempts):

```powershell
uv run --env-file .env python scripts/simulator_smoke.py --provider bedrock --model us.amazon.nova-pro-v1:0 --output data/bedrock-sim-2026-10-12-v3.json --data-dir data/bedrock-sim-2026-10-12-v3
uv run --env-file .env python scripts/simulator_smoke.py --provider anthropic --output data/anthropic-sim-2026-10-12.json --data-dir data/anthropic-sim-2026-10-12
```

Nova: run `run_890feef149ff403a88f9f7372241f36a`, five expected outcomes passed.
[Sanitized receipt evidence and independent Stripe read](bedrock-sim-2026-10-12.json).
Real Google Calendar and Stripe test, simulator backend and real MCP HTTP transport.
No browser, microphone or acoustic verification is claimed.

1. Calendar 09:00–10:00 America/Santiago verified; payment waits for approval.
2. Lost payment response recovered; independent Stripe listing found exactly one
   succeeded USD 60 test PaymentIntent for this run (`livemode=false`).
3. Two false calendar acknowledgements produce NOT_OBSERVED; calendar stays at 09:00.
4. Explicit retry verifies 10:00–11:00 on the same operation. One rejected call was
   corrected by Nova before success; this was not an error-free tool trace.
5. Saved-receipt recap includes observation dates, timezone and zero pending/unverified operations.

Earlier failed attempts are retained privately under `data/bedrock-sim-2026-10-12*`:
the first failed payment creation on a deprecated Stripe parameter; the second
interpreted UTC as local time (13:00 instead of 10:00) and started a new operation on retry.
The model prompt now explicitly explains UTC conversion and reuse of the original
arguments/operation. The acceptance runner checks the requested local hour and
operation identity, in addition to receipt outcomes. A prompt improvement and one
passing live sample do not guarantee correctness for arbitrary natural-language inputs.

Sonnet 4.6 via Anthropic API also completed all five expected outcomes, without
tool errors, in the separate preserved local trace above. The local demo keeps
Anthropic; the header derives its label from server-side provider/model configuration.
The session metadata gained one `model_label` field to connect that label to the UI.

Verification: simulator module 20 tests passed; Stripe/connected HTTP mocks 21
passed; real connected provider smoke 1 passed (USD 1 payment, same-key replay,
read-back, calendar create/move/stale-ETag refusal/cleanup). The new recap has its
separate second-session test in block 3. No full suite was run for this bounded block.
