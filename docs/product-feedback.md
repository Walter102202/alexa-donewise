# Product feedback — Devpost draft

Scope: observed local development and recorded client experiments through 17 September 2026.
Developer feedback, not a user study. No connected provider run or cloud deployment claimed.

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

## What worked

The lockfile and Docker made local setup reproducible. Python ClientSession and Inspector discovered
the MCP tools independently. Structured receipts let UI and speech share the verified outcome.
Claude Code polled pending operations without resending writes. Form elicitation accepted and
declined consent over real local TCP; tests independently checked Fake payment counts.

Persisted Fake stores made response-loss recovery and false acknowledgements observable. The
deterministic evaluation reports failure counts and incomplete work with denominators. Its timing
is diagnostic only; it establishes neither provider latency nor real-world reliability.

## What was missing or difficult

The SDK's tuple shape and HTTP client type differed from the original brief. Function-derived
schemas needed explicit registration; validation errors needed redaction. Inspector produced a
migration notice. Asynchronous receipts exceeded the fixture count. Claude Code first sent
timezone-naive datetimes and recovered after rejection. The [friction log](friction-log.md)
links each observation to evidence and a reproducible check.

Actual audio rehearsal, connected Google/Stripe acceptance, simulator live-model acceptance and
measured p50/p95 remain pending. Desktop setup is unvalidated. The historical Claude Code run did
not record its negotiated protocol version; a separate official-client trace did.

## Zero to hello world

With Docker/Compose installed, obtain the repository, run `docker compose up --build`, open
`http://localhost:8080`, keep Scripted selected and press Continue. A verified Fake calendar event
and bound approval request are the first useful result. Four more Continue actions finish the
story. No provider account is required. The [README](../README.md) gives port overrides; occupied
default ports required those overrides in local acceptance.

For an external-client hello world, run the pinned Inspector tools/list command from the README.
It returns six tools. Payment interaction additionally requires trusted consent. No onboarding
duration was measured, so none is claimed.

## Would we use these tools again?

**Yes** for the MCP SDK, Inspector, Python validation/storage stack and Compose: they made the
tool boundary and failure cases inspectable without a provider account. We would pin versions,
retain safe errors and keep transport acceptance tests. **Yes, with explicit consent and receipt
instructions**, for Claude Code as an interoperability client; one recorded run is not proof for
every host. Browser speech would be reused after human rehearsal confirms the audio path.

Unevaluated Amazon services and command-line tools are deliberately omitted. Planned integrations
belong in the README's pending-validation section, not in an experience report.
