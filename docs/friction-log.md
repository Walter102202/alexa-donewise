# Integration friction — Amazon submission format

Observed local work only. This reformats the existing log without inventing occurrence dates.
Historical failures fixed in code are paired with regression commands, not presented as failures
that must still occur. Severity: high = safety/contract risk; medium = blocked integration or
extra interaction; low = setup/documentation inconvenience.

## 1. Python MCP 2.2.0 transport shape

| Field | Observation |
| --- | --- |
| Task | Connect the Python simulator and acceptance client over Streamable HTTP |
| Steps | Enter `streamable_http_client` with `httpx2.AsyncClient`; access `streams.read_stream` as described in the original brief |
| Expected | Named read/write stream attributes |
| Observed | Two-element tuple; `AttributeError: 'tuple' object has no attribute 'read_stream'` |
| Severity | Medium: integration blocked |
| Workaround | Use `ClientSession(*streams)` and the SDK's `httpx2` client |
| Suggestion | Version examples and show the context-manager return shape and HTTP client type |
| Evidence | [Working client](../sim/donewise_sim/mcp_client.py), [initialize trace](traces/initialize.json) |
| Reproducible command | `uv run pytest tests/test_server.py -k official_client_contract_and_pending -q` exercises corrected transport and handshake |

Status: workaround implemented; protocol negotiation remains `2025-11-25`.

## 2. SDK validation and contract fidelity

| Field | Observation |
| --- | --- |
| Task | Publish canonical contracts without exposing rejected consent values |
| Steps | Generate tools from functions; compare schemas with canonical models; submit invalid tool input |
| Expected | Exact schemas and errors without capability values |
| Observed | Function-derived titles/configuration differed; default validation errors could echo rejected values |
| Severity | High: contract drift and possible capability disclosure |
| Workaround | Supply canonical schemas and validate through the safe wrapper |
| Suggestion | Document explicit-schema registration and value-redacted errors |
| Evidence | [Wrapper](../server/donewise_server/tools.py), [acceptance](../tests/test_server.py) |
| Reproducible command | `uv run pytest tests/test_server.py -k official_client_contract_and_pending -q` checks schema equality and safe rejection |

Status: corrected locally. The command verifies the fix, not the historical unsafe behavior.

## 3. Inspector package resolution

| Field | Observation |
| --- | --- |
| Task | List local MCP tools with an external client |
| Steps | Run unpinned Inspector help, then tools/list |
| Expected | Unambiguous supported CLI version |
| Observed | Local unpinned invocation resolved 1.0.2 and printed a notice recommending v2 |
| Severity | Low: version ambiguity |
| Workaround | Pin exercised 1.0.2 and label newer versions unvalidated |
| Suggestion | Make migration/version information and reproducible CLI examples easy to find |
| Evidence | [Inspector trace](traces/inspector-handshake.md) |
| Reproducible command | With Compose running: `npx --yes @modelcontextprotocol/inspector@1.0.2 --cli http://127.0.0.1:8765/mcp --transport http --method tools/list` |

Historical discovery command: `npx --yes @modelcontextprotocol/inspector --help`.
Unpinned resolution can change; the old notice need not recur.

## 4. Fixture count versus asynchronous receipts

| Field | Observation |
| --- | --- |
| Task | Render the five-turn story with live MCP/SSE |
| Steps | Run Scripted mode; inject two acknowledgements without calendar writes on the move turn |
| Expected | Initial fixture assumption: seven receipts with immediate final outcomes |
| Observed | Two real read windows can emit PENDING before NOT_OBSERVED |
| Severity | Medium: fixed fixture count misrepresents runtime behavior |
| Workaround | Render actual receipts and deduplicate unchanged polls; accept intermediate states |
| Suggestion | Separate fixture story states from asynchronous receipt counts in examples |
| Evidence | [Simulator trace](traces/simulator-flow.md), [SSE test](../tests/test_sim.py) |
| Reproducible command | `uv run pytest tests/test_sim.py -k five_scripted_turns_over_mcp_and_sse -q` |

Status: UI handles the intermediate state. This is a local integration lesson, not an Amazon
service failure.

## 5. Datetime inputs from an unfamiliar client

| Field | Observation |
| --- | --- |
| Task | Create a calendar event through Claude Code |
| Steps | Send the first booking turn in the recorded client run; inspect its start/end arguments |
| Expected | Offset-aware ISO 8601 input on the first call |
| Observed | Model omitted offsets; `Invalid tool input: end, start`; model corrected itself |
| Severity | Medium: extra tool round trip |
| Workaround | Include offsets or `Z`; preserve field-specific safe errors |
| Suggestion | Describe the offset requirement explicitly in a future functional change |
| Evidence | [Client trace](traces/claude-code-client.md), [schema](schemas/calendar_create_verified.input.json), [validation tests](../tests/test_contracts.py) |
| Reproducible command | `uv run pytest tests/test_contracts.py -q` checks deterministic validation; the trace contains configuration for repeating the model session |

