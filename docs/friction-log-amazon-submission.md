# Amazon integration friction: selected entries

Selected from `docs/friction-log.md` at commit `993ca8d`. Original entry numbers, occurrence dates and severity ratings are retained. The entries describe recorded integration work; resolved historical failures are paired with their workarounds and follow-up evidence.

## #19. Strands executes a queued tool after recap (13 October 2026)

**Task attempted:** End a historical recap without writing.

**Steps taken:** Run Nova Pro through Strands with multiple tools exposed. Command: `python agents/strands_client/smoke.py --five-turns --output data/new-remote-trace.json` in the isolated environment.

**Expected vs. actual result:** Expected: stop_event_loop stops work after receipts_recap. Observed: a later calendar-create in the same model response still executed; the last returned receipt was then the wrong one.

**Severity:** High: unwanted calendar write in a read-only conversation turn.

**Workaround:** Before-tool guard cancels all calls after recap; the morning scene uses a fresh client exposing only recap, as AgentCore already does. Regression test and remote five-turn rerun pass ([evidence](traces/lightsail-2026-10-13.md)).

**Actionable suggestion:** Document that stopping the event loop does not cancel the current batch, or offer a batch-cancellation flag.

## #23. Developer Console simulator microphone returns "No Content" (21 October 2026)

**Task attempted:** Record the Alexa scene of the demo video in the Developer Console Test tab (Development stage, en-US).

**Steps taken:** Click the microphone, say `open done wise`, then the question. Commands: `ask smapi simulate-skill --skill-id <id> --stage development --device-locale en-US --input-content "open done wise"`, then `ask smapi get-skill-simulation`.

**Expected vs. actual result:** Expected a transcript and the spoken receipt; observed `No Content` on every attempt, although Chrome had microphone permission and `getUserMedia` captured audio in the same tab. Typing `open donewise` (one word) answered "I'm not quite sure how to help you with that"; typing `open done wise` (the invocation name, two words) opened the skill; the typed question returned the exact receipt in 2709 ms of skill execution.

**Severity:** Medium: voice testing in the console blocked; typed testing unaffected.

**Workaround:** Type the utterances in the Test tab, prewarm Lambda and AgentCore with the same pair through SMAPI right before recording, and record the typed exchange ([open](traces/alexa-simulation-2026-10-21-open.json) and [question](traces/alexa-simulation-2026-10-21-question.json) simulations; account, device and token values redacted).

**Actionable suggestion:** Report why captured audio produced no content (permission, device, recognition) instead of `No Content`; when a typed utterance matches no enabled invocation name, say so.

## #17. Alexa latency evidence stops at fixed speech (13 October 2026)

**Task attempted:** Prewarm Lambda and validate three next-morning questions.

**Steps taken:** Prewarm Lambda and validate three next-morning questions. Command: `aws bedrock-agentcore-control list-agent-runtimes --profile donewise --region us-east-1`.

**Expected vs. actual result:** Fixed speech passed 3/3, SMAPI skill times 28/43/36 ms; first Lambda init 774.39 ms. AgentCore list was empty, so no receipt/runtime latency or 8-second fallback claim is possible; SDK SyntaxWarnings did not prevent execution.

**Severity:** High for complete receipt acceptance: required runtime is absent.

**Workaround:** Keep explicit fixed-response mode; leave runtime-specific IAM grant and real receipt 3/3 gate pending; CLI polling time (about 10 to 11 s) is reported separately from skill execution. Follow-up to entry 17, 00:43 Chile: AgentCore is deployed and the real receipt gate now passes; fresh warm CLI maximum 3367 ms; exact Alexa pairs 3/3 at 1250/1124/1853 ms, with dates/timezone preserved; the original fixed-response evidence remains historical ([connected proof](traces/alexa-connected-2026-10-13.json) and [recap-only spans](traces/alexa-runtime-spans-2026-10-13.json)).

**Actionable suggestion:** Expose runtime readiness and distinguish simulation-tool overhead from endpoint latency.

## #13. Skill creation validates the trigger before its ID can be scoped (13 October 2026)

**Task attempted:** Create a skill with its own Lambda endpoint, then scope AddPermission to the returned skill ID.

**Steps taken:** Create a skill with its own Lambda endpoint, then scope AddPermission to the returned skill ID. Command: `ask smapi get-skill-status --skill-id <returned-id> --profile default`.

**Expected vs. actual result:** Create returned 202 and an ID, but asynchronous manifest validation failed with `The trigger setting for the Lambda ... is invalid.` Model/manifest updates on that failed ID returned 404.

**Severity:** Medium: bootstrap dependency and failed resource ID.

**Workaround:** Create without endpoint; wait for success; add skill-scoped Lambda permission; update manifest. One active skill verified in vendor listing ([reproducible sequence](../integrations/alexa/README.md) and [trace](traces/alexa-2026-10-13.md)).

**Actionable suggestion:** Document this bootstrap order and make asynchronous failures explicit in CLI output.

## #11. ASK CLI diagnostics and Windows invocation (13 October 2026)

**Task attempted:** Configure ASK 2.30.7 on Windows; list skills and diagnose a manifest rejection.

**Steps taken:** `list-skills-for-vendor --vendor-id ...` rejected the flag because this CLI takes the vendor from its profile. Command: `ask smapi list-skills-for-vendor --profile default`.

