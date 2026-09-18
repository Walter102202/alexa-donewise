import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from donewise_harness import contracts as c
from donewise_harness.ports import ReadRequest, ReadResult, WriteRequest, WriteResult
from donewise_harness.spoken import clock_time, render_spoken, span
from pydantic import TypeAdapter, ValidationError

ROOT = Path(__file__).resolve().parents[1]
STORY = json.loads((ROOT / "sim/fixtures/story-3min.json").read_text(encoding="utf-8"))
SPECS = {spec.name: spec for spec in c.TOOL_SPECS}
ROWS = [row for state in STORY["states"] for row in state["receipts"]]
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
CONTEXT = {"now": NOW}
CALENDAR = ROWS[0]["result"]["expected"]
PAYMENT = ROWS[1]["result"]["expected"]
INPUTS = {
    "calendar_create_verified": dict(
        submission_id="submit-1",
        title="Ridge Plumbing",
        start=CALENDAR["start"],
        end=CALENDAR["end"],
        timezone=CALENDAR["timezone"],
    ),
    "calendar_reschedule_verified": dict(
        submission_id="submit-2",
        event_id="evt_plumber",
        new_start=CALENDAR["start"],
        new_end=CALENDAR["end"],
        timezone=CALENDAR["timezone"],
    ),
    "payment_charge_verified": {
        "submission_id": "submit-3",
        **{key: value for key, value in PAYMENT.items() if key != "status"},
    },
    "operation_get": {"operation_id": "op_payment"},
    "approval_grant": {"approval_request_id": "apr_request_deposit", "consent_token": "test-only"},
    "receipts_recap": {"run_id": STORY["run_id"]},
}


@pytest.mark.parametrize("spec", c.TOOL_SPECS, ids=lambda spec: spec.name)
def test_each_tool_input_and_output_roundtrip(spec):
    inp = spec.input_model.model_validate(INPUTS[spec.name], context=CONTEXT)
    assert spec.input_model.model_validate_json(inp.model_dump_json(), context=CONTEXT) == inp
    if spec.name == "approval_grant":
        out = c.ApprovalGrantResult(
            approval_id="apr_deposit",
            expires_at=NOW,
            bound_to=dict(
                intent_id="int_payment", amount_minor=6000, currency="USD", payee="Ridge Plumbing"
            ),
            granted_by="session_ui",
        )
    else:
        out = spec.output_model.model_validate(
            next(row["result"] for row in ROWS if row["tool"] == spec.name)
        )
    assert spec.output_model.model_validate_json(out.model_dump_json()) == out


POLICY = {
    c.Outcome.VERIFIED: [c.Claim.EFFECT_VERIFIED, c.Claim.LATEST_READ_MATCHES_TARGET],
    c.Outcome.PENDING: [c.Claim.OPERATION_IN_PROGRESS],
    c.Outcome.NEEDS_APPROVAL: [c.Claim.APPROVAL_REQUIRED, c.Claim.NOTHING_CHARGED],
    c.Outcome.NEEDS_INPUT: [],
    c.Outcome.NOT_OBSERVED: [c.Claim.EFFECT_UNVERIFIED, c.Claim.LATEST_READ_DIFFERS_FROM_TARGET],
    c.Outcome.UNKNOWN: [c.Claim.EFFECT_UNVERIFIED],
    c.Outcome.REJECTED: [],
}


@pytest.mark.parametrize("outcome", c.Outcome)
@pytest.mark.parametrize("action", c.Action)
def test_policy_and_receipt_reject_forged_claims(outcome, action):
    claims = POLICY[outcome].copy()
    if action == c.Action.PAYMENT_CHARGE:
        if outcome == c.Outcome.VERIFIED:
            claims.append(c.Claim.CHARGED_ONCE)
        elif outcome == c.Outcome.REJECTED:
            claims.append(c.Claim.NOTHING_CHARGED)
    assert c.claims_for(outcome, action) == claims
    assert c.may_claim_success(outcome) == (outcome == c.Outcome.VERIFIED)
    target = PAYMENT if action == c.Action.PAYMENT_CHARGE else CALENDAR
    payload = {
        key: value for key, value in ROWS[0]["result"].items() if key in c.Receipt.model_fields
    }
    payload.update(
        action=action,
        outcome=outcome,
        expected=target,
        observed=target,
        allowed_claims=claims,
        may_claim_success=outcome == c.Outcome.VERIFIED,
        writes_applied=0,
    )
    payload["evidence"] = {
        **payload["evidence"],
        "source": ("fake_payments" if action == c.Action.PAYMENT_CHARGE else "fake_calendar"),
    }
    c.Receipt.model_validate(payload)
    for change in (
        {"may_claim_success": not payload["may_claim_success"]},
        {"allowed_claims": [*claims, c.Claim.EFFECT_VERIFIED]},
    ):
        with pytest.raises(ValidationError):
            c.Receipt.model_validate({**payload, **change})
    if outcome in (c.Outcome.NEEDS_APPROVAL, c.Outcome.REJECTED):
        with pytest.raises(ValidationError):
            c.Receipt.model_validate({**payload, "writes_applied": 1})