The exact model mistake is nondeterministic. No paid model run was performed for this log.
No AgentCore or ASK CLI experience is asserted in the historical entries above.

## 6. Bedrock model access and budget visibility — 12 October 2026

| Field | Observation |
| --- | --- |
| Task | Run the first Bedrock text/tool smoke in the personal DoneWise account |
| Steps | STS with profile `donewise`; Converse with Terra, Nova Pro, Sonnet 4.6 and gpt-oss-120b; describe budgets |
| Expected | Available models accept text and canonical tool schemas; budget actions can be inspected |
| Observed | Nova, Sonnet and gpt-oss passed both probes. Terra returned model-specific AccessDenied, no longer the prior account-verification message. Budgets denied `budgets:ViewBudget` |
| Severity | Medium: selected development model unavailable; budget action coverage unverified |
| Workaround | Use the approved Nova/gpt-oss fallbacks. Walter explicitly retained existing budget alerts; no alert edits |
| Suggestion | Distinguish model entitlement from account verification in onboarding; show which principal a budget action actually covers |
| Command | `uv run python scripts/bedrock_smoke.py --output data/bedrock-smoke-new.json` |
| Evidence | [Smoke, commands and limits](traces/bedrock-smoke-2026-10-12.md), [request IDs and output](traces/bedrock-smoke-2026-10-12.json) |

## 7. Connected Stripe renewal and Nova time/retry errors — 12 October 2026

| Field | Observation |
| --- | --- |
| Task | Complete the five-turn connected simulator with Nova Pro |
| Steps | Renew expired Stripe sandbox; run connected provider smoke and simulator smoke |
| Expected | One test payment; requested local time preserved; explicit retry reuses the operation |
| Observed | Old key expired; new sandbox rejected `payment_method_types`. After fixing that, Nova used 13:00 instead of 10:00 and a new operation on retry |
| Severity | High: provider incompatibility and incorrect requested calendar time |
| Workaround | Authorized minimal Stripe API migration; explicit UTC/retry prompt guidance; live acceptance now checks local hour and operation identity. Third Nova attempt passed, with one rejected/corrected call; Sonnet API passed separately |
| Suggestion | Stripe: surface version changes during sandbox renewal. Bedrock/Nova: include timezone and identifier-preservation cases in tool-use examples |
| Command | `uv run --env-file .env python scripts/simulator_smoke.py --provider bedrock --model us.amazon.nova-pro-v1:0 --output data/new-smoke.json --data-dir data/new-smoke` |
| Evidence | [Connected run and limits](traces/bedrock-sim-2026-10-12.md) |

## 8. Bedrock evaluation schema and Windows output — 12 October 2026

| Field | Observation |
| --- | --- |
| Task | Run the same fault matrix with Nova, Sonnet and gpt-oss |
| Steps | Invoke the LLM evaluator with each Bedrock model |
| Expected | Shared logical tool capabilities; results saved and printed |
| Observed | Sonnet rejected top-level anyOf in optional read schemas before scenario execution. Its successful run later saved results but cp1252 could not print an emoji |
| Severity | Medium: API schema compatibility; low: terminal output encoding |
| Workaround | Keep both lookup fields and validate at execution; retain accepted Nova evidence. Use PYTHONIOENCODING=utf-8; do not repeat the already-saved Sonnet run |
| Suggestion | Bedrock: expose model-specific JSON Schema restrictions before invocation. Windows tools: default to UTF-8 or escape unsupported console output |
| Command | Set `LLM_PROVIDER=bedrock`, selected `BEDROCK_MODEL_ID`, `PYTHONIOENCODING=utf-8`; run `uv run --env-file .env donewise-evals --runner llm --output-dir data/new-eval` |
| Evidence | [Three-model results, annotations and limits](../evals/README.md) |

## 9. Strands dependency boundary on Windows — 12 October 2026

