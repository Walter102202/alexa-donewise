"""Read-only reconciliation shared by startup, polling and operation_get."""

import json

from .contracts import Outcome
from .harness import Context, Harness
from .registry import Registry


class Reconciler:
    def __init__(self, registry: Registry, harness: Harness):
        self.registry, self.harness = registry, harness

    def run_once(self):
        for op in self.registry.operations_with_outcomes(Outcome.UNKNOWN):
            latest = self.registry.latest_receipt(op["operation_id"])
            self.harness.reconcile_operation(
                op,
                json.loads(latest["receipt_json"]),
                Context(user_id="demo", run_id=op["run_id"]),
            )