@pytest.mark.parametrize(
    ("tool", "change"),
    [
        ("calendar_create_verified", {"end": "2026-09-17T15:00:00Z"}),
        ("calendar_create_verified", {"start": "2026-09-17T16:00:00"}),
        ("calendar_create_verified", {"timezone": "Mars/Olympus"}),
        (
            "calendar_create_verified",
            {"start": "2028-09-17T16:00:00Z", "end": "2028-09-17T17:00:00Z"},
        ),
        ("calendar_create_verified", {"start": "2026-09-15T16:00:00Z"}),
        ("calendar_reschedule_verified", {"event_query": "plumber"}),
        ("calendar_reschedule_verified", {"event_id": None}),
        ("calendar_reschedule_verified", {"new_end": CALENDAR["start"]}),
        ("payment_charge_verified", {"amount_minor": 0}),
        ("payment_charge_verified", {"amount_minor": 1.5}),
        ("payment_charge_verified", {"amount_minor": True}),
        ("payment_charge_verified", {"currency": "US"}),
        ("payment_charge_verified", {"currency": "usd"}),
        ("payment_charge_verified", {"payee": "  "}),
        ("payment_charge_verified", {"may_claim_success": True}),
        ("approval_grant", {"consent_token": ""}),
    ],
)
def test_invalid_inputs(tool, change):
    with pytest.raises(ValidationError):
        SPECS[tool].input_model.model_validate({**INPUTS[tool], **change}, context=CONTEXT)


def test_input_window_boundary_and_query_alternative():
    leap_day = datetime(2028, 2, 29, 12, tzinfo=UTC)
    limit = datetime(2029, 2, 28, 12, tzinfo=UTC)
    data = {**INPUTS["calendar_create_verified"], "start": limit, "end": limit + timedelta(hours=1)}
    c.CalendarCreateInput.model_validate(data, context={"now": leap_day})
    with pytest.raises(ValidationError):
        c.CalendarCreateInput.model_validate(
            {**data, "start": limit + timedelta(seconds=1)}, context={"now": leap_day}
        )
    c.CalendarRescheduleInput.model_validate(
        {**INPUTS["calendar_reschedule_verified"], "event_id": None, "event_query": "plumber"},
        context=CONTEXT,
    )


@pytest.mark.parametrize(
    ("prefix", "identity"),
    [
        ("int_", c.IntentId),
        ("op_", c.OperationId),
        ("att_", c.AttemptId),
        ("ev_", c.EvidenceId),
        ("rcpt_", c.ReceiptId),
        ("apr_", c.ApprovalId),
        ("run_", c.RunId),
        ("evt_", c.EventId),
        ("pi_", c.PaymentIntentId),
    ],
)
def test_identity_prefixes(prefix, identity):
    adapter = TypeAdapter(identity)
    assert adapter.validate_python(c.new_id(prefix)).startswith(prefix)
    for invalid in (prefix, "wrong_value", prefix + "bad value"):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)


@pytest.mark.parametrize(
    "change",
    [
        {"observed": None},
        {"evidence": None},
        {"receipt_id": None},
        {"expected": PAYMENT},
        {"event_id": "evt_wrong"},
        {"writes_applied": -1},
        {"automatic_retries": 2},
        {"observed_at": "2026-09-17T02:40:00Z"},
    ],
)
def test_receipt_evidence_and_identity_consistency(change):
    with pytest.raises(ValidationError):
        c.CalendarCreateResult.model_validate({**ROWS[0]["result"], **change})


def test_story_shapes_spoken_and_shared_identity():
    assert [state["state"] for state in STORY["states"]] == ["1", "2", "2b", "3", "4", "5"]
    assert len(ROWS) == 7
    results = [SPECS[row["tool"]].output_model.model_validate(row["result"]) for row in ROWS]
    expected = [
        "It's on your calendar: Ridge Plumbing, tomorrow 9 to 10 AM.",
        "For the deposit: a $60 test charge for Ridge Plumbing. Should I charge it?",
        "I'm on it. I'll confirm in a moment.",
        "Done: a $60 test charge is recorded for Ridge Plumbing's deposit, charged once. "
        "Confirmation pi_story_deposit. You don't need to try again.",
        "I couldn't confirm the change. I tried twice; the latest calendar check still shows 9 AM.",
        "The plumber is now at 10 to 11 AM. I read it back from your calendar.",
        "From the receipts in this conversation: the plumber is at 10 to 11 AM, read back at "
        "7:44 PM. One $60 test charge for the deposit, read back at 7:40 PM. "
        "Nothing new was written.",
    ]
    for result, phrase in zip(results, expected, strict=True):
        assert render_spoken(result) == result.spoken == phrase
        assert type(result).model_validate_json(result.model_dump_json()) == result
        assert result.run_id == STORY["run_id"]
    assert results[1].operation_id == results[2].operation_id == results[3].operation_id
    assert results[4].intent_id == results[5].intent_id
    assert results[4].operation_id == results[5].operation_id
    assert results[3].charges_applied == 1
    assert results[4].automatic_retries == 1
    assert results[5].automatic_retries == 0