| Field | Observation |
| --- | --- |
| Task | Connect a native Strands MCP client to DoneWise |
| Steps | Inspect/install Strands 1.60.0; run five connected turns |
| Expected | An interoperable HTTP client with local timezone support |
| Observed | Strands requires MCP below 2.2 while server requires 2.2+. Windows environment lacked tzdata and failed before inference |
| Severity | Medium: packaging/startup blocked |
| Workaround | Separate client environment; explicit tzdata dependency; same HTTP protocol. Five turns and fresh-session recap then passed |
| Suggestion | Include Windows timezone dependencies and a client/server version matrix in the SDK quickstart |
| Command | `uv pip install --python data/strands-venv/Scripts/python.exe -r agents/strands_client/requirements.txt` then the documented smoke |
| Evidence | [Strands trace](traces/strands-local-2026-10-12.md) |

## 10. AWS deployment principal lacks service access — 12 October 2026

| Field | Observation |
| --- | --- |
| Task | Prepare Lightsail, AgentCore and Lambda deployment |
| Steps | Verify STS; query Lightsail instances and IAM policies with `donewise`; repeat after Walter requested a retry; inspect the personal account's IAM console |
| Expected | Deployment permissions on the personal account |
| Observed | Both CLI attempts denied Lightsail GetInstances and IAM ListAttachedUserPolicies. Console showed only AmazonBedrockLimitedAccess and IAMUserChangePassword |
| Severity | Medium: cloud deployment blocked |
| Workaround | Walter approved the time-limited policy; applied in the personal console, then deployed Lightsail. AgentCore required additional creation dependencies, recorded below |
| Suggestion | Onboarding should separate model inference permission from hosting/build/pass-role permissions |
| Command | `aws lightsail get-instances --profile donewise --region us-east-1` |
| Evidence | [Prepared policy](../deploy/aws-deployment-policy.json), [deployment instructions](../deploy/lightsail/README.md) |

## 11. ASK CLI diagnostics and Windows invocation — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Configure ASK 2.30.7 on Windows; list skills and diagnose a manifest rejection |
| Expected / observed | LWA worked; AWS association was declined. `list-skills-for-vendor --vendor-id ...` rejected the flag because this CLI takes the vendor from its profile. Ordinary errors exposed only HTTP 400/403 and a stack; debug error objects included Authorization headers |
| Severity | Medium: poor diagnostics; raw debug output contains credentials |
| Workaround | Use `--profile default`; capture diagnostics only under ignored data, extract only the response body, redact auth values; do not publish raw debug files |
| Suggestion | Include safe validation details in normal errors and redact nested Axios headers in debug output |
| Command / evidence | `ask smapi list-skills-for-vendor --profile default`; [Alexa trace](traces/alexa-2026-10-13.md) |

## 12. Manifest category enum mismatch — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Create the initial Custom skill manifest |
| Expected / observed | Authoring used `PRODUCTIVITY`; SMAPI rejected it with `INVALID_ENUM_VALUE`. This was a manifest authoring error, not a service failure |
| Severity | Low: creation blocked until corrected |
| Workaround / suggestion | Use documented `ORGANIZERS_AND_ASSISTANTS`; expose valid enum values in the CLI error |
| Command / evidence | `ask smapi create-skill-for-vendor --manifest file:integrations/alexa/skill.json --profile default`; [corrected manifest](../integrations/alexa/skill.json), [trace](traces/alexa-2026-10-13.md) |

## 13. Skill creation validates the trigger before its ID can be scoped — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Create a skill with its own Lambda endpoint, then scope AddPermission to the returned skill ID |
| Expected / observed | Create returned 202 and an ID, but asynchronous manifest validation failed with `The trigger setting for the Lambda ... is invalid.` Model/manifest updates on that failed ID returned 404 |
| Severity | Medium: bootstrap dependency and failed resource ID |
| Workaround | Create without endpoint; wait for success; add skill-scoped Lambda permission; update manifest. One active skill verified in vendor listing |
| Suggestion | Document this bootstrap order and make asynchronous failures explicit in CLI output |
| Command / evidence | `ask smapi get-skill-status --skill-id <returned-id> --profile default`; [reproducible sequence](../integrations/alexa/README.md), [trace](traces/alexa-2026-10-13.md) |

## 14. Deployment IAM permits adding but not inspecting/removing triggers — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Remove the old trigger after failed skill creation; inspect the final policy |
| Expected / observed | `lambda:RemovePermission` and `lambda:GetPolicy` denied for donewise-alexa. Removal still denied after Walter confirmed permission; role creation, policy attachment, Lambda creation and AddPermission succeeded |
| Severity | Medium: stale scoped statement remains; full policy read unavailable |
| Workaround | Active statement uses the correct skill ID; handler also validates it. Old statement only targets the failed ID. Cleanup remains pending an effective IAM grant |
| Suggestion | Include read/cleanup actions alongside create/add permissions in bounded deployment policies |
| Command / evidence | `aws lambda remove-permission --function-name donewise-alexa --statement-id AlexaSkillDevelopment --profile donewise --region us-east-1`; [trace and cleanup](traces/alexa-2026-10-13.md) |

