# Lightsail HTTPS and remote Strands — 13 October 2026

Observed with Nova Pro through Bedrock, real Google Calendar and Stripe test.
Five operator-driven turns; final recap uses a fresh, read-only Strands session.

- Instance: `donewise-mcp-20261013`, Ubuntu 24.04, `nano_3_0`, USD 5/month at creation.
- Endpoint: `https://donewise-mcp.duckdns.org/mcp`; valid Let's Encrypt TLS.
- Missing and wrong bearer: 401. `/`, `/healthz`, `/admin/faults`: 404 publicly.
- SQLite persists on the instance. Secrets are separate mode-0600 files; no AWS/Anthropic keys copied.
- Admin faults/consent use a temporary loopback SSH tunnel, closed after the test.
- Run: `run_5030a0e68ed642dab6c1bd505008600b`. One USD 60 test payment: `pi_3UPw9pFik9VWGlFf0GD6olIK`.
- Outcomes: NEEDS_APPROVAL → VERIFIED → NOT_OBSERVED → VERIFIED → recap.
- Independent Stripe PaymentIntent listing found exactly one USD 60 payment for this run,
  with `status=succeeded` and `livemode=false`.
- Explicit retry kept the original reschedule operation ID. Last recap contains two saved observations.

## Latency samples

Client-observed tool round trips from Chile to Lightsail us-east-1. Includes network and
provider work up to the initial receipt; pending polls are listed separately. Tiny sample,
not a production percentile estimate. p95 uses nearest rank; n=1 is one observation.

| Tool | n | p50 ms | p95 ms |
| --- | ---: | ---: | ---: |
| operation_get | 24 | 145 | 160 |
| calendar_create_verified | 1 | 594 | 594 |
| payment_charge_verified | 2 | 384 | 580 |
| approval_grant | 1 | 3155 | 3155 |
| calendar_reschedule_verified | 2 | 594 | 594 |
| receipts_recap | 1 | 172 | 172 |

Full turn times (seconds, including inference and polling): 5.25, 5.78, 11.82, 5.34, 3.26.

## Earlier attempts and correction

Attempt 1 returned a valid recap, then executed a queued calendar-create tool in the same
model response and returned the wrong final receipt. Strands stopping the event loop did
not cancel the remaining tools in that response. The client now rejects all subsequent
tools after recap; a focused regression test covers this. The morning scene also starts a
new session with only receipts_recap exposed, matching the AgentCore entrypoint.

Attempt 2 stopped at the admin call because the task-owned SSH tunnel had ended with its
shell. Attempt 3 kept the tunnel and smoke in one shell and completed all five turns.
Earlier raw traces remain under ignored data; no test data was deleted.

Windows httpx2/truststore raised a native certificate-chain access violation. Using
`SSL_CERT_FILE` pointing to the isolated environment's certifi CA bundle retained full TLS
verification and allowed the native MCP client to connect. No certificate check was disabled.

The remote server is git snapshot `218f1c2` plus the deployment configuration.
Private full trace: `data/strands-lightsail-five-turns-2026-10-13-v3.json`.