**Expected vs. actual result:** LWA worked; AWS association was declined. Ordinary errors exposed only HTTP 400/403 and a stack; debug error objects included Authorization headers.

**Severity:** Medium: poor diagnostics; raw debug output contains credentials.

**Workaround:** Use `--profile default`; capture diagnostics only under ignored data, extract only the response body, redact auth values; do not publish raw debug files ([Alexa trace](traces/alexa-2026-10-13.md)).

**Actionable suggestion:** Include safe validation details in normal errors and redact nested Axios headers in debug output.

## #15. Initial Development enablement returned an empty 403 (13 October 2026)

**Task attempted:** Enable Development testing after uploading the model.

**Steps taken:** Enable Development testing after uploading the model. Command: `ask smapi set-skill-enablement --skill-id amzn1.ask.skill.34982f14-6b4a-47c6-9b65-f0649d1c6a0b --stage development --profile default`.

**Expected vs. actual result:** Two 403 responses with `{}` body. Full model later SUCCEEDED; console Test displayed Development enabled; retry returned 204 at 00:15:38 Chile.

**Severity:** Medium: testing initially blocked.

**Workaround:** Wait for model build, open Test and verify Development, retry the same command; exact initial cause not established ([trace](traces/alexa-2026-10-13.md)).

**Actionable suggestion:** Return an actionable reason distinguishing build readiness from account/test enablement.

## #21. AgentCore creation checks dependent identities before a final runtime ARN (13 October 2026)

**Task attempted:** Create tagged DoneWise runtime under scoped IAM permissions.

**Steps taken:** Create tagged DoneWise runtime under scoped IAM permissions. Command: `aws bedrock-agentcore-control create-agent-runtime`.

**Expected vs. actual result:** TagResource/endpoint and workload identity/directory authorization needed separate creation grants; request Project tag did not propagate to every dependent check.

**Severity:** Medium: runtime creation initially denied.

**Workaround:** Approved creation/tagging policy with account, region and expiry restrictions; operating permissions remain scoped to donewise resources. Inline cloud JSON was compared exactly to the working tree ([policy](../deploy/aws-runtime-creation-tagging-policy.json) and [actual deployment](traces/agentcore-2026-10-13.md)).

**Actionable suggestion:** Document the full dependent-action/resource matrix for runtime creation.

## #20. AgentCore toolkit source bucket conflicts with deployment scope (13 October 2026)

**Task attempted:** Configure a container deployment with the AgentCore starter toolkit, then launch.

**Steps taken:** Configure a container deployment with the AgentCore starter toolkit, then launch. Command: `agentcore launch`.

**Expected vs. actual result:** Toolkit 0.3.14 selected fixed bucket bedrock-agentcore-codebuild-sources-027018013541-us-east-1, outside the approved donewise-prefixed artifacts policy; CodeBuild did not run. That toolkit reports itself deprecated in favor of @aws/agentcore ([recorded deployment](traces/agentcore-2026-10-13.md)).

**Severity:** Medium: default launch path blocked.

**Workaround:** Approved local buildx ARM64 fallback, ECR push and control-plane creation; image digest and actual runtime recorded.

**Actionable suggestion:** Allow a caller-supplied source bucket and show required resource names before launch.

## #8. Bedrock evaluation schema (12 October 2026)

**Task attempted:** Run the same fault matrix with Nova, Sonnet and gpt-oss.

**Steps taken:** Invoke the LLM evaluator with each Bedrock model. Set `LLM_PROVIDER=bedrock` and selected `BEDROCK_MODEL_ID`; run `uv run --env-file .env donewise-evals --runner llm --output-dir data/new-eval`.

**Expected vs. actual result:** Expected: shared logical tool capabilities. Observed: Sonnet rejected top-level anyOf in optional read schemas before scenario execution.

**Severity:** Medium: API schema compatibility.

**Workaround:** Keep both lookup fields and validate at execution; retain accepted Nova evidence ([three-model results, annotations and limits](../evals/README.md)).

**Actionable suggestion:** Bedrock: expose model-specific JSON Schema restrictions before invocation.

## #7. Nova time/retry errors (12 October 2026)

**Task attempted:** Complete the five-turn connected simulator with Nova Pro.

**Steps taken:** Run simulator smoke. Command: `uv run --env-file .env python scripts/simulator_smoke.py --provider bedrock --model us.amazon.nova-pro-v1:0 --output data/new-smoke.json --data-dir data/new-smoke`.

**Expected vs. actual result:** Expected: requested local time preserved; explicit retry reuses the operation. Observed: Nova used 13:00 instead of 10:00 and a new operation on retry.

**Severity:** High: incorrect requested calendar time.

**Workaround:** Explicit UTC/retry prompt guidance; live acceptance now checks local hour and operation identity. Third Nova attempt passed, with one rejected/corrected call; Sonnet API passed separately ([connected run and limits](traces/bedrock-sim-2026-10-12.md)).

**Actionable suggestion:** Bedrock/Nova: include timezone and identifier-preservation cases in tool-use examples.

Full log, 23 entries with commands and evidence: https://github.com/Walter102202/alexa-donewise/blob/main/docs/friction-log.md
