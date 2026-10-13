import io
import json
import os
import unittest
from unittest.mock import Mock, patch

import lambda_function as skill
from botocore.exceptions import ReadTimeoutError


def event():
    return {
        "version": "1.0",
        "session": {
            "new": False,
            "sessionId": "s",
            "attributes": {},
            "application": {"applicationId": "skill-test"},
            "user": {"userId": "user-test"},
        },
        "context": {
            "System": {
                "application": {"applicationId": "skill-test"},
                "user": {"userId": "user-test"},
                "device": {"deviceId": "test", "supportedInterfaces": {}},
                "apiEndpoint": "https://api.amazonalexa.com",
                "apiAccessToken": "unused",
            }
        },
        "request": {
            "type": "IntentRequest",
            "requestId": "r",
            "timestamp": "2026-10-13T00:00:00Z",
            "locale": "en-US",
            "intent": {
                "name": "RequestIntent",
                "confirmationStatus": "NONE",
                "slots": {"request": {"name": "request", "value": "what did you do last night"}},
            },
        },
    }


class LambdaTests(unittest.TestCase):
    @patch.dict(os.environ, {"ALEXA_SKILL_ID": "skill-test", "AGENT_RUNTIME_ARN": "runtime-test"})
    def test_exact_receipt_and_session_identity(self):
        payload = {"speech": "Saved A & B", "receipt": {"spoken": "Saved A & B"}}
        client = Mock()
        client.invoke_agent_runtime.return_value = {
            "response": io.BytesIO(json.dumps(payload).encode())
        }
        with patch.object(skill.boto3, "client", return_value=client) as factory:
            response = skill.lambda_handler(event(), None)
        self.assertEqual(
            response["response"]["outputSpeech"]["ssml"], "<speak>Saved A &amp; B</speak>"
        )
        args = client.invoke_agent_runtime.call_args.kwargs
        self.assertEqual(len(args["runtimeSessionId"]), 64)
        self.assertNotIn("user-test", json.dumps(args, default=str))
        self.assertEqual(factory.call_args.kwargs["config"].read_timeout, 7)
        self.assertEqual(factory.call_args.kwargs["config"].retries["total_max_attempts"], 1)

    @patch.dict(os.environ, {"ALEXA_SKILL_ID": "skill-test"})
    def test_timeout_and_mismatched_application(self):
        with patch.object(
            skill, "receipt_speech", side_effect=ReadTimeoutError(endpoint_url="test")
        ):
            response = skill.lambda_handler(event(), None)
        self.assertIn(skill.CHECKING, response["response"]["outputSpeech"]["ssml"])
        bad = event()
        bad["context"]["System"]["application"]["applicationId"] = "other"
        with self.assertRaises(ValueError):
            skill.lambda_handler(bad, None)

    @patch.dict(os.environ, {"AGENT_RUNTIME_ARN": "runtime-test"})
    def test_mismatched_speech_is_rejected(self):
        client = Mock()
        client.invoke_agent_runtime.return_value = {
            "response": io.BytesIO(
                json.dumps({"speech": "Done!", "receipt": {"spoken": "Not verified"}}).encode()
            )
        }
        with (
            patch.object(skill.boto3, "client", return_value=client),
            self.assertRaises(ValueError),
        ):
            skill.receipt_speech("user-test", "recap")


if __name__ == "__main__":
    unittest.main()
