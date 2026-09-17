# Docker and packaging acceptance — 17 September 2026

Local sandbox only. No provider credentials, model calls or real money. Source UI: `sim/static`,
served by the actual simulator container. The starting checkout was clean. Packaging changes do
not alter functional Python/JS code.

## Startup

Docker Desktop 4.43.2, Linux engine 28.3.2; Windows host. Built both targets from the single
Dockerfile with uv 0.8.17 and Python 3.12.13. Default host ports 8765 and 8080 were already held
by existing local processes, which were left running. Reproduction in PowerShell:

```powershell
$env:DONEWISE_SERVER_PORT = '18765'
$env:DONEWISE_SIM_PORT = '18080'
docker compose up --build -d
docker compose ps
```

Observed: `donewise-server` healthy, host 18765 → container 8765; `donewise-sim` running,
host 18080 → container 8080. A real browser at `http://localhost:18080` created a live MCP session
and displayed `sandbox` / `scripted session`. Containers read `.env.example`, with no model or
provider keys. Server state is bound to `./data`. The sim target runs Uvicorn on 0.0.0.0 inside
its container; the server uses its Compose DNS name for binding and MCP host validation.

## Browser and independent state

Complete run: `run_16fe6822b93a45b1a66fbd4eba580325`.

| Continue | Observed |
| --- | --- |
| 1 | Calendar VERIFIED at 9–10; $60 NEEDS_APPROVAL, zero charges |
| 2 | Lost-response fault; PENDING then VERIFIED, one charge |
| 3 | Two false acknowledgements; PENDING then NOT_OBSERVED; latest read still 9–10 |
| 4 | Explicit retry verified 10–11 |
| 5 | Two-result stored recap, no fresh reads or writes claimed |

Independent read of `data/calendar.json` found one event for this run, `evt_61e83708221343faac8711feec147b2e`,
start `2026-09-17T17:00:00+00:00`, end `18:00:00+00:00` (10–11 America/Los_Angeles).
`data/payments.json` contained one payment for this run, `pi_24f4c864db1842939c209d83fbbc9619`,
6000 USD minor units, succeeded. Reproduce the independent count after your run:

```powershell
$run = 'run_16fe6822b93a45b1a66fbd4eba580325' # replace with your UI run ID
$events = (Get-Content data/calendar.json -Raw | ConvertFrom-Json).events
$payments = (Get-Content data/payments.json -Raw | ConvertFrom-Json).intents
$events.PSObject.Properties.Value | Where-Object run_id -EQ $run
$payments.PSObject.Properties.Value | Where-Object run_id -EQ $run
```

The three committed screenshots show a second fresh run, `run_dfddc3f90cc74431abea6d00fcfa1b09`:
approval (zero charges), recovered payment (one charge), and NOT_OBSERVED. They are actual viewport
captures, without fabricated results or image editing. Voice was off. The aggregate consumed-fault
counter reaches three: one dropped payment response plus two calendar acknowledgements.

## Verification scope

Windows Python 3.12.10, uv 0.8.17, current lockfile:

```sh
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest -m "not connected"
uv run donewise-evals --runner deterministic --output-dir data/step5-evals
```

All checks passed; **163 passed, 1 deselected** (52.82 s). A temporary virtual environment was
used through `UV_PROJECT_ENVIRONMENT`, since existing server processes held the checkout's launcher
open. Evaluation `run_66195b4727a94a7c9f90e1008324a3fd` reproduced the published counts.

Linux Python 3.12.13 in an ephemeral container: uv sync, Ruff check/format and the same pytest
selection passed: **163 passed, 1 deselected** (40.30 s). The verification container copied
`tests/`, `scripts/` and `docs/schemas/` from the checkout; these are not production image inputs.
An earlier incomplete test-container setup omitted schemas/scripts and caused two file-not-found
failures; including the required test inputs resolved both without application changes.

The minimal runtime image has no Git executable. Linux eval verification installed Git only in
an ephemeral container and mounted the checkout read-only for revision metadata. Evaluation
`run_f8ac894d56ce438790e7638d8de6e3e1` also reproduced the table. GitHub Ubuntu runners provide Git;
the actual Windows/Ubuntu workflow has not run remotely because no push was performed.

Both test platforms emitted the existing Starlette/AnyIO BlockingPortal deprecation warning.
No new tests were needed: the changes are packaging/documentation, and existing transport/SSE,
schema and deterministic suites provide useful coverage. No connected test or human audio test
was executed. Linux-container evidence is not labelled as a hosted Ubuntu Actions run.

`git add --renormalize .` found tracked index contents already normalized to LF. The isolated
normalization commit adds `.gitattributes`; working-tree CRLF text was also converted to LF without
semantic changes. No application source diff was introduced.
