# Classic Alexa Skill — Development only

`done wise` is deployed as a **classic Custom Alexa Skill**, provisioned in our own
AWS account. Invocation: `done wise`; locale: `en-US`. This is not an Alexa+ add-on.

Verified **13 October 2026, 00:43 America/Santiago (UTC-03:00)**:

| Resource | Value |
| --- | --- |
| Skill ID | `amzn1.ask.skill.34982f14-6b4a-47c6-9b65-f0649d1c6a0b` |
| Lambda ARN | `arn:aws:lambda:us-east-1:027018013541:function:donewise-alexa` |
| Execution role | `arn:aws:iam::027018013541:role/donewise-alexa` |
| ASK profile / vendor | `default` / `M1DZO2VF4RRLZ8`; no AWS profile linked |
| AWS profile / region | `donewise` / `us-east-1` |
| Runtime | Python 3.12, arm64, 8 s timeout, 512 MB |
| Stage / model | Development enabled; full en-US build `SUCCEEDED` |
| Current mode | `AGENT_RUNTIME_ARN`; `FIXED_SPEECH` removed |
| AgentCore | `arn:aws:bedrock-agentcore:us-east-1:027018013541:runtime/donewise_receipts-wbsa177WJQ`, version 1, READY |
| Demo run | `run_b7d652a00a1e444d9ba6e54b0823107c`, user `demo`, America/Santiago |

**Real receipt acceptance: 3/3 passed.** Three consecutive pairs of `open done wise`
and the exact question resolved to `RequestIntent`. Decoded speech equaled the
reference runtime receipt, including date, time and zone. The demo consists of five
local Sonnet 4.6/Anthropic turns whose completed registry was copied to Lightsail.
The separate remote Strands smoke run `run_5030a0e68ed642dab6c1bd505008600b` is not
substituted for the original demo story. No microphone test was performed.

| Trial | Chile time | Simulation ID (question) | Skill execution |
| --- | --- | --- | --- |
| 1 | 00:42:18 | `e9575aab-8d4d-43e2-96a9-e3db6a64bf6b` | 1250 ms |
| 2 | 00:42:42 | `9333a6de-b248-427a-9a82-1ff55c48e430` | 1124 ms |
| 3 | 00:43:06 | `61270597-bafb-4fd5-8acf-a75f83e161d4` | 1853 ms |

Each trial used `open done wise`, then
`what did you charge last night and when is the plumber`. Each returned:

```json
{"status":"SUCCESSFUL","speech":"From the saved receipts: plumber is at 10 to 11 AM, read back at 2026-10-12 at 11:01 PM America/Santiago (UTC-0300). One $60 test charge for the deposit, read back at 2026-10-12 at 11 PM America/Santiago (UTC-0300). 0 operations remain unverified or pending. Nothing new was written to your calendar or payments."}
```

