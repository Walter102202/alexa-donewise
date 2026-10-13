"""Development-only classic Alexa Skill: speak the AgentCore receipt verbatim."""

import hashlib
import json
import os
from xml.sax.saxutils import escape

import boto3
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.skill_builder import SkillBuilder
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

CHECKING = "I'm still checking the receipts. Ask me again in a moment."


def receipt_speech(user_id, prompt):
    client = boto3.client(
        "bedrock-agentcore",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        config=Config(connect_timeout=0.3, read_timeout=7, retries={"total_max_attempts": 1}),
    )
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
            runtimeSessionId=hashlib.sha256(user_id.encode()).hexdigest(),
            payload=json.dumps({"prompt": prompt}).encode(),
            contentType="application/json",
        )
        body = response["response"]
        try:
            result = json.loads(body.read())
        finally:
            body.close()
        receipt = result.get("receipt")
        if not isinstance(receipt, dict) or not isinstance(receipt.get("spoken"), str):
            raise ValueError("Missing receipt speech")
        if result.get("speech") != receipt["spoken"]:
            raise ValueError("Speech differs from receipt")
        return receipt["spoken"]
    finally:
        client.close()


class RequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return True

    def handle(self, handler_input):
        envelope = handler_input.request_envelope
        request = envelope.request
        if request.object_type == "SessionEndedRequest":
            return handler_input.response_builder.response
        intent = getattr(request, "intent", None)
        name = intent.name if intent else None
        if name in {"AMAZON.StopIntent", "AMAZON.CancelIntent"}:
            return (
                handler_input.response_builder.speak("Goodbye.")
                .set_should_end_session(True)
                .response
            )
        if os.getenv("FIXED_SPEECH"):
            speech = os.environ["FIXED_SPEECH"]
        elif request.object_type == "LaunchRequest" or name not in {"RequestIntent", "AskIntent"}:
            speech = "Ask what I charged last night, and when the plumber is scheduled."
        else:
            slots = intent.slots or {}
            slot = slots.get("request") or slots.get("query")
            prompt = slot.value if slot and slot.value else "What did you do last night?"
            user_id = envelope.context.system.user.user_id
            try:
                speech = receipt_speech(user_id, prompt)
            except (BotoCoreError, ClientError, ValueError, KeyError):
                speech = CHECKING
        return (
            handler_input.response_builder.speak(escape(speech))
            .set_should_end_session(False)
            .response
        )


builder = SkillBuilder()
builder.add_request_handler(RequestHandler())
_handler = builder.lambda_handler()


def lambda_handler(event, context):
    expected = os.environ.get("ALEXA_SKILL_ID")
    actual = event.get("context", {}).get("System", {}).get("application", {}).get("applicationId")
    if not expected or actual != expected:
        raise ValueError("Unexpected Alexa application")
    return _handler(event, context)
