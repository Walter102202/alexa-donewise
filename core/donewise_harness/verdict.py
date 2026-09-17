"""Compare the authorized target with the latest observation (PRD RF-18). Pure functions."""

from dataclasses import dataclass, field

from .contracts import CalendarTarget, PaymentTarget, Target
from .ports import ReadResult

CALENDAR_FIELDS = ("calendar_id", "event_id", "status", "start", "end", "timezone", "title")
PAYMENT_FIELDS = ("status", "amount_minor", "currency", "payee", "concept")


@dataclass(frozen=True)
class Judgement:
    matches: bool
    rule: str
    compared: tuple[str, ...]
    mismatch: str | None = None
    observed: Target | None = None
    version: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


def judge(expected: Target, read: ReadResult) -> Judgement:
    """A read counts as verification only when every compared field equals the target."""
    if not read.found or read.observed is None:
        return Judgement(False, "object_absent", (), "target not found on provider")
    observed = read.observed
    if type(observed) is not type(expected):
        return Judgement(False, "type_mismatch", (), "observed object is of another kind")
    fields = CALENDAR_FIELDS if isinstance(expected, CalendarTarget) else PAYMENT_FIELDS
    rule = (
        "calendar_fields_equal" if isinstance(expected, CalendarTarget) else "payment_fields_equal"
    )
    if isinstance(expected, CalendarTarget) and observed.status == "cancelled":
        return Judgement(False, rule, fields, "event is cancelled", observed, read.version)
    if isinstance(expected, PaymentTarget) and observed.status != "succeeded":
        return Judgement(
            False, rule, fields, f"status is {observed.status}", observed, read.version
        )
    for name in fields:
        if getattr(observed, name) != getattr(expected, name):
            return Judgement(
                False,
                rule,
                fields,
                f"{name}: expected {getattr(expected, name)!r}, "
                f"observed {getattr(observed, name)!r}",
                observed,
                read.version,
            )
    return Judgement(True, rule, fields, None, observed, read.version)
