# Evaluation matrix — approved 17 September 2026

Walter approved this ten-scenario matrix for step 3B on 17 September 2026, including the S01 user retry
in revision v2. This compares the **whole harness**
(intent identity, verification and receipt presentation) with direct writes, not the verifier alone.
Zero in a finite sample does not mean never: **cero en muestra finita no es nunca**.

## Shared protocol

One execution per row and variant, independent Fake JSON files and SQLite registry, a fixed logical
clock, and the same initial state and external inputs. DoneWise goes through the official MCP client
over local TCP. The deterministic baseline writes directly, says done only for `acked`, never reads
or retries automatically, and generates a fresh payment key or creation ID for every invocation.
Calendar updates retain the existing event ID and original precondition. Provider faults are armed
identically; the report records actual consumption, including an unconsumed read fault in baseline.

The externally requested retries below are fixed inputs, not branches chosen to make baseline fail.
Each payment authorizes exactly one $60 USD deposit to Ridge Plumbing. Repeated transport delivery
or recovery never authorizes another charge. Each calendar creation authorizes exactly one event.
Seeded calendar rows start at 09:00–10:00 America/Los_Angeles on the day after the logical clock;
the requested move is 10:00–11:00. Setup writes are excluded from timed actions and metric counts.
Both variants retain setup snapshots and the mapping from logical intent to provider objects.

| ID | Initial state and external inputs | Fault and injection point | DoneWise predicate to check | Baseline observation to measure |
| --- | --- | --- | --- | --- |
| S01 lost payment response | Empty payments; approve and charge, then the user retries the same payment. Both variants receive the identical second request. | `drop_response_after_write`, 1 use, immediately before the first charge. | Recover automatically; user retry resends the same `submission_id` and returns the same receipt, with one charge. | User retry invokes another write with a fresh key; report observed charge count, total and text. No automatic baseline retry. |
| S02 acknowledgement without write once | Empty calendar; create once. | `ack_without_write`, 1 use, before create. | One event after at most one automatic replay; verified. | Ack success claim with no event; false confirmation if observed. |
| S03 acknowledgement without write twice | Seed one event; request move once, no external retry. | `ack_without_write`, 2 uses, before move. | Original time remains; `NOT_OBSERVED`, one automatic retry; no success claim. | Original time remains despite ack claim; one fault use remains because baseline made only one write. |
| S04 concurrent edit | Seed one event; request move once. | `concurrent_edit`, 1 use, between precondition capture and write. | Preserve external edit, report conflict, no overwrite or success claim. | Observe `precondition_failed`, preserve external edit; no automatic resubmission. |
| S05 read unavailable | Empty calendar; create once, then request status of that action. | `drop_response_after_write` ×1 and `read_unavailable` ×3 before create. | Initial uncertainty retained; subsequent read reconciliation can verify one event; never a second effect. | Write response lost; baseline status reports lack of verification and does not read; report unconsumed read failures. |
| S06 registry down before intent | Empty calendar; create once. | `registry_down`, 1 use, before intention persistence. Baseline: N/A — protection absent. | No adapter write or success claim; fail closed. | Direct write has no registry dependency; measure effect/claim, outside same-provider-fault subtotal. |
| S07 repeated submission | Empty payments; approve once; deliver the identical approved request twice with the same `submission_id`. | Duplicate external delivery; no provider fault. | Same operation and one charge; no approval re-consumption. | Two calls with fresh keys; count any extra charge against one authorized payment intent. |
| S08 explicit retry of operation | Seed event; request move, then explicitly retry the same logical move. | `ack_without_write` ×2 before the first move. Second DoneWise input includes its `retry_of_operation_id`. | First outcome not observed; retry recovers the same operation to requested time; one applied move. | Two direct calls consume two false acknowledgements; original time remains. Do not give baseline a third input. |
| S09 reused approval | Empty payments; approve and execute one charge; submit a different operation using the spent approval without new consent. | Approval reuse, no provider fault. Baseline approval store: N/A — protection absent. | Reject second operation; exactly one charge. | Direct adapter has no durable approval check; count any second charge as unauthorized, separately from duplicates. |
| S10 replay window expired | Empty payments; approve and charge once, then request status. | Payment idempotency window set to zero and `drop_response_after_write` ×1 before charge; deterministic expiry boundary, not a real-time wait. | Initial `UNKNOWN`; no replay; reconcile by durable identity to one verified charge. | One charge, lost response; no verification or second write. Record that this uses a Fake expiry boundary. |

S03 is an unmet mutation goal, not a completed task simply because uncertainty was reported safely.
S04, S06 and S09 are protection goals: success means preserving the concurrent state or refusing the
unsafe action. They appear separately from mutation completion rates. S06 and S09 test harness-only
protections; no claim of an identical provider failure is made for those rows. Expected outcomes
above are regression assertions, never report data. Unexpected observations remain visible.

## Measurement and artifacts