def test_timezones_normalize_utc_and_render_dst_and_noon():
    target = c.CalendarTarget.model_validate({**CALENDAR, "start": "2026-09-17T09:00:00-07:00"})
    assert target.start.tzinfo == UTC
    assert span(target) == "9 to 10 AM"
    assert clock_time(datetime(2026, 1, 17, 17, tzinfo=UTC), target.timezone) == "9 AM"
    assert clock_time(datetime(2026, 7, 17, 17, tzinfo=UTC), target.timezone) == "10 AM"
    across_noon = c.CalendarTarget.model_validate(
        {**CALENDAR, "start": "2026-09-17T18:00:00Z", "end": "2026-09-17T19:30:00Z"}
    )
    assert span(across_noon) == "11 AM to 12:30 PM"


def test_ports_data_roundtrip_and_read_consistency():
    values = [
        WriteRequest(
            action="CALENDAR_CREATE",
            target=CALENDAR,
            provider_key="provider-key",
            precondition_version=None,
            first_sent_at=None,
        ),
        WriteResult(status="response_lost", provider_ref=None, version=None, error=None),
        ReadRequest(action="CALENDAR_CREATE", target=CALENDAR),
        ReadResult(
            found=True, observed=CALENDAR, version="etag", observed_at=NOW, source="fake_calendar"
        ),
    ]
    for value in values:
        assert type(value).model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        ReadRequest(action="CALENDAR_CREATE")
    with pytest.raises(ValidationError):
        ReadResult(found=True, observed=None, version=None, observed_at=NOW, source="fake_calendar")


def test_verified_payment_variants_reject_missing_proof_and_duplicate_counts():
    view = ROWS[3]["result"]
    charge = {key: value for key, value in view.items() if key != "history"}
    charge.update(approval_id="apr_deposit", approval_request=None)
    result = c.PaymentChargeResult.model_validate(charge)
    assert c.PaymentChargeResult.model_validate_json(result.model_dump_json()) == result
    for model, payload in ((c.OperationView, view), (c.PaymentChargeResult, charge)):
        for change in ({"payment_intent_id": None}, {"charges_applied": 2, "writes_applied": 2}):
            with pytest.raises(ValidationError):
                model.model_validate({**payload, **change})
    with pytest.raises(ValidationError):
        c.PaymentChargeResult.model_validate({**charge, "approval_id": None})


@pytest.mark.parametrize(
    ("outcome", "reason", "phrase"),
    [
        (
            "UNKNOWN",
            "READ_TIMEOUT",
            "I couldn't check the result yet. Nothing is confirmed. I'll keep checking.",
        ),
        ("REJECTED", "NO_APPROVAL", "I won't charge anything without your OK."),
        ("REJECTED", "APPROVAL_MISMATCH", "That's a different amount. I need a new OK for $60."),
    ],
)
def test_non_success_spoken_does_not_reuse_stored_success(outcome, reason, phrase):
    payload = {
        **ROWS[1]["result"],
        "outcome": outcome,
        "reason_code": reason,
        "spoken": "Done!",
        "allowed_claims": c.claims_for(c.Outcome(outcome), c.Action.PAYMENT_CHARGE),
    }
    assert render_spoken(c.PaymentChargeResult.model_validate(payload)) == phrase


def test_schemas_are_current(tmp_path):
    export = runpy.run_path(str(ROOT / "scripts/export_schemas.py"))["export_schemas"]
    export(tmp_path)
    committed = ROOT / "docs/schemas"
    assert len(list(tmp_path.glob("*.json"))) == 12
    assert {p.name for p in tmp_path.glob("*.json")} == {p.name for p in committed.glob("*.json")}
    for path in tmp_path.glob("*.json"):
        assert path.read_bytes() == (committed / path.name).read_bytes()


def test_every_input_property_has_a_description():
    missing = []
    for spec in c.TOOL_SPECS:
        for name, prop in spec.input_model.model_json_schema()["properties"].items():
            if not prop.get("description", "").strip():
                missing.append(f"{spec.name}.{name}")
    assert missing == []
