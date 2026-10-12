# donewise-harness

An MIT-licensed Python library for verified calendar and test-payment execution. The implemented
flow is intention, approval when required, idempotent submission, adapter write, read-back,
verdict and a typed receipt. SQLite stores identities, approvals, attempts and receipts; bounded
replay and reconciliation handle uncertain outcomes. Only a VERIFIED receipt permits a success
claim, and spoken summaries are rendered from receipt data.

The package is separate from DoneWise's MCP server and web simulator. It depends on Pydantic v2
and `tzdata`; it does not require MCP, FastAPI, a model SDK or provider credentials. Applications
supply adapters through [ports.Adapter](donewise_harness/ports.py). The Google Calendar, Stripe
test and persisted Fake adapters live in the parent application's [adapters](../adapters/) folder
and are not included in this package.

## Install independently

Requires Python 3.12 or later; the recorded project checks use Python 3.12. In an activated Python
virtual environment, install just the core package from this repository:

```sh
git clone https://github.com/Walter102202/alexa-donewise.git
python -m pip install ./alexa-donewise/core
```

Source installation is available under the [MIT license](LICENSE). The package has not been
published to PyPI. Installing `core/` does not install the parent application's dependencies.

## Run without MCP or a model

Save the following as `example.py` outside the checkout and run `python example.py` in that
environment. This uses an in-memory calendar adapter and a temporary SQLite registry. It makes
no network requests and moves no money. The adapter deliberately supports calendar creation only.

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from donewise_harness.contracts import Action, CalendarCreateInput, EvidenceSource, Outcome
from donewise_harness.faults import FaultBoard
from donewise_harness.harness import Context, Harness
from donewise_harness.ports import ReadResult, WriteResult
from donewise_harness.registry import Registry


class TinyCalendar:
    source = EvidenceSource.FAKE_CALENDAR

    def __init__(self):
        self.events = {}

    def write(self, req):
        if req.action != Action.CALENDAR_CREATE:
            return WriteResult(status="error", provider_ref=None, version=None, error="Create only")
        key = req.target.event_id
        if key in self.events:
            return WriteResult(status="already_exists", provider_ref=key, version="1", error=None)
        self.events[key] = req.target.model_copy(deep=True)
        return WriteResult(status="acked", provider_ref=key, version="1", error=None)

    def read(self, req):
        key = req.provider_ref or req.target.event_id
        observed = self.events.get(key)
        return ReadResult(
            found=observed is not None,
            observed=observed,
            version="1" if observed else None,
            observed_at=datetime.now(UTC),
            source=self.source,
        )

    def replay_is_safe(self, req):
        return False


with TemporaryDirectory() as directory:
    calendar = TinyCalendar()
    harness = Harness(
        registry=Registry(Path(directory) / "registry.sqlite"),
        calendar=calendar,
        payments=calendar,  # This example adapter refuses payment writes.
        faults=FaultBoard(),
    )
    start = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    request = CalendarCreateInput(
        submission_id="example-booking",
        title="Plumber visit",
        start=start,
        end=start + timedelta(hours=1),
        timezone="UTC",
    )
    context = Context(user_id="example", run_id="run_example")
    receipt = harness.calendar_create(request, context)
    repeated = harness.calendar_create(request, context)

    assert receipt.outcome == Outcome.VERIFIED
    assert receipt.may_claim_success
    assert repeated.operation_id == receipt.operation_id
    assert len(calendar.events) == 1  # Inspect the adapter's state independently.
    assert calendar.events[receipt.event_id].start == start
    print(receipt.outcome.value, len(calendar.events), "event", receipt.evidence.source.value)
```

Expected output: `VERIFIED 1 event fake_calendar`. Reusing the same submission identity resumes
the stored operation. It does not imply a fresh provider read. Keep that identity stable for
retries of one request; a separate intended action needs a new submission identity.

## Integration boundaries and evidence

- Use one server process per data directory and persistent storage for a lasting application.
  The example's temporary registry and in-memory calendar are discarded when it exits.
- `pending_after` defaults to `None` for synchronous execution. The parent server also exercises
  background verification, operation polling and restart reconciliation; callers enabling workers
  must manage their lifecycle with `wait_for_workers` and recovery with `recover_pending`.
- Payments require trusted approval bound to the operation and payment details. Keep the consent
  capability outside the model; the example configures no payment approval path.
- An adapter must provide scoped read-back, correct evidence provenance and a justified
  `replay_is_safe` decision. This illustrative adapter does not establish external-provider behavior.
  A new provider evidence source also requires an explicit contract change.
- Unknown outcomes remain uncertain. Typed receipt validation alone does not prove an external
  effect; the harness relies on the adapter's observations.

The parent repository contains [contract tests](../tests/test_contracts.py),
[harness recovery and approval tests](../tests/test_harness.py), and
[restart/reconciliation tests](../tests/test_reconcile.py). Recorded evidence distinguishes
[deterministic Fake experiments](../evals/README.md) from the
[Google Calendar and Stripe test smoke check](../docs/stripe-sandbox.md).
These are bounded observations, not a production reliability guarantee.
