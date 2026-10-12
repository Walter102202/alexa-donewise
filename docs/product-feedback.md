# Product feedback — Devpost draft

Scope: observed local development, client experiments and connected-provider checks through
18 September 2026. Developer feedback, not a user study. Google Calendar and Stripe test evidence
includes one connected smoke test; cloud deployment and full connected fault acceptance remain
unvalidated. These historical results do not establish current provider or credential availability.

## Tools used and why

| Tool | Actual use | Evidence |
| --- | --- | --- |
| Python MCP SDK 2.2.0 | Stateful HTTP server, structured tools/resources, official client and form elicitation | [Handshake](traces/initialize.json), [elicitation](traces/elicitation.md) |
| MCP Inspector CLI 1.0.2 | Independent discovery of tools and schemas | [CLI trace](traces/inspector-handshake.md) |
| Claude Code 2.1.274 / Sonnet | External client completed five sandbox turns, polling PENDING and using receipt speech | [Client trace](traces/claude-code-client.md) |
| FastAPI, Uvicorn, HTML/CSS/JS | Simulator and real MCP-derived receipts over SSE | [Simulator trace](traces/simulator-flow.md) |
| Pydantic and SQLite | Contracts, operation identity, approvals and append-only receipts | [Contracts](../tests/test_contracts.py), [harness tests](../tests/test_harness.py) |
| pytest, respx, Ruff and uv | Locked dependencies, mocked provider HTTP, verification and formatting | [Verification](traces/docker-compose.md) |
| Docker Compose | Two local services without provider keys; persisted bind-mount data | [Acceptance](traces/docker-compose.md) |
| Browser speech APIs | Voice controls and UI wiring checks with doubles | [Voice trace](traces/simulator-flow.md); acoustic rehearsal pending |
| Google Calendar API / google-auth | Service-account access to a dedicated test calendar; create, read, move and delete events, with conditional updates | [Connected evidence](stripe-sandbox.md#verification-performed), [smoke test](../tests/test_connected_providers.py) |
| Stripe PaymentIntents API / Stripe CLI 1.51.0 | Provision a temporary sandbox, create a test payment and verify identity-preserving replay and read-back | [Setup and evidence](stripe-sandbox.md), [smoke test](../tests/test_connected_providers.py) |

## What worked

The lockfile and Docker made local setup reproducible. Python ClientSession and Inspector discovered
the MCP tools independently. Structured receipts let UI and speech share the verified outcome.
Claude Code polled pending operations without resending writes. Form elicitation accepted and
declined consent over real local TCP; tests independently checked Fake payment counts.

Persisted Fake stores made response-loss recovery and false acknowledgements observable. The
deterministic evaluation reports failure counts and incomplete work with denominators. Its timing
is diagnostic only; it establishes neither provider latency nor real-world reliability.

**Google Calendar API:** the connected check created, reread, rescheduled and deleted a test
event. Reusing a stale ETag rejected the update, and a subsequent read confirmed the intended
event state. Conditional updates and read-back gave us concrete checks for our calendar adapter.

**Stripe API and CLI:** the CLI provisioned a sandbox without commercial account onboarding.
The connected check created a USD 1.00 test PaymentIntent; repeating the request with the same
idempotency key returned the same PaymentIntent ID. Read-back checked its amount, currency,
metadata and successful status. An independent list request found one PaymentIntent with
`livemode: false`. This demonstrates direct provider replay in that run; lost-response recovery
through the harness with connected providers remains unvalidated.

## What was missing or difficult

The SDK's tuple shape and HTTP client type differed from the original brief. Function-derived
schemas needed explicit registration; validation errors needed redaction. Inspector produced a
migration notice. Asynchronous receipts exceeded the fixture count. Claude Code first sent
timezone-naive datetimes and recovered after rejection. The [friction log](friction-log.md)
links each observation to evidence and a reproducible check.

**Google Calendar API:** the first connected smoke test failed because its generated timestamps
included microseconds that Google's read-back discarded. We changed the smoke fixture to use
whole seconds; production date comparison was unchanged. Subsecond inputs remain outside this
proof. A round-trip example showing timestamp precision would help adapter authors avoid this
assumption.

**Stripe CLI:** the sandbox issued an `rkcs_test_` key, while our adapter only accepted `sk_test_`.
Our validation rejected the key before contacting Stripe. We added explicit support for the CLI
prefix while retaining test-mode checks. This was a limitation in our adapter, not a Stripe
payment failure. Showing the sandbox key format alongside API integration examples would help.
The sandbox had a documented expiry of 25 September 2026 unless claimed. The claim flow and
permanent account onboarding from Chile were not validated, and current availability has not
been rechecked. This temporary setup does not establish a durable demo environment.

Actual audio rehearsal, full connected Google/Stripe fault acceptance, the five-turn browser flow
with real providers, full simulator live-model acceptance and measured p50/p95 remain pending.
Desktop setup is unvalidated. The historical Claude Code run did not record its negotiated
protocol version; a separate official-client trace did.

## Zero to hello world

With Docker/Compose installed, obtain the repository, run `docker compose up --build`, open
`http://localhost:8080`, keep Scripted selected and press Continue. A verified Fake calendar event
and bound approval request are the first useful result. Four more Continue actions finish the
story. No provider account is required. The [README](../README.md) gives port overrides; occupied
default ports required those overrides in local acceptance.

For an external-client hello world, run the pinned Inspector tools/list command from the README.
It returns six tools. Payment interaction additionally requires trusted consent. No onboarding
duration was measured, so none is claimed.

**Google Calendar API:** onboarding required enabling the API, creating a service account and
sharing a dedicated test calendar with event-edit permission. The credential JSON stayed outside
the repository, with its path and the calendar ID configured in ignored `.env`. The first useful
result was an event created through the adapter and independently read back from Calendar.

**Stripe CLI and API:** `stripe sandbox create` provisioned the temporary test environment without
browser login or commercial account onboarding. The CLI stored the credentials locally outside
the repository; the application read the test key from ignored `.env`. An authenticated API list
request was the first connection check. After correcting our key-prefix validation, the USD 1.00
payment and same-key replay completed the smoke test. The [setup record](stripe-sandbox.md)
documents the commands, expiry and unvalidated claim path. No provider onboarding duration was
measured.

## Would we use these tools again?

**Yes** for the MCP SDK, Inspector, Python validation/storage stack and Compose: they made the
tool boundary and failure cases inspectable without a provider account. We would pin versions,
retain safe errors and keep transport acceptance tests. **Yes, with explicit consent and receipt
instructions**, for Claude Code as an interoperability client; one recorded run is not proof for
every host. Browser speech would be reused after human rehearsal confirms the audio path.

**Yes** for Google Calendar API / google-auth in this calendar test workflow: dedicated-calendar
access, read-back and ETag checks supported the verification we needed. **Yes** for Stripe's
PaymentIntents API and CLI for payment integration tests: sandbox provisioning and same-key replay
let us exercise the adapter without moving real money. We would verify sandbox lifetime and a
supported renewal or claim path before relying on it for a lasting demo. These recommendations
are limited to the recorded test workflow; production payment onboarding was not evaluated.

Unevaluated Amazon services and command-line tools are deliberately omitted. Planned integrations
belong in the README's pending-validation section, not in an experience report.