The evaluator reads persisted Fake state independently at every emitted success claim and at final
quiescence. Its private reads neither consume faults nor provide evidence to either variant. Count
false atomic success claims / all success claims (N/A if none), affected scenarios / executed
scenarios, extra charges and creation events / authorized intents, and unauthorized writes separately.
Completion requires the row's final-state predicate without extra or unauthorized effects.

Timing in JSON is diagnostic wall-clock execution time with a logical clock: the five-second read
window does not elapse. It is not real verification latency, so p50/p95 are omitted from published
Markdown tables. RF-13 latency requires real adapters. Verified/unverified counts remain reported;
no unverified result is assigned a zero duration.
External turns, tool calls and internal write attempts are separate counts. Each scenario has a 30 s
horizon, 100 ms polling and 5 s cleanup allowance. Failed quiescence invalidates the complete run.

The default command `uv run donewise-evals` runs without an LLM, retains run IDs, input and
fault transcripts, snapshots, revision/configuration and a reproduction command in dated JSON/Markdown
under `evals/results/`, and supplies the main README table labelled deterministic sandbox. S01 supplies
observed contrast evidence; it is not labelled same model or Stripe and does not yet drive the live UI.
The `--runner llm` path uses the same provider/model settings across variants, direct writes
plus optional reads in baseline, verified tools in DoneWise, and reviewed annotations for model
claims. `LLM_PROVIDER=none` skips that path without fabricated output. Real LLM execution is deferred.

## Run and interpret

```powershell
uv run donewise-evals
$env:LLM_PROVIDER = 'none'
uv run donewise-evals --runner llm
uv run pytest tests/test_evals.py -q
```

The deterministic command ignores `LLM_PROVIDER`. It starts its own ephemeral local MCP servers;
no existing simulator/server or provider account is needed. On Windows, an open `donewise-server`
or `donewise-sim` executable may block updating the editable package. Leave that session running and
set `$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'donewise-step3-venv'` before the commands to
use an isolated environment. This environment override was used for the recorded step 3B checks.

`evals/results/<UTC-date>-sandbox.json` contains the full evidence, and the matching Markdown contains
the summary. Later runs on that date get a unique run-ID suffix; existing results are never replaced.
Raw working databases are temporary; initial, per-call and final Fake JSON snapshots, complete
receipts, inputs, consumed faults and source SHA-256 hashes (normalized newlines) remain in the JSON.
Dates are deliberately fixed to the approved logical clock; both MCP input validation and the
harness use that injected clock. Diagnostic wall-clock timings vary and exclude the simulated read wait.

Claims use a documented finite vocabulary in deterministic mode: each acknowledged direct write
emits one effect claim; each verified DoneWise receipt emits one effect claim and, for payments,
one additional `charged_once` claim. Each `receipt_id` contributes these claims only once; repeated
returns through retries or `operation_get` remain in the trace but do not inflate the denominator.
Distinct receipts still contribute their own claims. Baseline acknowledgements have no receipt ID
and each acknowledged write is counted.
The repeated payment in S07 is a duplicate of one authorized intent; the second distinct operation
in S09 lacks new consent and is counted as unauthorized instead. In S01 baseline first reports
uncertainty, then reports the acknowledgement from the user-requested retry; RF-46 exports the
observed text and amount. S03 intentionally fails to complete its mutation in both variants.

The LLM runner uses the same adapters and matrix, six model responses per external turn and recorded
variant prompts/tool schemas. Bedrock/Anthropic use the simulator's provider adapters with an injected
evaluation prompt; simulator defaults are unchanged. Baseline can read optionally and its model prose
is captured with independent snapshots. Its false-claim aggregates remain **Pending annotation**.
Review each `llm.utterances[]` entry against its snapshot before annotating atomic claims and marking
the row reviewed; raw unreviewed transcripts are not a reliability score. DoneWise model prose after
tool calls is suppressed in favour of receipt speech, as in the simulator. No live LLM run is included.

Timeouts are explicit failures; unfinished writes prevent publication of a complete aggregate.
The suite runs below 30 seconds locally and therefore does not need a `slow` marker. Run the full
repository checks as well when changing the shared TCP host or input-validation clock.

Acceptance on 17 September 2026: `uv run pytest -q -o faulthandler_timeout=45` passed **124 tests in
32.92 s**; `uv run ruff check .` and `uv run ruff format --check .` passed. The matrix and two LLM
tool-loop doubles are covered in `tests/test_evals.py`; both provider adapters also retain their
default prompts and accept an evaluation prompt in `tests/test_sim.py`. The no-admin HTTP check uses
ASGI directly, avoiding an unnecessary empty SSE stream that stalled one full-suite run during
cleanup. No production transport behavior was changed to resolve that test setup issue.

Revision v2 verification: the same full-suite command passed **124 tests in 33.86 s**; Ruff lint and
format checks passed. The existing matrix test now checks identical S01 retry arguments, two baseline
charges versus one DoneWise charge, and one claim set per receipt across S01/S07 repeated returns.
