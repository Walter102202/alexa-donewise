# Claude Code as an external MCP client — 2026-09-16

Goal: show that a client we did not write completes the five-turn story against the DoneWise
server over Streamable HTTP, driven only by the receipts. No real adapters, credentials or charges.

## Setup

- Server: `uv run donewise-server` on `127.0.0.1:8766`, sandbox mode (Fake adapters), fresh data
  directory, `MCP_BEARER_TOKEN` and `DEMO_ADMIN_TOKEN` set.
- Client: Claude Code CLI 2.1.274, model Sonnet, non-interactive (`claude -p`), MCP config:

```json
{"mcpServers":{"donewise":{"type":"http","url":"http://127.0.0.1:8766/mcp",
 "headers":{"Authorization":"Bearer <token>","X-DoneWise-Run-Id":"run_claudecode01"}}}}
```

- Flags: `--strict-mcp-config --allowedTools "mcp__donewise__*"`, one `claude -p` call per turn,
  `--session-id` / `--resume` to keep the conversation. The prompt told the model to answer with the
  receipt's `spoken` verbatim, never to retry a write, and to poll `operation_get` while a receipt
  says `PENDING` with `next_action: CHECK_EXISTING_OPERATION`.
- Consent stayed outside the model (RF-24): the operator fetched the consent token from
  `/admin/consent-token` and called `approval_grant` with the official Python client. The model only
  received the resulting `approval_id`. Faults were armed through `/admin/faults` before turns 2 and 3.

## Observed

| Turn | User | Receipts persisted (in order) | Assistant reply (receipt `spoken`, verbatim) |
| --- | --- | --- | --- |
| 1 | Book the plumber tomorrow nine to ten and pay the sixty-dollar deposit to Ridge Plumbing. | CALENDAR_CREATE VERIFIED (1 write); PAYMENT_CHARGE NEEDS_APPROVAL (0 writes) | "It's on your calendar: Plumber appointment, 2026-09-18 9 to 10 AM." + "For the Deposit for plumber appointment: a $60 test charge for Ridge Plumbing. Should I charge it?" |
| 2 | Yes, charge it. (fault armed: `drop_response_after_write`) | PAYMENT_CHARGE PENDING; then VERIFIED, `WRITE_RESPONSE_LOST_RECOVERED`, writes 1, automatic retries 1 | "Done: a $60 test charge is recorded for Ridge Plumbing's Deposit for plumber appointment, charged once. Confirmation pi_e8d0…. You don't need to try again." |
| 3 | I'm running late. Move the plumber to ten. (fault armed: `ack_without_write` × 2) | CALENDAR_RESCHEDULE PENDING; then NOT_OBSERVED, `REPLAY_BUDGET_EXHAUSTED`, writes 0, automatic retries 1 | "I couldn't confirm the change. I tried twice; the latest calendar check still shows 9 AM." |
| 4 | Try that again. | CALENDAR_RESCHEDULE VERIFIED on the same operation (`retry_of_operation_id`), 1 write | "The plumber is now at 10 to 11 AM. I read it back from your calendar." |
| 5 | Recap tomorrow. And what did you charge? | receipts_recap (read-only) | "From the receipts in this conversation: the plumber is at 10 to 11 AM, read back at 7:57 PM. One $60 test charge for the Deposit for plumber appointment, read back at 7:55 PM. Nothing new was written." |

The model polled `operation_get` on its own after each `PENDING` (turns 2 and 3) and never resent a
write. The Fake stores ended with one calendar event at 10–11 and exactly one $60 charge.

Differences from the scripted story are the model's wording of inputs (title "Plumber appointment",
concept "Deposit for plumber appointment", the date in the create receipt because the prompt gave
the model a fixed "today"); every state, count and time came from receipts.

## Friction found

- The model's first `calendar_create_verified` call was rejected with
  `Invalid tool input: end, start` (it sent datetimes without a timezone offset). It corrected itself
  on the next call because the error names the fields. The schema only says `format: date-time`;
  a field description stating "ISO 8601 with offset or Z" would avoid the round trip.
- `protocol_sessions` recorded nothing for the Claude Code sessions, while the Python client's
  session was recorded. The negotiated version for this client was therefore not captured server-side.
- `approval_grant` always records `granted_by: session_ui`; for a client like this one the PRD expects
  `mcp_client`.

Session identifiers and tokens are intentionally not included.
