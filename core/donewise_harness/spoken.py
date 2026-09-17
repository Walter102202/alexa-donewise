"""Deterministic English presentation; never infer success from an acknowledgement."""

from datetime import datetime
from decimal import Decimal

from .contracts import (
    Action,
    ApprovalGrantResult,
    CalendarTarget,
    Outcome,
    PaymentTarget,
    ReasonCode,
    RecapResult,
    Receipt,
    ToolResult,
    timezone_for,
)

TEMPLATES = {
    "create": "It's on your calendar: {title}, {day} {span}.",
    "move": "{title} is now at {span}. I read it back from your calendar.",
    "charge": (
        "Done: a {amount} test charge is recorded for {payee}'s {concept}, charged once. "
        "Confirmation {payment_intent_id}."
    ),
    "historical": "I checked at {observed_at}; the calendar shows {span}.",
    "pending": "I'm on it. I'll confirm in a moment.",
    "pending_no_follow_up": "Ask me 'did it go through?' if you don't hear back.",
    "approval": "For the {concept}: a {amount} test charge for {payee}. Should I charge it?",
    "input": "Which one, the plumber or the dentist?",
    "not_observed": (
        "I couldn't confirm the change. I tried {attempts_word}; "
        "the latest calendar check still shows {observed_start}."
    ),
    "not_observed_absent": (
        "I couldn't confirm it. I tried {attempts_word}; the latest calendar check doesn't show it."
    ),
    "unknown": "I couldn't check the result yet. Nothing is confirmed. I'll keep checking.",
    "no_approval": "I won't charge anything without your OK.",
    "approval_mismatch": "That's a different amount. I need a new OK for {amount}.",
    "conflict": (
        "Your calendar changed since I last looked. It now shows {observed}. "
        "Still move it to {target}?"
    ),
    "recap": "From the receipts in this conversation: {items} Nothing new was written.",
    "recovered": " You don't need to try again.",
    "recap_item": "{summary}, read back at {observed_at}.",
    "grant": "Your approval is recorded. Nothing has been charged by this approval.",
    "rejected": "I couldn't carry out this request.",
    "payment_not_observed": "I couldn't confirm the charge from the latest payment check.",
}


def clock_time(value: datetime, zone: str, *, suffix: bool = True) -> str:
    local = value.astimezone(timezone_for(zone))
    minute = f":{local.minute:02}" if local.minute else ""
    return f"{local.hour % 12 or 12}{minute}" + (
        f" {'AM' if local.hour < 12 else 'PM'}" if suffix else ""
    )


def span(target: CalendarTarget) -> str:
    zone = timezone_for(target.timezone)
    start, end = target.start.astimezone(zone), target.end.astimezone(zone)
    if start.date() != end.date():
        return (
            f"{start:%Y-%m-%d} {clock_time(start, target.timezone)} to "
            f"{end:%Y-%m-%d} {clock_time(end, target.timezone)}"
        )
    same_period = (start.hour < 12) == (end.hour < 12)
    return (
        f"{clock_time(start, target.timezone, suffix=not same_period)} to "
        f"{clock_time(end, target.timezone)}"
    )


def amount(target: PaymentTarget) -> str:
    if target.currency != "USD":
        return f"{target.amount_minor} minor units of {target.currency}"
    value = Decimal(target.amount_minor) / 100
    return f"${value:.0f}" if value == value.to_integral_value() else f"${value:.2f}"


def render_spoken(receipt: ToolResult, *, historical: bool = False, follow_up: bool = True) -> str:
    """Render only receipt data. Historical mode is explicit; no wall-clock staleness guess."""
    if isinstance(receipt, RecapResult):
        items = " ".join(
            TEMPLATES["recap_item"].format(
                summary=item.summary.rstrip("."),
                observed_at=clock_time(item.observed_at, receipt.timezone),
            )
            for item in receipt.items
        )
        return TEMPLATES["recap"].format(items=items)
    if isinstance(receipt, ApprovalGrantResult):
        return TEMPLATES["grant"]
    if not isinstance(receipt, Receipt):
        raise ValueError("Unsupported tool result")
    target = receipt.expected
    if receipt.reason_code == ReasonCode.VERSION_CONFLICT:
        if not isinstance(target, CalendarTarget) or not isinstance(
            receipt.observed, CalendarTarget
        ):
            raise ValueError("Version conflict speech requires a calendar observation")
        return TEMPLATES["conflict"].format(observed=span(receipt.observed), target=span(target))
    if historical:
        if receipt.outcome != Outcome.VERIFIED or not isinstance(target, CalendarTarget):
            raise ValueError("Historical speech requires a verified calendar receipt")
        return TEMPLATES["historical"].format(
            observed_at=clock_time(receipt.observed_at, target.timezone),
            span=span(target),
        )
    if receipt.outcome == Outcome.VERIFIED:
        if isinstance(target, PaymentTarget):
            confirmation = getattr(receipt, "payment_intent_id", None)
            if confirmation is None:
                raise ValueError("Verified charge speech requires its PaymentIntent id")
            text = TEMPLATES["charge"].format(
                amount=amount(target),
                payee=target.payee,
                concept=target.concept,
                payment_intent_id=confirmation,
            )
            if receipt.reason_code == ReasonCode.WRITE_RESPONSE_LOST_RECOVERED:
                text += TEMPLATES["recovered"]
            return text
        if receipt.action == Action.CALENDAR_RESCHEDULE:
            return TEMPLATES["move"].format(
                title=receipt.spoken_subject or target.title,
                span=span(target),
            )
        zone = timezone_for(target.timezone)
        days = (
            target.start.astimezone(zone).date() - receipt.observed_at.astimezone(zone).date()
        ).days
        day = {0: "today", 1: "tomorrow"}.get(
            days, target.start.astimezone(zone).strftime("%Y-%m-%d")
        )
        return TEMPLATES["create"].format(title=target.title, day=day, span=span(target))
    if receipt.outcome == Outcome.NEEDS_APPROVAL:
        if not isinstance(target, PaymentTarget):
            raise ValueError("Approval speech requires a payment")
        return TEMPLATES["approval"].format(
            amount=amount(target),
            payee=target.payee,
            concept=target.concept,
        )
    if receipt.outcome == Outcome.NOT_OBSERVED:
        if isinstance(target, PaymentTarget):
            return TEMPLATES["payment_not_observed"]
        attempts_word = "twice" if receipt.automatic_retries == 1 else "once"
        if not isinstance(receipt.observed, CalendarTarget):
            # Create that was acknowledged but never appeared: there is no observed start to quote.
            return TEMPLATES["not_observed_absent"].format(attempts_word=attempts_word)
        return TEMPLATES["not_observed"].format(
            attempts_word=attempts_word,
            observed_start=clock_time(receipt.observed.start, target.timezone),
        )
    if receipt.outcome == Outcome.REJECTED:
        if receipt.reason_code == ReasonCode.APPROVAL_MISMATCH and isinstance(
            target, PaymentTarget
        ):
            return TEMPLATES["approval_mismatch"].format(amount=amount(target))
        if receipt.reason_code == ReasonCode.NO_APPROVAL:
            return TEMPLATES["no_approval"]
        return TEMPLATES["rejected"]
    text = TEMPLATES[
        {
            Outcome.PENDING: "pending",
            Outcome.NEEDS_INPUT: "input",
            Outcome.UNKNOWN: "unknown",
        }[receipt.outcome]
    ]
    if receipt.outcome == Outcome.PENDING and not follow_up:
        text += " " + TEMPLATES["pending_no_follow_up"]
    return text