Evidence: [connected runtime and exact simulations](../../docs/traces/alexa-connected-2026-10-13.json),
[40 fresh runtime spans](../../docs/traces/alexa-runtime-spans-2026-10-13.json),
[deployment trace](../../docs/traces/alexa-2026-10-13.md),
[connected console screenshot](../../docs/traces/alexa-receipt-2026-10-13.jpg).
The [initial fixed-response tests](../../docs/traces/alexa-simulation-2026-10-13.json)
and [three alternate console inputs](../../docs/traces/alexa-test-2026-10-13.json)
remain separate historical evidence.
[Open Test](https://developer.amazon.com/alexa/console/ask/test/amzn1.ask.skill.34982f14-6b4a-47c6-9b65-f0649d1c6a0b/development/en_US/).

## Reproduce configuration

Run in PowerShell 7 from the repository root. Keep `data/` ignored. Raw simulation
envelopes and ASK debug output can contain access tokens: do not publish them.
The creation/fixed-response commands are for fresh infrastructure only. The existing
skill is connected; use **Repeat simulations** and **Runtime wiring** below.

```powershell
$skillId = 'amzn1.ask.skill.34982f14-6b4a-47c6-9b65-f0649d1c6a0b'
$awsArgs = @('--profile', 'donewise', '--region', 'us-east-1', '--no-cli-pager')
$work = 'data/alexa-deploy-2026-10-13'
New-Item -ItemType Directory -Force $work | Out-Null
aws sts get-caller-identity @awsArgs  # Must be account 027018013541.
```

Authentication is complete. On a new machine run `ask configure --profile default`,
sign into the same Developer account and answer **No** to AWS association. ASK
2.30.7 obtains the vendor from the profile; `list-skills-for-vendor` has no
`--vendor-id` option.

Deployment reused `data/alexa-package-7d424229.zip`, SHA-256
`45273b828fddac0bcab0f1b60b4f29b1ab016231e5702ae1bdf992aa6f411bc6`.
The ZIP handler matches `lambda_function.py` byte for byte. To rebuild, run
`uv run python integrations/alexa/package.py` and use its printed ZIP path.

On fresh infrastructure, create role `donewise-alexa` with trust principal
`lambda.amazonaws.com` and attach
`arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole`. Create Lambda:

```powershell
$trust = @{Version='2012-10-17'; Statement=@(@{
  Effect='Allow'; Principal=@{Service='lambda.amazonaws.com'}; Action='sts:AssumeRole'
})}
$trust | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8NoBOM "$work/trust.json"
aws iam create-role --role-name donewise-alexa `
  --assume-role-policy-document "file://$work/trust.json" @awsArgs
aws iam attach-role-policy --role-name donewise-alexa `
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole @awsArgs
aws lambda create-function --function-name donewise-alexa --runtime python3.12 `
  --architectures arm64 --role arn:aws:iam::027018013541:role/donewise-alexa `
  --handler lambda_function.lambda_handler --timeout 8 --memory-size 512 `
  --zip-file fileb://data/alexa-package-7d424229.zip @awsArgs
```

For a **new skill only**, omit the endpoint during creation, then set the scoped
trigger before updating the manifest. Creating with the endpoint first fails
asynchronous trigger validation. Reuse the existing skill for normal updates:

```powershell
$initial = Get-Content integrations/alexa/skill.json -Raw | ConvertFrom-Json
$initial.manifest.apis.custom.PSObject.Properties.Remove('endpoint')
$initial | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8NoBOM "$work/initial-skill.json"
$created = ask smapi create-skill-for-vendor --manifest "file:$work/initial-skill.json" `
  --profile default | ConvertFrom-Json
$skillId = $created.skillId
ask smapi get-skill-status --skill-id $skillId --profile default
# Continue only after manifest.lastUpdateRequest.status == SUCCEEDED.
```

The configuration below is already applied. Add the trigger once on recreation;
inspect an existing statement ID before replacing it:

```powershell
aws lambda add-permission --function-name donewise-alexa `
  --statement-id AlexaSkillDevelopmentCurrent --action lambda:InvokeFunction `
  --principal alexa-appkit.amazon.com --event-source-token $skillId @awsArgs
@{Variables=@{ALEXA_SKILL_ID=$skillId; FIXED_SPEECH='DoneWise is ready for the receipt test.'}} |
  ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8NoBOM "$work/environment.json"
aws lambda update-function-configuration --function-name donewise-alexa `
  --environment "file://$work/environment.json" @awsArgs
ask smapi update-skill-manifest --skill-id $skillId --stage development `
  --manifest file:integrations/alexa/skill.json --profile default
ask smapi set-interaction-model --skill-id $skillId --stage development --locale en-US `
  --interaction-model file:integrations/alexa/en-US.json --profile default
ask smapi get-skill-status --skill-id $skillId --profile default
# set-interaction-model starts the build. Wait for full en-US SUCCEEDED.
ask smapi set-skill-enablement --skill-id $skillId --stage development --profile default
```

Enablement initially returned 403 with an empty response. After visiting Test and
seeing Development enabled, the same command returned 204. The exact initial
cause was not established.

## Repeat simulations

```powershell
function Invoke-AlexaSimulation([string]$text, [string]$mode = 'DEFAULT') {
  $result = ask smapi simulate-skill --skill-id $skillId --stage development `
    --input-content $text --device-locale en-US --session-mode $mode `
    --profile default | ConvertFrom-Json
  for ($poll = 0; $result.status -eq 'IN_PROGRESS' -and $poll -lt 20; $poll++) {
    Start-Sleep -Seconds 1
    $result = ask smapi get-skill-simulation --skill-id $skillId --stage development `
      --simulation-id $result.id --profile default | ConvertFrom-Json
  }
  if ($result.status -ne 'SUCCESSFUL') { throw "Simulation status: $($result.status)" }
  return $result
}
$phrase = 'what did you charge last night and when is the plumber'
1..3 | ForEach-Object {
  $launch = Invoke-AlexaSimulation 'open done wise' 'FORCE_NEW_SESSION'
  # Prewarm using the actual Alexa identity; this also warms AgentCore once connected.
  $warmup = $launch.result.skillExecutionInfo.invocations[0].invocationRequest.body
  $warmup.request = @{
    type='IntentRequest'; requestId="prewarm-$([guid]::NewGuid())"; locale='en-US'
    timestamp=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    intent=@{name='RequestIntent'; confirmationStatus='NONE'
      slots=@{request=@{name='request'; value=$phrase}}}
  }
  $warmup | ConvertTo-Json -Depth 40 | Set-Content -Encoding utf8NoBOM "$work/prewarm.json"
  aws lambda invoke --function-name donewise-alexa --payload "fileb://$work/prewarm.json" `
    "$work/prewarm-response.json" @awsArgs
  $result = Invoke-AlexaSimulation $phrase
  $invocation = $result.result.skillExecutionInfo.invocations[-1]
  [pscustomobject]@{
    Trial=$_; Simulation=$result.id; Status=$result.status
    Intent=$invocation.invocationRequest.body.request.intent.name
    Speech=$invocation.invocationResponse.body.response.outputSpeech.ssml
    SkillMs=$invocation.metrics.skillExecutionTimeInMilliseconds
  }
}
```

The initial fixed-response run prewarmed Lambda before each pair. The final connected
run and commands above warm both Lambda and AgentCore using the same Alexa user
before the question. Compare decoded SSML with `reference_response.receipt.spoken`
in the connected evidence file; a SUCCESSFUL simulation alone is insufficient.

## Runtime wiring — applied

The existing ARM64 Strands/Nova runtime passed its warm gate: first/new session
2.579 s, warm maximum 1.804 s in the original SDK measurements. Final AWS CLI
verification with the comma-containing prompt measured 3.786 s in a new session
and 2.816/2.808/3.367 s warm, including CLI overhead. All are below 6.5 s.
Each new trace contains exactly one `execute_tool receipts_recap`; no write tool
was invoked. See the [AgentCore trace](../../docs/traces/agentcore-2026-10-13.md).
This Alexa closure did not modify the MCP server or the local demo.

```powershell
$runtimeArn = 'arn:aws:bedrock-agentcore:us-east-1:027018013541:runtime/donewise_receipts-wbsa177WJQ'
if ($runtimeArn -notmatch '^arn:aws:bedrock-agentcore:us-east-1:027018013541:runtime/[A-Za-z0-9_-]+$') {
  throw 'Unexpected runtime ARN'
}
@{Version='2012-10-17'; Statement=@(@{
  Effect='Allow'; Action='bedrock-agentcore:InvokeAgentRuntime'; Resource="$runtimeArn*"
})} | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8NoBOM "$work/invoke-runtime.json"
aws iam put-role-policy --role-name donewise-alexa --policy-name InvokeDoneWiseReceipts `
  --policy-document "file://$work/invoke-runtime.json" @awsArgs
# Replace the environment map, removing FIXED_SPEECH.
@{Variables=@{ALEXA_SKILL_ID=$skillId; AGENT_RUNTIME_ARN=$runtimeArn}} |
  ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8NoBOM "$work/environment.json"
aws lambda update-function-configuration --function-name donewise-alexa `
  --environment "file://$work/environment.json" @awsArgs
aws lambda wait function-updated --function-name donewise-alexa @awsArgs
```

The existing handler has `read_timeout=7`, no SDK retries, SHA-256 userId session
IDs (64 hex), skill ID validation, XML escaping and strict equality of `speech`
and `receipt.spoken`. Timeout/error response:
`I'm still checking the receipts. Ask me again in a moment.`
Three connected simulations passed with the reference receipt, including
date/time/zone, without fallback. A forced live timeout was not injected; timeout
and identity boundaries are covered by the existing focused tests.

## Verification and completed IAM cleanup

Three existing boundary tests passed; no full suite or new tests:

```powershell
& data/alexa-venv/Scripts/python.exe -m unittest discover -s integrations/alexa -p test_lambda.py -v
```

With Walter's authorization, `DoneWiseDeployment20261013` was updated in the
personal account at 00:37 Chile. The only addition is `lambda:GetPolicy` and
`lambda:RemovePermission` on the exact donewise-alexa ARN, retaining the expiry.
The inline `DoneWiseRuntimeCreationTagging` already matched the working-tree JSON.

Deleted the failed-ID statement `AlexaSkillDevelopment` and the identical active-ID
duplicate `DoneWiseAlexaSkill`. Live `get-policy` now returns exactly one statement,
`AlexaSkillDevelopmentCurrent`, restricted to the valid skill. No cleanup remains.

Final checks: remote model exactly matches local JSON; deployed ZIP hash is unchanged;
four new runtime CLI responses equal their receipt, 40 spans show recap-only calls,
and three distinct SMAPI questions equal the reference speech. Existing local
tests were reused because handler code did not change. No full suite was run in
this closure. [IAM screenshot](../../docs/traces/iam-alexa-policy-2026-10-13.png).

References: [ASK CLI](https://developer.amazon.com/en-US/docs/alexa/smapi/ask-cli-command-reference.html),
[manifest schema](https://developer.amazon.com/en-US/docs/alexa/smapi/skill-manifest.html),
[Lambda trigger](https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-an-aws-lambda-function.html).