Follow-up to entry 14, 00:37–00:39 Chile: Walter authorized console execution.
DoneWiseDeployment20261013 now grants GetPolicy/RemovePermission on the exact
donewise-alexa ARN. Both the failed-ID trigger and an identical active-ID duplicate
were removed. Fresh GetPolicy confirms only the current skill-scoped statement.
This blocker is resolved; [final evidence](traces/alexa-connected-2026-10-13.json).

## 15. Initial Development enablement returned an empty 403 — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Enable Development testing after uploading the model |
| Expected / observed | Two 403 responses with `{}` body. Full model later SUCCEEDED; console Test displayed Development enabled; retry returned 204 at 00:15:38 Chile |
| Severity | Medium: testing initially blocked |
| Workaround | Wait for model build, open Test and verify Development, retry the same command; exact initial cause not established |
| Suggestion | Return an actionable reason distinguishing build readiness from account/test enablement |
| Command / evidence | `ask smapi set-skill-enablement --skill-id amzn1.ask.skill.34982f14-6b4a-47c6-9b65-f0649d1c6a0b --stage development --profile default`; [trace](traces/alexa-2026-10-13.md) |

## 16. Windows timezone dependency in evidence capture — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Timestamp real Alexa simulation evidence in America/Santiago |
| Expected / observed | Isolated Python environment lacked tzdata; local recorder raised `ZoneInfoNotFoundError` after a simulation. This was local tooling, not a Lambda failure |
| Severity | Low: first evidence-capture attempt incomplete |
| Workaround / suggestion | Install tzdata only in isolated evidence environment; declare timezone dependency when using ZoneInfo on Windows |
| Command / evidence | `uv pip install --python data/alexa-venv/Scripts/python.exe tzdata`; [six completed simulations](traces/alexa-simulation-2026-10-13.json) |

## 17. Alexa latency evidence stops at fixed speech — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Prewarm Lambda and validate three next-morning questions |
| Expected / observed | Fixed speech passed 3/3, SMAPI skill times 28/43/36 ms. First Lambda init 774.39 ms. AgentCore list was empty, so no receipt/runtime latency or 8-second fallback claim is possible. SDK SyntaxWarnings did not prevent execution |
| Severity | High for complete receipt acceptance: required runtime is absent |
| Workaround | Keep explicit fixed-response mode; leave runtime-specific IAM grant and real receipt 3/3 gate pending. CLI polling time (about 10–11 s) is reported separately from skill execution |
| Suggestion | Expose runtime readiness and distinguish simulation-tool overhead from endpoint latency |
| Command / evidence | `aws bedrock-agentcore-control list-agent-runtimes --profile donewise --region us-east-1`; [timings and limits](traces/alexa-2026-10-13.md), [wiring commands](../integrations/alexa/README.md) |

Follow-up to entry 17, 00:43 Chile: AgentCore is deployed and the real receipt gate
now passes. Fresh warm CLI maximum 3367 ms; exact Alexa pairs 3/3 at 1250/1124/1853 ms,
with dates/timezone preserved. The original fixed-response evidence remains historical.
[Connected proof](traces/alexa-connected-2026-10-13.json) and
[recap-only spans](traces/alexa-runtime-spans-2026-10-13.json).

## 18. Lightsail Caddy routing and Windows TLS — 13 October 2026

| Field | Observation |
| --- | --- |
| Task | Reach a private MCP endpoint over public HTTPS |
| Steps | Deploy Compose on Ubuntu nano instance; call MCP from Strands on Windows |
| Expected | Valid TLS and authenticated MCP, admin private |
| Observed | Caddy sorted the catch-all response before the proxy; replacing a bind-mounted file also left its old inode mounted. Windows httpx2/truststore later raised a native certificate-chain access violation |
| Severity | Medium: endpoint/client initialization blocked |
| Workaround | Mutually exclusive Caddy handle blocks, recreate only Caddy; SSL_CERT_FILE points to certifi, retaining TLS verification |
| Suggestion | Caddy: make handler ordering visible during validation. SDK: document the Windows certificate-store dependency and fallback CA bundle |
| Command | `docker compose --env-file /opt/donewise/private/compose.env -f deploy/lightsail/compose.yaml up -d`; run documented Strands smoke with SSL_CERT_FILE |
| Evidence | [Remote five-turn proof and latency](traces/lightsail-2026-10-13.md) |

## 19. Strands executes a queued tool after recap — 13 October 2026

