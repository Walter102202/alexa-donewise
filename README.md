# DoneWise

An assistant that verifies external effects before claiming success. The asynchronous harness,
MCP Streamable HTTP server and web simulator run against persisted local Fake adapters.
The five-turn demo uses real MCP calls and receipt-derived speech; no real money is moved.

## Development (Windows / Python 3.12)

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run python scripts/export_schemas.py
```

Import contracts from `donewise_harness.contracts`. The independent MIT package
lives in `core/`; adapter, server and simulator packages live in `adapters/`, `server/`, and `sim/`.
The six story states (seven receipts) are in `sim/fixtures/story-3min.json`.
The twelve JSON schemas are in `docs/schemas/`.

## What is real / what is simulated

Start with the [server guide](server/README.md) and [simulator guide](sim/static/README.md).
Recorded acceptance evidence is in [docs/traces](docs/traces).

Validation, policy, asynchronous verification, MCP and SSE are executable. Live demo receipts
come from the Fake stores, independently read back after writes. The offline fixture is invented
data and is explicitly labelled. Real Google/Stripe adapters and live LLM acceptance remain separate.
No provider credentials are needed for tests.
Configuration names are listed in `.env.example`; secrets must stay out of git.
