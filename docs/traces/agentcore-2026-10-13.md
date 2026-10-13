# AgentCore Runtime proof — 13 October 2026

- Runtime: `arn:aws:bedrock-agentcore:us-east-1:027018013541:runtime/donewise_receipts-wbsa177WJQ`, version 1, endpoint DEFAULT, us-east-1.
- Client: Strands 1.60.0, Nova Pro `us.amazon.nova-pro-v1:0`, ARM64 container.
- Image: `donewise-strands:20261013-otel-v2`, digest
  `sha256:7de51e6646f05a94726f8b43c38442564a1d808788b0b3e1c5b022f0170b0964`.
- MCP: `https://donewise-mcp.duckdns.org/mcp`, authenticated with a private bearer.
- Saved run: `run_b7d652a00a1e444d9ba6e54b0823107c`, user `demo`.
- Each invocation starts a fresh read-only agent. Caller payload accepts only the prompt;
  the run is configured by the operator. Only receipts_recap is exposed.
- All four measured invocations returned two saved observations and exactly
  `speech == receipt.spoken`. No additional model call after the receipt.

## Measured response times

| Invocation | Client-observed milliseconds |
| --- | ---: |
| First request, new session on the newly deployed runtime | 2579 |
| Warm 1, same runtime session | 1358 |
| Warm 2 | 1804 |
| Warm 3 | 1606 |

Warm maximum 1804 ms is below the 6500 ms acceptance gate. N=1 first/new
session and N=3 warm samples, measured from Chile. The first request is the cold-session
sample; this does not establish cold-container latency after every possible scale-to-zero.
Session IDs exceed 33 characters. Runtime idle timeout is 300 seconds; maximum lifetime 3600.

## Actual Observability export

CloudWatch Transaction Search was enabled in the personal account in us-east-1 with
1% trace-summary indexing. All spans are ingested; 1% indexing is not 1% application sampling.
ADOT instruments the container via opentelemetry-instrument. Unified span destination:
`/aws/bedrock-agentcore/runtimes/donewise_receipts-wbsa177WJQ-DEFAULT`, stream `spans`.

[Sanitized CloudWatch export](agentcore-spans-2026-10-13.json): 50 actual spans across
five traces (four measured requests and Alexa-session prewarm). Each trace contains
one `execute_tool receipts_recap`, one model-specific chat span, MCP discovery/list/call
and the invocation HTTP span. No mutation tool appears. Headers, credentials, user IDs,
prompts and tool payloads are omitted from the export. Source raw export stays ignored.

Trace IDs:
- `32f561ee1af9546c5dcc730640698544`
- `6326e03dd0941bdb453b7696e26366c5`
- `6acda66c78a348e464abd7c453300538`
- `8baea93fec28008052c4230828bfd541`
- `e3f426e0c031acd3a4594815a5fa7267`

## Deployment friction and fallback

`agentcore configure` completed with the container path, supplied roles/ECR and memory
disabled. Starter toolkit 0.3.14 then failed `agentcore launch`: its fixed source bucket
`bedrock-agentcore-codebuild-sources-027018013541-us-east-1` did not match approved project
permissions. It also reports itself deprecated in favor of @aws/agentcore. We used the
planned fallback: locally build ARM64, push to the project ECR repository, deploy with
the control-plane API. CodeBuild did not run and is not claimed as a demonstrated service.

Runtime creation authorizes several dependent actions against `runtime/*` before the
runtime ARN exists. Endpoint/TagResource checks did not propagate the requested Project
tag; workload identity creation and directory/identity tagging required separate rights.
Walter approved the necessary IAM changes. The managed deployment policy plus the
[creation dependency policy](../../deploy/aws-runtime-creation-tagging-policy.json)
document the effective permissions and expiry. Operational get/update/invoke actions
remain scoped to donewise resources. The runtime uses IAM authentication, no JWT/OAuth.

Reproduce invocation with AWS profile donewise, the ARN above, a new 33+ character
session ID and payload `{"prompt":"What did you charge last night and when is the plumber?"}`.
Private environment configuration and receipt registry are intentionally not in Git.

Official setup reference: [AgentCore Observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html).

## Final Alexa acceptance gate — 00:41–00:43 Chile

The coordinated Alexa closure reused runtime version 1 and the original Sonnet demo
run above. Four fresh **AWS CLI** calls used the exact prompt
`What did you charge last night, and when is the plumber?` and a new 47-character
runtime session. First/new session: **3786 ms**; warm: **2816, 2808, 3367 ms**,
including CLI process overhead. Warm maximum remains below **6500 ms: PASS**.
This is a new-session sample, not a guarantee for every container cold start.

[Reference response and measurements](alexa-connected-2026-10-13.json) retain the
full receipt. The returned speech, identical to receipt.spoken on every call, was:

```json
{"speech":"From the saved receipts: plumber is at 10 to 11 AM, read back at 2026-10-12 at 11:01 PM America/Santiago (UTC-0300). One $60 test charge for the deposit, read back at 2026-10-12 at 11 PM America/Santiago (UTC-0300). 0 operations remain unverified or pending. Nothing new was written to your calendar or payments."}
```

[Forty fresh CloudWatch spans](alexa-runtime-spans-2026-10-13.json), filtered to this
new session, cover four traces. Every trace has exactly one `execute_tool receipts_recap`
and no mutation tool. Lambda is connected to the real ARN; three exact SMAPI
launch/question pairs passed, skill execution 1250/1124/1853 ms. See
[Alexa closure](alexa-2026-10-13.md). No new MCP/server/demo changes or full suite
were performed for this acceptance check.
