# DoneWise

An assistant that verifies external effects before claiming success. The asynchronous harness,
MCP Streamable HTTP server and web simulator run against persisted local Fake adapters.
The five-turn demo uses real MCP calls and receipt-derived speech; no real money is moved.

## Deterministic sandbox · Fake adapters · no model

Run `run_c897c7a7142544a2a836f6e2481551ae` · matrix `2026-09-17-v1`.

| Metric | Baseline | DoneWise |
| --- | --- | --- |
| False success claims / success claims | 4/9 | 0/13 |
| Scenarios with false claims / executed | 3/10 | 0/10 |
| Extra charges / authorized payment intents | 1/4 | 0/4 |
| Extra events / authorized creation intents | 0/3 | 0/3 |
| Completed mutations / mutation scenarios | 3/7 | 6/7 |
| Completed protections / protection scenarios | 1/3 | 3/3 |
| Verified mutations / mutation scenarios | 0/7 | 6/7 |
| Unauthorized writes | 1 | 0 |
| External turns | 15 | 15 |
| Tool calls (excluding setup) | 15 | 15 |
| Adapter write attempts | 13 | 15 |
| Timeouts | 0 | 0 |
| Verification p50 / p95 ms, verified mutations only | N/A | 47.0 / 125.0 (n=6) |

Unverified mutations remain in the verified/total denominator; their latency is not zero.
Harness-only protection rows are not an identical-provider-fault comparison.
**Cero en muestra finita no es nunca.** This compares the whole harness, not just verification.

Reproduce: `uv run donewise-evals --runner deterministic --output-dir "evals/results"`

[Full evidence and S01 contrast](evals/results/2026-09-17-sandbox.json) · [Approved matrix and limits](evals/README.md).

No live LLM, Google or Stripe run is claimed. Voice controls are implemented; human microphone/TTS rehearsal remains pending.

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
