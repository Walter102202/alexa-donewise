"""Receipt-authoritative agent; consent and polling never depend on the model."""

import json
import re
from uuid import uuid4

from .session import ToolCallError

STRONG_YES = re.compile(
    r"\b(yes|yep|yup|yeah go ahead|go ahead|do it|charge it|approve|confirm|please do)\b"
)
WEAK_YES = re.compile(r"^(ok|okay|sure|yeah|yep|yup|fine|alright|sounds good)$")
NO = re.compile(r"\b(no|nope|don't|do not|cancel|stop|never mind|nevermind|not now|forget it)\b")
CHANGE = re.compile(r"\d|\$|\bbut\b|\binstead\b|\bfifty\b|\bforty\b|\bhundred\b")
DECLINED = "OK, I won't charge it. Nothing was charged."


def normalize(text):
    return " ".join(re.sub(r"[^\w\s$']", " ", text.lower()).split())


def classify_consent(text, pending):
    """Deterministic yes/no against the pending approval; anything else goes to the model."""
    if not pending:
        return None
    words = normalize(text)
    if NO.search(words):
        return "no"
    if CHANGE.search(words):
        return None
    if STRONG_YES.search(words):
        return "yes"
    if pending.get("turns_since", 0) == 0 and WEAK_YES.match(words):
        return "yes"
    return None


async def turn(session, text):
    await session.emit("user", {"text": text})
    session.messages.append({"role": "user", "content": [{"type": "text", "text": text}]})
    consent = classify_consent(text, session.pending_approval)
    if consent == "no":
        session.pending_approval = None
        session.messages.append(
            {"role": "assistant", "content": [{"type": "text", "text": DECLINED}]}
        )
        await session.emit("assistant", {"text": DECLINED, "source": "session"})
        return
    if consent == "yes":
        if session.ui_mode == "scripted" and session.step == 1:
            await session.arm("drop_response_after_write")
        result = await session.approve()
        if session.step == 1 and session.script_args:
            session.step = 2
        # No grant, capability or model invocation in the deterministic approval path.
        session.messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": json.dumps({"structuredContent": result})}],
            }
        )
        await session.speak_receipts()
        return
    if session.pending_approval:
        session.pending_approval["turns_since"] += 1
    attempted = set()
    called = False
    for _ in range(6):
        await session.emit("status", {"status": "thinking"})
        reply = await session.llm.reply(session.messages, session.tools)
        if not reply.tool_calls:
            # A turn with a receipt speaks only the receipt. Without one (rejected or failed
            # calls) the model's explanation or question is the only thing the user can hear.
            if not called or not session.turn_spoken:
                await session.emit("assistant", {"text": reply.text, "source": "model"})
                session.messages.append(
                    {"role": "assistant", "content": [{"type": "text", "text": reply.text}]}
                )
            break
        called = True
        # Model prose accompanying a tool call is deliberately neither spoken nor displayed.
        session.messages.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                    for call in reply.tool_calls
                ],
            }
        )
        outputs = []
        for call in reply.tool_calls:
            args = dict(call.arguments)
            try:
                if call.name.endswith("_verified"):
                    identity = (
                        call.name,
                        json.dumps(
                            {
                                k: v
                                for k, v in args.items()
                                if k not in ("submission_id", "approval_id")
                            },
                            sort_keys=True,
                        ),
                    )
                    if identity in attempted:
                        raise RuntimeError("Automatic write retry denied")
                    attempted.add(identity)
                    # Backend-owned ids: a fresh submission per call (session.approve resends
                    # these same arguments, so the id survives the consent round trip), and
                    # never a model-supplied approval.
                    args.pop("approval_id", None)
                    args["submission_id"] = str(uuid4())
                result = await session.execute(call.name, args)
                payload, error = {"structuredContent": result}, False
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, ToolCallError)
                    else ("Tool failed or denied; do not retry writes")
                )
                payload, error = {"error": message}, True
                await session.emit("error", {"message": "Tool failed or denied: " + call.name})
            outputs.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(payload),
                    "is_error": error,
                }
            )
        session.messages.append({"role": "user", "content": outputs})
    await session.speak_receipts()
