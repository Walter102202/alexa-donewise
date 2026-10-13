# AgentCore deployment gate

Entrypoint is `app.py`; the SDK exposes `/invocations` and `/ping`. Only the
`prompt` is accepted from the payload. User and previous run come from trusted
environment configuration, never from caller-controlled fields.

Required environment: `MCP_URL` (HTTPS), `MCP_BEARER_TOKEN`, `DONEWISE_RUN_ID`,
`DONEWISE_USER_ID=demo`, `AWS_REGION=us-east-1`,
`BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0`, and `USER_TIMEZONE`.
Do not pass `DEMO_ADMIN_TOKEN`, provider credentials or `AWS_PROFILE` to the runtime.
Use its execution role. This entrypoint does not offer the local operator's approval method.

Build ARM64 from `agents/strands_client` as context:

```powershell
docker buildx build --platform linux/arm64 -f agents/strands_client/agentcore/Dockerfile agents/strands_client -t donewise-strands:latest
```

The deployment role needs AgentCore Runtime/endpoint creation, ECR image publication
and `iam:PassRole` for the dedicated runtime role. The runtime role needs
`bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on the US Nova Pro
inference profile and its routed foundation models, plus AgentCore's logging permissions.
Its trust principal is `bedrock-agentcore.amazonaws.com`, scoped to this account.
Keep bearer values in private configuration; never put them in this directory.

Use the AgentCore starter toolkit's `agentcore configure`/`agentcore launch` with
the **container** deployment path and CodeBuild ARM64, or push the local ARM64 image
after verifying it. Current toolkits default to direct-code ZIP deployment, so do
not assume the default builds the planned container.

Acceptance must record the runtime ARN, a session ID of at least 33 characters,
CloudWatch/Observability trace, exact receipt speech, one recap tool call and no
external writes. Measure cold and warm invocation separately. This implementation
already stops after recap without a second inference. The 6.5-second warm gate
and Alexa's timeout must be measured in AWS; local timing is not a cloud result.

Status: deployed and verified in AWS. Runtime
`arn:aws:bedrock-agentcore:us-east-1:027018013541:runtime/donewise_receipts-wbsa177WJQ`,
version 1, endpoint DEFAULT. [Full evidence and exported spans](../../../docs/traces/agentcore-2026-10-13.md).
First new-session request: 2579 ms; three warm requests: 1358/1804/1606 ms.
The 6500 ms warm gate passed. Transaction Search is enabled, with 1% summary indexing.
The ARM64 image includes ADOT and launches through `opentelemetry-instrument`.

The configured demo run is `run_b7d652a00a1e444d9ba6e54b0823107c`: five local
Sonnet 4.6/Anthropic simulator turns whose consistent SQLite backup was transferred
to Lightsail. The later remote Strands acceptance run is separate and is not silently
substituted. Before recording a new story, transfer its consistent completed registry
and update DONEWISE_RUN_ID explicitly. Keep the original evidence for provenance.

CodeBuild launch was attempted and blocked by the toolkit's fixed source-bucket name.
The tested deployment uses the approved local-build/ECR fallback. Do not claim CodeBuild
as a successfully demonstrated service. The image contains only the client and SDK
entrypoint; server/provider credentials remain on Lightsail.

Invoke the existing runtime from PowerShell (profile `donewise`):

```powershell
@{prompt='What did you charge last night and when is the plumber?'} | ConvertTo-Json | Set-Content -Encoding utf8NoBOM data/agentcore-prompt.json
$runtimeSession = 'donewise-' + [guid]::NewGuid().ToString('N')
aws bedrock-agentcore invoke-agent-runtime --profile donewise --region us-east-1 --agent-runtime-arn arn:aws:bedrock-agentcore:us-east-1:027018013541:runtime/donewise_receipts-wbsa177WJQ --runtime-session-id $runtimeSession --content-type application/json --payload fileb://data/agentcore-prompt.json data/agentcore-response.json
```

