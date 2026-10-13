# Bedrock smoke — 12 October 2026 (America/Santiago)

Account verified with STS: personal DoneWise account `027018013541`, IAM user `donewise`.
Region `us-east-1`. Command:

```powershell
uv run python scripts/bedrock_smoke.py --output docs/traces/bedrock-smoke-2026-10-12.json
```

The [JSON evidence](bedrock-smoke-2026-10-12.json) records UTC time, request IDs,
tokens, parameters and latency. Text smoke followed by a tool-selection smoke with
the six canonical MCP tool schemas; no tool executed and no external writes.

| Model | Text | Tools | Text / tool latency |
| --- | --- | --- | --- |
| GPT-5.6 Terra | AccessDeniedException | Skipped after denial | 803 ms / N/A |
| Nova Pro | OK | receipts_recap | 453 / 1100 ms |
| Sonnet 4.6 | OK | receipts_recap | 720 / 1062 ms |
| gpt-oss-120b | OK | receipts_recap | 485 / 762 ms |

The earlier account-verification block is gone for Nova and Sonnet. Terra returns
`openai.gpt-5.6-terra is not available for this account` and directs the account
owner to AWS Sales. Nova is the planned development fallback, gpt-oss the second
OpenAI choice. Private `.env` now selects Nova for Bedrock; the local demo retains
`LLM_PROVIDER=anthropic` and `claude-sonnet-4-6`.

An initial unvalidated GPT-5.6 reasoning setting was removed after Walter explicitly
excluded frontier GPT models. The smoke script now defaults only to the three
available models and never retries Terra by default. The first recorded probe remains
in the JSON as historical access evidence. No reasoning-off or Terra evaluation is claimed;
the successful smoke and evaluation requests use provider defaults with maxTokens=1200.

`aws budgets describe-budgets --account-id 027018013541 --profile donewise --region us-east-1`
returned AccessDenied for `budgets:ViewBudget`. Walter instructed us to retain the
existing alerts. No budget or alert was changed; the 100% action's coverage is
unverified. This smoke does not establish a hard spending cap.
