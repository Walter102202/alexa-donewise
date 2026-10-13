"""Run in the isolated Strands environment: python -m unittest discover -s ..."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from client import ReceiptAgent


class ReceiptBoundaryTests(unittest.TestCase):
    def client(self):
        client = ReceiptAgent.__new__(ReceiptAgent)
        client.run_id, client.timezone = "run_test", "America/Santiago"
        client.receipts, client.trace, client.pending = [], [], None
        client.recap_complete = False
        return client

    def test_model_prose_cannot_replace_receipt(self):
        client = self.client()
        receipt = {"spoken": "I could not confirm it.", "may_claim_success": False}

        class Model:
            def __call__(self, text):
                client.receipts.append(receipt)
                return "Done! Everything succeeded."

        client.agent = Model()
        self.assertEqual(client.turn("do it"), {"speech": receipt["spoken"], "receipt": receipt})

    def test_recap_scope_and_write_identity_are_backend_owned(self):
        client = self.client()
        client.attempted = set()
        event = SimpleNamespace(
            tool_use={"name": "receipts_recap", "input": {"run_id": "run_other"}}
        )
        client.before_tool(event)
        self.assertEqual(event.tool_use["input"]["run_id"], "run_test")
        event = SimpleNamespace(
            tool_use={
                "name": "payment_charge_verified",
                "input": {
                    "submission_id": "invented",
                    "approval_id": "forged",
                    "amount_minor": 6000,
                },
            }
        )
        client.before_tool(event)
        self.assertNotIn("approval_id", event.tool_use["input"])
        self.assertNotEqual(event.tool_use["input"]["submission_id"], "invented")
        client.before_tool(event)
        self.assertEqual(event.cancel_tool, "Automatic write retry denied")

    def test_pending_poll_is_bounded_and_never_rewrites(self):
        client = self.client()
        pending = {"spoken": "Pending", "operation_id": "op_existing", "outcome": "PENDING"}
        with (
            patch("client.time.monotonic", side_effect=[0, 1, 16]),
            patch("client.time.sleep"),
            patch.object(client, "request", return_value={"structuredContent": pending}) as call,
        ):
            self.assertEqual(
                client.accept("payment_charge_verified", {}, {"structuredContent": pending}),
                pending,
            )
        call.assert_called_once_with("operation_get", {"operation_id": "op_existing"})

    def test_recap_cancels_later_write_in_same_model_response(self):
        client = self.client()
        receipt = {"spoken": "From the saved receipts."}
        event = SimpleNamespace(
            cancel_message=None,
            exception=None,
            duration=0.1,
            result={"structuredContent": receipt},
            tool_use={"name": "receipts_recap", "input": {}},
            invocation_state={"request_state": {}},
        )
        client.after_tool(event)
        queued = SimpleNamespace(tool_use={"name": "calendar_create_verified", "input": {}})
        client.before_tool(queued)
        self.assertEqual(queued.cancel_tool, "Recap completed; further tools denied")
        self.assertEqual(client.receipts, [receipt])


if __name__ == "__main__":
    unittest.main()
