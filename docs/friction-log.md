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
No Bedrock, AgentCore or ASK CLI experience is asserted.
