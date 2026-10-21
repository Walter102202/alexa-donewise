"""Receipt-authoritative agent; consent and polling never depend on the model."""

import json
import re
import sys
from uuid import uuid4

from .session import ToolCallError

# "yes" needs every word to belong to this vocabulary, so questions ("should I do it"),
# negations ("I didn't say yes") and compound requests ("yes, and move it to ten") reach the
# model instead of charging. A decline wins over everything.
YES_WORDS = frozenset(
    "yes yeah yep yup sure ok okay please go ahead do it charge approve confirm confirmed "
    "that thanks thank you fine alright sounds good right absolutely course of".split()
)
STRONG_YES = re.compile(
    r"\b(yes|yep|yup|go ahead|do it|charge it|approve|confirm|confirmed|absolutely|of course)\b"
)
NO = re.compile(r"\b(no|nope|don't|do not|cancel|stop|never mind|nevermind|not now|forget it)\b")
DECLINED = "OK, I won't charge it."


def normalize(text):
    text = text.replace("\u2019", "'").lower()
    return " ".join(re.sub(r"[^\w\s']", " ", text).split())


def classify_consent(text, pending):
    """Deterministic yes/no against the pending approval; anything else goes to the model."""
    if not pending:
        return None
    words = normalize(text)
    if NO.search(words):
        return "no"
    tokens = words.split()
    if not tokens or any(token not in YES_WORDS for token in tokens):
        return None
    if STRONG_YES.search(words):
        return "yes"
    # Weak words alone ("ok", "sure") count only as the first answer to the question.
    return "yes" if pending.get("turns_since", 0) == 0 else None


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
                print(
                    f"tool error {call.name}: {message} :: args={json.dumps(args)[:600]}",
                    file=sys.stderr,
                    flush=True,
                )
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
