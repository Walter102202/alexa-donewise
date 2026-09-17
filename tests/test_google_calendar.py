import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from donewise_adapters.google_calendar import GoogleCalendar, google_event_id
from donewise_harness.contracts import Action, CalendarTarget
from donewise_harness.errors import ReadUnavailable
from donewise_harness.ports import ReadRequest, WriteRequest
from google.oauth2.credentials import Credentials


@pytest.fixture
def calendar():
    adapter = GoogleCalendar(
        "", "test@example.com", credentials=Credentials("token"), run_id="run_a"
    )
    yield adapter
    adapter.close()


@pytest.fixture
def calendar_req():
    start = datetime.now(UTC) + timedelta(days=1)
    return WriteRequest(
        action=Action.CALENDAR_CREATE,
        provider_key="evt_abc123",
        precondition_version=None,
        first_sent_at=None,
        target=CalendarTarget(
            calendar_id="test@example.com",
            event_id="evt_abc123",
            title="Ridge Plumbing",
            start=start,
            end=start + timedelta(hours=1),
            timezone="America/Los_Angeles",
            status="confirmed",
        ),
    )


def event(req, **changes):
    return {
        "id": google_event_id(req.provider_key),
        "etag": '"v1"',
        "summary": req.target.title,
        "status": "confirmed",
        "start": {"dateTime": req.target.start.isoformat(), "timeZone": req.target.timezone},
        "end": {"dateTime": req.target.end.isoformat(), "timeZone": req.target.timezone},
        "extendedProperties": {"private": {"run_id": "run_a"}},
        **changes,
    }


def test_create_read_conflict_and_conditional_patch(calendar, calendar_req, respx_mock):
    row = event(calendar_req)
    post = respx_mock.post(path__regex="/events").respond(200, json=row)
    assert calendar.write(calendar_req).status == "acked"
    payload = json.loads(post.calls.last.request.content)
    assert payload["id"] == row["id"]
    assert payload["extendedProperties"]["private"] == {
        "intent_id": calendar_req.provider_key,
        "run_id": "run_a",
    }
    get = respx_mock.get(path__regex="/" + row["id"]).respond(200, json=row)
    read = calendar.read(ReadRequest(action=calendar_req.action, target=calendar_req.target))
    assert read.observed == calendar_req.target and read.version == '"v1"'
    assert get.calls.last.request.headers["cache-control"] == "no-cache"
    post.respond(409)
    assert calendar.write(calendar_req).status == "already_exists"
    patch = respx_mock.patch(path__regex="/" + row["id"]).respond(412)
    move = calendar_req.model_copy(
        update={"action": Action.CALENDAR_RESCHEDULE, "precondition_version": '"v0"'}
    )
    result = calendar.write(move)
    assert result.status == "precondition_failed" and result.version == '"v1"'
    assert patch.calls.last.request.headers["if-match"] == '"v0"'
    assert calendar.replay_is_safe(move)
    assert not calendar.replay_is_safe(move.model_copy(update={"precondition_version": None}))
    assert len(calendar.latencies) == 5 and all(t >= 0 for _, t in calendar.latencies)


@pytest.mark.parametrize(
    "failure,status",
    [
        (httpx.ReadTimeout, "response_lost"),
        (httpx.RemoteProtocolError, "response_lost"),
        (httpx.ConnectTimeout, "error"),
    ],
)
def test_write_network_classification(calendar, calendar_req, respx_mock, failure, status):
    respx_mock.post(path__regex="/events").mock(side_effect=failure("injected"))
    assert calendar.write(calendar_req).status == status


@pytest.mark.parametrize("status", [404, 503])
def test_read_missing_or_unavailable(calendar, calendar_req, respx_mock, status):
    respx_mock.get(path__regex=google_event_id(calendar_req.provider_key)).respond(status)
    req = ReadRequest(action=calendar_req.action, target=calendar_req.target)
    if status == 404:
        assert not calendar.read(req).found
    else:
        with pytest.raises(ReadUnavailable):
            calendar.read(req)


def test_search_stems_scope_pagination(calendar, calendar_req, respx_mock):
    def respond(request):
        assert request.url.params["privateExtendedProperty"] == "run_id=run_a"
        if "q" in request.url.params:
            return httpx.Response(200, json={"items": []})
        if "pageToken" not in request.url.params:
            return httpx.Response(
                200,
                json={"items": [event(calendar_req, status="cancelled")], "nextPageToken": "next"},
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    event(calendar_req),
                    event(calendar_req, extendedProperties={"private": {"run_id": "run_other"}}),
                ]
            },
        )

    respx_mock.get(path__regex="/events").mock(side_effect=respond)
    assert calendar.search("the plumber") == [calendar_req.target]

