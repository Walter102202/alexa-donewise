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
| Anthropic SDK / Sonnet 4.6 | Model tool selection and clarification in the simulator's small sandbox evaluation | [Recorded results](../README.md#run-connected-with-your-own-keys-opt-in), [evaluation script](../scripts/eval_tool_calls.py) |
| FastAPI, Uvicorn, HTML/CSS/JS | Simulator and real MCP-derived receipts over SSE | [Simulator trace](traces/simulator-flow.md) |
| Pydantic and SQLite | Contracts, operation identity, approvals and append-only receipts | [Contracts](../tests/test_contracts.py), [harness tests](../tests/test_harness.py) |
| pytest, respx, Ruff and uv | Locked dependencies, mocked provider HTTP, verification and formatting | [Verification](traces/docker-compose.md) |
| Docker Compose | Two local services without provider keys; persisted bind-mount data | [Acceptance](traces/docker-compose.md) |
| Browser speech APIs | Voice controls and UI wiring checks with doubles | [Voice trace](traces/simulator-flow.md); acoustic rehearsal pending |
| Google Calendar API / google-auth | Service-account access to a dedicated test calendar; create, read, move and delete events, with conditional updates | [Connected evidence](stripe-sandbox.md#verification-performed), [smoke test](../tests/test_connected_providers.py) |
| Stripe PaymentIntents API / Stripe CLI 1.51.0 | Provision a temporary sandbox, create a test payment and verify identity-preserving replay and read-back | [Setup and evidence](stripe-sandbox.md), [smoke test](../tests/test_connected_providers.py) |

## What worked

These are observed results from the evidence linked above, scoped to the recorded experiments.

| Tool | What worked and why it mattered |
| --- | --- |
| Python MCP SDK | The official client negotiated `2025-11-25`, discovered tools and received structured receipts. Form elicitation accepted and declined consent over local TCP. This made transport and consent independently testable. |
| MCP Inspector CLI | Listed all six tools with input/output schemas outside our simulator, giving us an independent check of the server's published interface. |
| Claude Code / Sonnet | Completed the five sandbox turns, polled `operation_get` after PENDING and did not resend writes. The recorded final Fake state contained one event and one payment. |
| Anthropic SDK / Sonnet 4.6 | In the small simulator evaluation, future-time bookings succeeded on the first call 3/3; past-time requests produced a visible question with zero writes 3/3 and booked after clarification 3/3. This is limited model evidence with Fake providers. |
| FastAPI | Served session endpoints and SSE events used by the real five-turn browser flow, so the UI displayed receipts from MCP operations. |
| Uvicorn | Ran the server and simulator entry points used by the local browser and Docker acceptance checks. This establishes local serving, not hosted performance. |
| HTML/CSS/JavaScript | The UI displayed approval, PENDING, failure and recap states from actual receipts; the recorded 390 px check had no horizontal overflow. |
| Pydantic | Contract tests exercised invalid input and inconsistent receipt rejection; exported schemas could be checked against the published MCP interface. |
| SQLite | Persisted operation identities, approvals and receipts. The restart test resumed the same operation without a second write, supporting recovery in the single-server design. |
| pytest | Exercised contracts, recovery and real TCP/SSE flows. The recorded Windows and Linux packaging runs passed the sandbox suite. |
| respx | Mocked provider HTTP responses and transport failures, allowing adapter error paths to be exercised without provider credentials. |
| Ruff | Lint and format checks passed in the recorded Windows and Linux packaging runs, giving both environments the same source checks. |
| uv | Installed the locked workspace dependencies on Windows and in the Linux container; a separate environment let validation proceed while running services held the original launcher open. |
| Docker Compose | Started both services using Fake adapters without provider keys, with data bound to the host. The five-turn browser run finished with one persisted event and one payment. |
| Browser speech APIs | Recognition and synthesis doubles verified transcript submission and microphone gating. These were UI wiring checks; human microphone/TTS acceptance remains pending. |
| Google Calendar API / google-auth | Created, reread, moved and deleted the test event. A stale ETag rejected the update; subsequent read-back confirmed the intended state. Service-account access worked with the dedicated calendar. |
| Stripe PaymentIntents API | A USD 1.00 test payment and same-key replay returned the same PaymentIntent ID. Read-back checked amount, currency, metadata and status; an independent list found one payment with `livemode: false`. |
| Stripe CLI | Provisioned a temporary sandbox without browser login or commercial account onboarding, enabling the API smoke check. |

The deterministic evaluation measures a finite Fake sample, not provider latency or real-world
reliability. Stripe's direct provider replay does not prove lost-response recovery through the
harness with connected providers.

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

No onboarding durations were measured. For supporting libraries, these entries describe the
exercised setup and useful checks; no separate first-use diary was recorded for each library.
The [friction log](friction-log.md) and linked traces distinguish encountered problems from limits
that remain untested.

| Tool | Setup, first useful result and friction |
| --- | --- |
| Python MCP SDK | Connected a local Streamable HTTP server and `ClientSession`. The stream tuple and HTTP client type differed from the brief; adapting the client resolved the mismatch. Handshake and tool discovery then worked. |
| MCP Inspector CLI | Started the local server and ran the pinned `tools/list` command from the [trace](traces/inspector-handshake.md). It returned six tools and their schemas. An unpinned invocation had printed a migration notice, so the exercised version was pinned. |
| Claude Code / Sonnet | Configured the HTTP MCP endpoint, authentication outside the model and receipt-only instructions. The first booking used dates without offsets; field-specific rejection let the model correct them. Payment consent required a separate trusted operator step. |
| Anthropic SDK / Sonnet 4.6 | Configured the simulator provider, model and private API key, then exercised calendar requests with Fake adapters. The [manual evaluation](../scripts/eval_tool_calls.py) checked first-call booking and clarification; it did not establish the complete voice or connected-provider flow. |
| FastAPI | Wired session and SSE routes to the MCP client. The first scripted booking displayed a verified calendar receipt and a payment approval request; asynchronous PENDING states required rendering actual events instead of assuming a fixed fixture count. |
| Uvicorn | Launched the server and simulator entry points. Occupied default ports required alternate ports during acceptance; the existing processes were left running. |
| HTML/CSS/JavaScript | Started from the story fixture, then connected the UI to live SSE receipts. The recorded browser checks distinguished offline fixture mode from the live MCP session and checked the mobile layout. |
| Pydantic | Defined typed tool inputs and receipts, then exported and compared schemas. Function-derived MCP schemas differed from the canonical models, requiring explicit registration and value-redacted validation errors. |
| SQLite | Opened a registry in an isolated data directory and exercised operation persistence and restart replay. The recorded workflow uses one server process per directory; distributed persistence was not evaluated. |
| pytest | Installed the development dependencies and ran the sandbox suite. An early Linux test-container setup lacked schemas and scripts; including those test inputs resolved the file-not-found failures. |
| respx | Used HTTP mocks in the Google Calendar and Stripe adapter tests to check responses and failures without credentials. A separate onboarding problem was not recorded. |
| Ruff | Ran lint and format checks from the locked environment. The README's Python example needed formatting under the locked Ruff version before the format check passed. |
| uv | Used the workspace and lockfile to install dependencies. Running services held the checkout's launcher open; `UV_PROJECT_ENVIRONMENT` selected a separate validation environment. |
| Docker Compose | Built both targets and used host ports 18765/18080 because the defaults were occupied. In Scripted mode, the first Continue produced a verified Fake event and an approval request; all five turns then completed. |
| Browser speech APIs | Connected recognition callbacks to turn submission and synthesis to receipt speech. Doubles checked submission timing, error handling and microphone gating. Actual microphone capture and acoustic rehearsal remain pending. |
| Google Calendar API / google-auth | Enabled the API, created a service account and shared a dedicated calendar with edit permission. Kept credential JSON outside the repo and its path in ignored `.env`. Created and independently reread an event; later corrected smoke-test timestamps to whole seconds. |
| Stripe CLI | Ran `stripe sandbox create` and kept its credentials outside the repo. Provisioning required no browser login or commercial account onboarding. The temporary sandbox's claim path and permanence from Chile were not validated. |
| Stripe PaymentIntents API | Configured the test key in ignored `.env` and checked an authenticated list request. Our adapter initially rejected the CLI key prefix; after the validation fix, a USD 1.00 test payment, same-key replay and read-back passed. |

Provider commands and the historical sandbox expiry are in the [setup record](stripe-sandbox.md).

## Would we use these tools again?

These decisions concern the uses tested here; they do not imply production acceptance.

| Tool | Decision and reason |
| --- | --- |
| Python MCP SDK | **Yes.** It supported an interface exercised by independent clients. We would pin versions and retain transport, schema and consent checks. |
| MCP Inspector CLI | **Yes.** It gave us a separate way to inspect tool discovery and schemas. The visual Inspector remains unvalidated here. |
| Claude Code / Sonnet | **Yes, as an interoperability client.** It exposed argument and polling issues in a real conversation. We would retain trusted consent and receipt instructions; one run does not establish behavior across clients. |
| Anthropic SDK / Sonnet 4.6 | **Yes, for further simulator experiments.** The small evaluation demonstrated tool selection and clarification through this path. Full voice acceptance, cost and latency still need evaluation. |
| FastAPI | **Yes, for the simulator backend.** Its session routes and SSE responses supported the recorded browser flow. |
| Uvicorn | **Yes, for local serving.** It ran both entry points used in acceptance. Hosted deployment and load behavior remain untested. |
| HTML/CSS/JavaScript | **Yes, for this demo UI.** The implementation displayed live receipt states and passed the recorded mobile-width check. |
| Pydantic | **Yes.** Typed contracts made input validation and schema comparison testable. We would keep explicit schema registration and safe error handling. |
| SQLite | **Yes, for a single-server demo with persistent storage.** It supported identity and receipt recovery; we would not infer distributed-worker support. |
| pytest | **Yes.** It exercises the contracts and recovery failures that matter to this project, including real TCP/SSE integration. |
| respx | **Yes.** It lets us exercise provider HTTP error paths without credentials, alongside separate connected checks. |
| Ruff | **Yes.** It provides repeatable lint and formatting checks across the tested environments. |
| uv | **Yes.** The locked workspace and separate environment setting supported reproducible setup without stopping running services. |
| Docker Compose | **Yes, for the local demo.** Two services and persisted Fake data can be exercised without provider credentials. |
| Browser speech APIs | **Undecided until human rehearsal.** Wiring checks are useful, but microphone and spoken-output quality have not been accepted. |
| Google Calendar API / google-auth | **Yes, for the calendar test workflow.** Dedicated-calendar access, read-back and ETags supported the verification we needed. |
| Stripe PaymentIntents API | **Yes, for payment integration tests.** Read-back and same-key replay exercised the adapter without moving real money. Production payment onboarding was not evaluated. |
| Stripe CLI | **Yes, for temporary test provisioning.** Before relying on it for a lasting demo, we would verify sandbox lifetime and a supported renewal or claim path. |

Unevaluated Amazon services and command-line tools are deliberately omitted. Planned integrations
belong in the README's pending-validation section, not in an experience report.
