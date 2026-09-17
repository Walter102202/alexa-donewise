# Integration friction

## Python MCP 2.2.0 transport shape

The brief describes `streams.read_stream` / `streams.write_stream`. The installed distribution
actually yields a two-element tuple. Reproduction: use that attribute access inside
`async with streamable_http_client(url, http_client=httpx2.AsyncClient()) as streams`.
It raises `AttributeError: 'tuple' object has no attribute 'read_stream'`.
Working client: `async with ClientSession(*streams) as session`.
The wire contract and negotiated `2025-11-25` are unchanged. Both server acceptance and simulator
clients must use this shape; ordinary `httpx.AsyncClient` is not the SDK's client type.

## SDK validation and contract fidelity

Function-derived argument schemas use different titles/configuration from the canonical models.
The server publishes the canonical schema via the SDK Tool's parameters field and validates the
full contract before invoking the function. Default SDK validation errors may echo rejected input
values, including a consent capability: the wrapper reports safe errors without those values.
Reproduction/acceptance: `uv run pytest tests/test_server.py -q`.

## Inspector package resolution

`npx --yes @modelcontextprotocol/inspector --help` resolved 1.0.2 here and printed a deprecation
notice recommending v2. The recorded smoke test pins the successfully exercised 1.0.2 CLI;
upgrading Inspector is not represented as validated by this trace.

## Fixture count versus real asynchronous receipts

Two ACK-without-write faults require two read windows in the real harness. Step 3 therefore
can emit PENDING before NOT_OBSERVED, unlike the instant fixture. Consumers must accept every real
structured receipt and deduplicate unchanged polling responses, rather than require seven events.