| Field | Observation |
| --- | --- |
| Task | End a historical recap without writing |
| Steps | Run Nova Pro through Strands with multiple tools exposed |
| Expected | stop_event_loop stops work after receipts_recap |
| Observed | A later calendar-create in the same model response still executed; the last returned receipt was then the wrong one |
| Severity | High: unwanted calendar write in a read-only conversation turn |
| Workaround | Before-tool guard cancels all calls after recap; the morning scene uses a fresh client exposing only recap, as AgentCore already does. Regression test and remote five-turn rerun pass |
| Suggestion | Document that stopping the event loop does not cancel the current batch, or offer a batch-cancellation flag |
| Command | `python agents/strands_client/smoke.py --five-turns --output data/new-remote-trace.json` in the isolated environment |
| Evidence | [Earlier attempts and successful rerun](traces/lightsail-2026-10-13.md) |

## 20. AgentCore toolkit source bucket conflicts with deployment scope — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Configure a container deployment with the AgentCore starter toolkit, then launch |
| Expected / observed | Toolkit 0.3.14 selected fixed bucket bedrock-agentcore-codebuild-sources-027018013541-us-east-1, outside the approved donewise-prefixed artifacts policy. CodeBuild did not run |
| Severity | Medium: default launch path blocked |
| Workaround | Approved local buildx ARM64 fallback, ECR push and control-plane creation; image digest and actual runtime recorded |
| Suggestion | Allow a caller-supplied source bucket and show required resource names before launch |
| Command / evidence | `agentcore launch`; [deployment and gate](traces/agentcore-2026-10-13.md) |

## 21. AgentCore creation checks dependent identities before a final runtime ARN — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Create tagged DoneWise runtime under scoped IAM permissions |
| Expected / observed | TagResource/endpoint and workload identity/directory authorization needed separate creation grants; request Project tag did not propagate to every dependent check |
| Severity | Medium: runtime creation initially denied |
| Workaround | Approved creation/tagging policy with account, region and expiry restrictions; operating permissions remain scoped to donewise resources. Inline cloud JSON was compared exactly to the working tree |
| Suggestion | Document the full dependent-action/resource matrix for runtime creation |
| Command / evidence | `aws bedrock-agentcore-control create-agent-runtime`; [policy](../deploy/aws-runtime-creation-tagging-policy.json), [actual deployment](traces/agentcore-2026-10-13.md) |

## 22. Concurrent closure and ambiguous demo run provenance — 13 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Finish Alexa while the AWS Builder chat was also closing AgentCore |
| Expected / observed | Runtime already existed and used the original Sonnet demo run; a different run ID in the remote Strands smoke trace initially looked inconsistent. Trigger policy also had two identical active-skill statements |
| Severity | Medium: risk of replacing the demo story or overwriting concurrent work |
| Workaround | Walter authorized chat coordination; assigned one writer per surface, kept the original demo run_b7d652a00a1e444d9ba6e54b0823107c copied to Lightsail, reused runtime v1, removed duplicate trigger, preserved each evidence set separately |
| Suggestion | Record demo versus smoke run provenance explicitly alongside runtime configuration |
| Command / evidence | `aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id donewise_receipts-wbsa177WJQ --profile donewise --region us-east-1` (do not publish its secret environment); [final receipt identity](traces/alexa-connected-2026-10-13.json) |

## 23. Developer Console simulator microphone returns "No Content" — 21 October 2026

| Field | Observation |
| --- | --- |
| Task / steps | Record the Alexa scene of the demo video in the Developer Console Test tab (Development stage, en-US): click the microphone, say `open done wise`, then the question |
| Expected / observed | Expected a transcript and the spoken receipt. Observed `No Content` on every attempt, although Chrome had microphone permission and `getUserMedia` captured audio in the same tab. Typing `open donewise` (one word) answered "I'm not quite sure how to help you with that"; typing `open done wise` (the invocation name, two words) opened the skill. The typed question returned the exact receipt in 2709 ms of skill execution |
| Severity | Medium: voice testing in the console blocked; typed testing unaffected |
| Workaround | Type the utterances in the Test tab, prewarm Lambda and AgentCore with the same pair through SMAPI right before recording, and record the typed exchange |
| Suggestion | Report why captured audio produced no content (permission, device, recognition) instead of `No Content`; when a typed utterance matches no enabled invocation name, say so |
| Command / evidence | `ask smapi simulate-skill --skill-id <id> --stage development --device-locale en-US --input-content "open done wise"`, then `ask smapi get-skill-simulation`; [open](traces/alexa-simulation-2026-10-21-open.json) and [question](traces/alexa-simulation-2026-10-21-question.json) simulations (account, device and token values redacted) |
