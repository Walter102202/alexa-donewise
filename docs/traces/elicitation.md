# Elicitation over real local MCP HTTP

Captured 2026-09-17 with MCP SDK 2.2.0, official ClientSession, real TCP, FakePayments
and persisted SQLite. No provider credentials or consent token. Run:
`uv run pytest tests/test_server.py -k elicitation -s`.
Each test prints its temporary `elicitation-trace.json` path. Below are short projections
of the actual messages captured in pytest-111 (accept and decline), not invented payloads.
Notifications/initialized, automatic tools/list, and unchanged receipt fields are omitted.
Server elicitation parameters are captured by the official callback; client JSON-RPC
messages are captured by the HTTP request hook, and final data by ClientSession.

## Accept

1. Client initialize, request 1: protocol `2025-11-25`, capability
   `{"elicitation":{"form":{},"url":{}}}`.
2. Client tools/call, request 2:

```json
{"name":"payment_charge_verified","arguments":{"submission_id":"elicited","amount_minor":6000,"currency":"USD","payee":"Ridge Plumbing","concept":"deposit"}}
```

3. Server elicitation/create while request 2 is open (SSE):

```json
{"mode":"form","message":"Approve a $60 test charge to Ridge Plumbing for the deposit?","requestedSchema":{"additionalProperties":false,"properties":{"approve":{"title":"Approve","type":"boolean"}},"required":["approve"],"title":"PaymentConsent","type":"object"}}
```

4. Client response to server request 1:

```json
{"jsonrpc":"2.0","id":1,"result":{"action":"accept","content":{"approve":true}}}
```

5. Server tool result (projection):

```json
{"outcome":"VERIFIED","writes_applied":1,"charges_applied":1,"granted_by":"elicitation","approval_id":"apr_9150f74bdf1146b697539f8a0514f1bd","receipt_id":"rcpt_4972c382cd104b6289b78187b18e860d","payment_intent_id":"pi_4dd50bfc4f1d4dfd957dd8b4665feafc"}
```

Independent assertions: one Fake payment, one consumed bound approval; repeating the
same submission returns the same receipt with no new prompt or provider write.

## Decline

A separate initialized MCP session sends the same payment call and receives the same prompt.
Client response to server request 1:

```json
{"jsonrpc":"2.0","id":1,"result":{"action":"decline"}}
```

Server tool result (projection):

```json
{"outcome":"REJECTED","reason_code":"NO_APPROVAL","writes_applied":0,"charges_applied":0,"next_action":"ASK_USER","approval_id":null,"granted_by":null,"receipt_id":"rcpt_30aa079868a14512a59b04556afc2080"}
```

Independent assertions: zero Fake payment writes and no grant row. Other parameterized
cases cover cancel, boolean false, string "true" (rejected), and timeout followed by late
acceptance (NEEDS_APPROVAL, no write). The timeout test shortens only the server's 120-second
limit to 50 ms. Existing no-capability and simulator journeys cover token-based approval,
with `mcp_client` and `session_ui` provenance respectively.

## Decisions and limits

- Walter approved the optional `granted_by` receipt field in addition to the enum change;
  operation_get preserves it too. Exported JSON schemas include these additive changes.
- SSE is required by the installed SDK: JSON-only mode explicitly disables server requests.
- DONEWISE_PENDING_AFTER=off disables intermediate PENDING receipts; it does not impose a
  6.5-second execution limit or implement the bridge's follow-up behavior. That belongs to
  the bridge and has not been exercised here. UNKNOWN reconciliation remains enabled.
- Tests exercise local MCP and Fake providers, not Alexa, an LLM, Google or Stripe.
